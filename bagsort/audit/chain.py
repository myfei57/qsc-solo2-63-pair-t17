"""Tamper evident audit chain.

Each entry carries the digest of the entry before it, so removing or editing a
record in the middle breaks every digest after it. Entries also carry the
handling stage that produced them, which lets the timeline spot an event that
claims to have happened before a step it depends on.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from bagsort.clock import Clock
from bagsort.model.entities import AuditEntry
from bagsort.ns.topology import Topology
from bagsort.store.store import Store

GENESIS = "0" * 64


class AuditChain:
    """Append-only, hash linked record of what the plant did."""

    def __init__(self, store: Store, clock: Clock, topology: Topology) -> None:
        self._store = store
        self._clock = clock
        self._topology = topology

    def entries(self) -> list[AuditEntry]:
        return list(self._store.state().audit)

    def count(self) -> int:
        return len(self._store.state().audit)

    def last(self) -> AuditEntry | None:
        audit = self._store.state().audit
        return audit[-1] if audit else None

    def last_digest(self) -> str:
        entry = self.last()
        return entry.digest if entry else GENESIS

    def record(
        self,
        kind: str,
        subject: str,
        stage: str,
        detail: dict[str, Any] | None = None,
        at: str | None = None,
    ) -> AuditEntry:
        if not self._topology.contains(stage):
            raise ValueError(f"unknown handling stage {stage!r}")
        sequence = self.count() + 1
        payload: dict[str, Any] = {
            "stage": stage,
            "stage_index": self._topology.index_of(stage),
        }
        if detail:
            payload.update(detail)
        entry = AuditEntry(
            sequence=sequence,
            kind=kind,
            subject=subject,
            detail=payload,
            prev_digest=self.last_digest(),
            at=at or self._clock.now_iso(),
        )
        digest = digest_of(entry)
        entry = AuditEntry(
            sequence=entry.sequence,
            kind=entry.kind,
            subject=entry.subject,
            detail=entry.detail,
            prev_digest=entry.prev_digest,
            digest=digest,
            at=entry.at,
        )
        with self._store.session() as session:
            session.state.audit.append(entry)
            session.record("audit.append", {"entry": entry.as_dict()}, entry.at)
        return entry

    def for_subject(self, subject: str) -> list[AuditEntry]:
        return [entry for entry in self.entries() if entry.subject == subject]

    def by_kind(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for entry in self.entries():
            summary[entry.kind] = summary.get(entry.kind, 0) + 1
        return dict(sorted(summary.items()))

    def by_stage(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for entry in self.entries():
            stage = str(entry.detail.get("stage", "unknown"))
            summary[stage] = summary.get(stage, 0) + 1
        return dict(sorted(summary.items()))

    def timeline(self, subject: str | None = None) -> list[AuditEntry]:
        """Entries ordered by the stage ordinal, then by commit sequence."""

        selected = self.entries() if subject is None else self.for_subject(subject)
        return sorted(
            selected,
            key=lambda entry: (int(entry.detail.get("stage_index", -1)), entry.sequence),
        )

    def out_of_order(self) -> list[AuditEntry]:
        """Entries whose stage ordinal sits before the previous one for the same subject."""

        worst: dict[str, int] = {}
        flagged: list[AuditEntry] = []
        for entry in self.entries():
            index = int(entry.detail.get("stage_index", -1))
            previous = worst.get(entry.subject)
            if previous is not None and index < previous:
                flagged.append(entry)
            worst[entry.subject] = max(index, previous if previous is not None else index)
        return flagged

    def verify(self) -> bool:
        """Recompute every digest and confirm the chain links up."""

        previous = GENESIS
        for entry in self.entries():
            if entry.prev_digest != previous:
                return False
            if digest_of(entry) != entry.digest:
                return False
            previous = entry.digest
        return True


def digest_of(entry: AuditEntry) -> str:
    """Deterministic digest over the fields that must not change."""

    material = json.dumps(
        [
            entry.sequence,
            entry.kind,
            entry.subject,
            entry.detail,
            entry.prev_digest,
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
