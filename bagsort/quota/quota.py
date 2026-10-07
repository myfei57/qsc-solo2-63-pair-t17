"""Per flight sorting allowance, plus temporary loans between flights.

The stored value is how many bags the flight may still take. A flight with no
entry on record is unlimited (:data:`UNLIMITED`, a sentinel below zero), so a
configured allowance that has been spent down to zero correctly reads as
exhausted. Both movements are committed commands, so the allowance survives a
restart instead of living in a process variable.

Loans
-----
A flight whose allowance is spent may borrow from a neighbour that has bags
to spare. The design decision, made once and held everywhere:

* **The borrowed allowance merges into the borrower's own limit** (it counts
  against the borrower's ceiling), so the check-in desk and ``consume`` need
  no special case. The debt itself is **booked as a separate payable** — a
  :class:`~bagsort.model.entities.QuotaLoan` record per loan with principal,
  repaid, written-off and outstanding columns — instead of being folded into
  either limit number.
* The alternative (keeping borrowed allowance in a separate spendable bucket)
  was rejected: on flight close the bucket boundary blurs once bags are
  sorted, and there is no honest answer to "who absorbs the loss". With the
  merged model, close-time handling is explicit: the outstanding balance is
  recalled from whatever allowance the borrower has left, and **the shortfall
  is bad debt borne by the lender** — the side that chose to lend — recorded
  as ``written_off`` on the loan.

Every loan movement is a committed journal command (``quota.loan_open``,
``quota.loan_repay``, ``quota.loan_rollback`` plus the paired ``quota.adjust``
entries), so the allowance ledger, the loan book and the audit chain can be
cross-checked with :func:`crosscheck_loans`, and the whole history replays
deterministically after a restart.
"""

from __future__ import annotations

from typing import Any, Iterable

from bagsort.clock import Clock
from bagsort.errors import ConflictError, QuotaError, ValidationError
from bagsort.model.entities import QuotaLoan
from bagsort.model.enums import FlightState, LoanState
from bagsort.model.errors import unknown_loan
from bagsort.store.store import Store

UNLIMITED = -1


class QuotaBook:
    """Tracks how many more bags each flight may accept."""

    def __init__(self, store: Store, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def set_limit(self, flight_id: str, limit: int) -> int:
        if not flight_id:
            raise ValidationError("flight id must not be empty")
        if limit < 0:
            raise ValidationError("quota limit must not be negative")
        with self._store.session() as session:
            session.state.quota_limits[flight_id] = limit
            session.record(
                "quota.set",
                {"flight_id": flight_id, "limit": limit},
                self._clock.now_iso(),
            )
        return limit

    def limit(self, flight_id: str) -> int:
        return self._store.state().quota_limits.get(flight_id, UNLIMITED)

    def is_limited(self, flight_id: str) -> bool:
        return self.limit(flight_id) >= 0

    def available(self, flight_id: str) -> int:
        """Remaining bags, or ``-1`` when the flight is unlimited."""

        return self.limit(flight_id)

    def allowed(self, flight_id: str) -> bool:
        limit = self.limit(flight_id)
        return limit < 0 or limit > 0

    def consume(self, flight_id: str, count: int = 1) -> bool:
        if count < 0:
            raise ValidationError("consume count must not be negative")
        limit = self.limit(flight_id)
        if limit < 0:
            return True
        if limit - count < 0:
            return False
        with self._store.session() as session:
            session.state.quota_limits[flight_id] = limit - count
            session.record(
                "quota.adjust",
                {"flight_id": flight_id, "delta": -count},
                self._clock.now_iso(),
            )
        return True

    def release(self, flight_id: str, count: int = 1) -> int:
        if count < 0:
            raise ValidationError("release count must not be negative")
        limit = self.limit(flight_id)
        if limit < 0:
            return UNLIMITED
        with self._store.session() as session:
            session.state.quota_limits[flight_id] = limit + count
            session.record(
                "quota.adjust",
                {"flight_id": flight_id, "delta": count},
                self._clock.now_iso(),
            )
        return limit + count

    def limits(self) -> dict[str, int]:
        return dict(sorted(self._store.state().quota_limits.items()))

    # -- loans between flights ---------------------------------------------

    def lend(self, lender: str, borrower: str, amount: int, due_at: str = "") -> QuotaLoan:
        """Move ``amount`` of allowance from ``lender`` to ``borrower``.

        The borrower's limit grows by the same amount the lender's shrinks;
        the payable is booked as one :class:`QuotaLoan` so the debt stays
        visible until it is repaid, written off or rolled back.
        """

        if not lender or not borrower:
            raise ValidationError("loan flights must not be empty")
        if lender == borrower:
            raise ValidationError("a flight cannot lend allowance to itself")
        if amount <= 0:
            raise ValidationError("loan amount must be positive")
        if not self.is_limited(lender):
            raise QuotaError(f"flight {lender!r} has no configured allowance to lend from")
        if not self.is_limited(borrower):
            raise QuotaError(f"flight {borrower!r} has no configured allowance to borrow into")
        if self.limit(lender) < amount:
            raise QuotaError(
                f"flight {lender!r} has only {self.limit(lender)} bags of allowance left"
            )
        now = self._clock.now_iso()
        loan = QuotaLoan(
            id=f"LOAN-{len(self._store.state().quota_loans) + 1:06d}",
            lender=lender,
            borrower=borrower,
            amount=amount,
            borrowed_at=now,
            due_at=due_at.strip(),
        )
        with self._store.session() as session:
            session.state.quota_limits[lender] -= amount
            session.state.quota_limits[borrower] += amount
            session.state.quota_loans[loan.id] = loan
            session.record("quota.adjust", {"flight_id": lender, "delta": -amount}, now)
            session.record("quota.adjust", {"flight_id": borrower, "delta": amount}, now)
            session.record("quota.loan_open", {"loan": loan.as_dict()}, now)
        return loan

    def repay(self, loan_id: str, count: int | None = None) -> QuotaLoan:
        """Return up to ``count`` bags of allowance to the lender.

        The repayment is capped by what the borrower's limit can actually
        cover; the uncovered rest stays outstanding (and becomes the lender's
        bad debt only if a close rolls the loan back). A loan that is no
        longer open refuses any further repayment, so the same debt can never
        be settled twice.
        """

        loan = self.loan(loan_id)
        if loan.state is not LoanState.OPEN:
            raise ConflictError(f"loan {loan_id!r} is already {loan.state.value}")
        if count is None:
            count = loan.outstanding
        if count <= 0:
            raise ValidationError("repay count must be positive")
        if count > loan.outstanding:
            raise ValidationError("repay count exceeds the outstanding balance")
        applied = min(count, max(self.limit(loan.borrower), 0))
        if applied == 0:
            raise QuotaError(
                f"flight {loan.borrower!r} has no allowance left to repay with"
            )
        now = self._clock.now_iso()
        with self._store.session() as session:
            session.state.quota_limits[loan.borrower] -= applied
            session.state.quota_limits[loan.lender] += applied
            repaid = loan.repaid + applied
            session.state.quota_loans[loan.id] = loan.evolved(
                repaid=repaid,
                state=LoanState.SETTLED if repaid >= loan.amount else loan.state,
                settled_at=now if repaid >= loan.amount else loan.settled_at,
            )
            session.record(
                "quota.adjust", {"flight_id": loan.borrower, "delta": -applied}, now
            )
            session.record("quota.adjust", {"flight_id": loan.lender, "delta": applied}, now)
            session.record(
                "quota.loan_repay",
                {"loan_id": loan.id, "requested": count, "count": applied, "at": now},
                now,
            )
        return self.loan(loan_id)

    def rollback_for_flight(self, flight_id: str) -> list[tuple[QuotaLoan, int]]:
        """Recall every open loan touching ``flight_id`` because it is closing.

        For each loan the outstanding balance is recalled from the borrower's
        remaining allowance and returned to the lender; whatever the borrower
        can no longer cover is written off as the lender's bad debt. All of it
        lands in a single commit, so the two allowance accounts and the loan
        book can never drift apart. Already settled or rolled-back loans are
        untouched, which makes a repeated call a no-op.
        """

        targets = [
            loan
            for loan in self.open_loans()
            if flight_id in (loan.lender, loan.borrower)
        ]
        if not targets:
            return []
        now = self._clock.now_iso()
        results: list[tuple[QuotaLoan, int]] = []
        with self._store.session() as session:
            limits = session.state.quota_limits
            for loan in targets:
                returned = min(loan.outstanding, max(limits.get(loan.borrower, 0), 0))
                written_off = loan.outstanding - returned
                if returned:
                    limits[loan.borrower] = limits.get(loan.borrower, 0) - returned
                    limits[loan.lender] = limits.get(loan.lender, 0) + returned
                    session.record(
                        "quota.adjust",
                        {"flight_id": loan.borrower, "delta": -returned},
                        now,
                    )
                    session.record(
                        "quota.adjust", {"flight_id": loan.lender, "delta": returned}, now
                    )
                updated = loan.evolved(
                    repaid=loan.repaid + returned,
                    written_off=loan.written_off + written_off,
                    state=LoanState.ROLLED_BACK,
                    settled_at=now,
                )
                session.state.quota_loans[loan.id] = updated
                session.record(
                    "quota.loan_rollback",
                    {
                        "loan_id": loan.id,
                        "returned": returned,
                        "written_off": written_off,
                        "at": now,
                    },
                    now,
                )
                results.append((updated, returned))
        return results

    def loan(self, loan_id: str) -> QuotaLoan:
        loan = self._store.state().quota_loans.get(loan_id)
        if loan is None:
            raise unknown_loan(loan_id)
        return loan

    def loans(self, flight_id: str | None = None) -> list[QuotaLoan]:
        """Every loan on record, oldest first; optionally one flight's loans."""

        loans = self._store.state().quota_loans
        selected = [loans[key] for key in sorted(loans)]
        if flight_id:
            selected = [
                loan for loan in selected if flight_id in (loan.lender, loan.borrower)
            ]
        return selected

    def open_loans(self, flight_id: str | None = None) -> list[QuotaLoan]:
        return [
            loan for loan in self.loans(flight_id) if loan.state is LoanState.OPEN
        ]

    def outstanding(self, flight_id: str | None = None) -> int:
        """Balance still owed across open loans, in total or for one flight."""

        return sum(loan.outstanding for loan in self.open_loans(flight_id))

    def status(self) -> list[dict[str, object]]:
        """One row per flight that has an allowance on record."""

        return [
            {
                "flight_id": flight_id,
                "limit": limit,
                "unlimited": limit < 0,
                "allowed": limit < 0 or limit > 0,
            }
            for flight_id, limit in sorted(self._store.state().quota_limits.items())
        ]


def crosscheck_loans(
    loans: list[QuotaLoan],
    journal_entries: Iterable[Any],
    audit_entries: Iterable[Any],
    flights: Iterable[Any],
) -> list[str]:
    """Cross-check the loan book against the journal, the audit chain and flights.

    Returns one problem string per inconsistency found; an empty list means
    the allowance ledger, the committed commands, the audit trail and the
    flight states all tell the same story.
    """

    problems: list[str] = []
    journal = list(journal_entries)
    audits = list(audit_entries)
    flight_states = {flight.id: flight.state for flight in flights}
    for loan in loans:
        if loan.repaid < 0 or loan.written_off < 0 or loan.outstanding < 0:
            problems.append(f"loan {loan.id}: negative balance in the loan book")
        if loan.state is LoanState.SETTLED and loan.repaid != loan.amount:
            problems.append(
                f"loan {loan.id}: settled with repaid {loan.repaid} != amount {loan.amount}"
            )
        if loan.state is LoanState.ROLLED_BACK and loan.outstanding != 0:
            problems.append(
                f"loan {loan.id}: rolled back with outstanding {loan.outstanding}"
            )
        opens = [
            entry
            for entry in journal
            if entry.kind == "quota.loan_open"
            and entry.payload.get("loan", {}).get("id") == loan.id
        ]
        if len(opens) != 1:
            problems.append(
                f"loan {loan.id}: journal holds {len(opens)} quota.loan_open commands"
            )
        repays = [
            entry
            for entry in journal
            if entry.kind == "quota.loan_repay" and entry.payload.get("loan_id") == loan.id
        ]
        rollbacks = [
            entry
            for entry in journal
            if entry.kind == "quota.loan_rollback"
            and entry.payload.get("loan_id") == loan.id
        ]
        repaid_journal = sum(int(entry.payload.get("count", 0)) for entry in repays)
        repaid_journal += sum(int(entry.payload.get("returned", 0)) for entry in rollbacks)
        if repaid_journal != loan.repaid:
            problems.append(
                f"loan {loan.id}: journal repaid {repaid_journal} != book {loan.repaid}"
            )
        written_journal = sum(
            int(entry.payload.get("written_off", 0)) for entry in rollbacks
        )
        if written_journal != loan.written_off:
            problems.append(
                f"loan {loan.id}: journal written off {written_journal} "
                f"!= book {loan.written_off}"
            )
        if loan.state is LoanState.ROLLED_BACK and len(rollbacks) != 1:
            problems.append(
                f"loan {loan.id}: journal holds {len(rollbacks)} rollback commands"
            )
        if loan.state is not LoanState.ROLLED_BACK and rollbacks:
            problems.append(f"loan {loan.id}: rolled back in the journal but open in the book")
        audit_kinds: dict[str, int] = {}
        for entry in audits:
            if entry.subject == loan.id:
                audit_kinds[entry.kind] = audit_kinds.get(entry.kind, 0) + 1
        if audit_kinds.get("quota_loan", 0) != 1:
            problems.append(
                f"loan {loan.id}: audit trail holds "
                f"{audit_kinds.get('quota_loan', 0)} borrow entries"
            )
        if audit_kinds.get("quota_repay", 0) != len(repays):
            problems.append(
                f"loan {loan.id}: audit trail holds {audit_kinds.get('quota_repay', 0)} "
                f"repay entries for {len(repays)} journal commands"
            )
        if audit_kinds.get("quota_loan_rollback", 0) != len(rollbacks):
            problems.append(
                f"loan {loan.id}: audit trail holds "
                f"{audit_kinds.get('quota_loan_rollback', 0)} rollback entries for "
                f"{len(rollbacks)} journal commands"
            )
        if loan.state is LoanState.OPEN:
            for flight_id in (loan.lender, loan.borrower):
                state = flight_states.get(flight_id)
                if state is None:
                    problems.append(f"loan {loan.id}: flight {flight_id} is not registered")
                elif state is FlightState.CLOSED:
                    problems.append(
                        f"loan {loan.id}: flight {flight_id} closed with the loan still open"
                    )
    return problems
