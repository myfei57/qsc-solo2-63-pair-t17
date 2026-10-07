"""Temporary allowance lending between flights.

One flight's allowance can run out while the neighbour's sits idle, so a
flight may lend part of its allowance to another flight for a while.

Accounting model (chosen once, do not mix): **the borrowed allowance occupies
the borrower's own limit.** At lend time the amount moves from the lender's
``quota_limits`` entry into the borrower's, so the allowance ledger stays the
single source of truth for check-in and lent quota cannot be spent twice.
The loan document in ``quota_loans`` is the separate payable/receivable
record: who lent, who borrowed, how much, and when it is due back.

**Bad debt belongs to the lender.** When a flight closes, every open loan
that touches it is rolled back, oldest loan first: the borrower returns up to
the loan amount from whatever allowance it still holds, and the shortfall —
allowance genuinely consumed by checked-in bags — is written off as
``bad_debt`` on the loan document, borne by the lender. The alternative
(keeping borrowed quota in a separate pool) was rejected because a close
would then have to void a second ledger whose consumption cannot be traced
bag by bag; moving the quota up front keeps both sides' books exact.

Every transition is a committed journal command: ``quota.lend``,
``quota.repay`` and ``quota.rollback`` carry the loan document, and the
paired ``quota.adjust`` movements carry the loan id, so the allowance ledger,
the loan ledger and the audit chain reconcile entry by entry. A loan settles
exactly once: repaying a settled loan is a conflict, and rollback only
touches loans that are still open.
"""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.errors import ConflictError, NotFoundError, QuotaError, ValidationError
from bagsort.flight.book import FlightBook
from bagsort.model.entities import QuotaLoan
from bagsort.model.enums import LoanState
from bagsort.store.store import Store


class LoanBook:
    """Owns the lifecycle of every allowance loan between flights."""

    def __init__(self, store: Store, clock: Clock, book: FlightBook) -> None:
        self._store = store
        self._clock = clock
        self._book = book

    # -- commands ----------------------------------------------------------

    def lend(self, lender_id: str, borrower_id: str, amount: int, due_at: str) -> QuotaLoan:
        """Move ``amount`` of allowance from the lender to the borrower."""

        lender_id = (lender_id or "").strip()
        borrower_id = (borrower_id or "").strip()
        if not lender_id or not borrower_id:
            raise ValidationError("lender and borrower must not be empty")
        if lender_id == borrower_id:
            raise ValidationError("lender and borrower must be different flights")
        if amount <= 0:
            raise ValidationError("loan amount must be positive")
        due = (due_at or "").strip()
        if not due:
            raise ValidationError("loan due time must not be empty")
        self._book.require_open(lender_id)
        self._book.require_open(borrower_id)
        limits = self._store.state().quota_limits
        for flight_id in (lender_id, borrower_id):
            if flight_id not in limits:
                raise ValidationError(
                    f"flight {flight_id!r} has no allowance on record and cannot lend"
                )
        if limits[lender_id] < amount:
            raise QuotaError(
                f"flight {lender_id!r} has only {limits[lender_id]} allowance left"
            )
        now = self._clock.now_iso()
        loan = QuotaLoan(
            id=f"loan-{len(self._store.state().quota_loans) + 1:06d}",
            lender_id=lender_id,
            borrower_id=borrower_id,
            amount=amount,
            due_at=due,
            created_at=now,
        )
        with self._store.session() as session:
            session.state.quota_limits[lender_id] = limits[lender_id] - amount
            session.record(
                "quota.adjust",
                {
                    "flight_id": lender_id,
                    "delta": -amount,
                    "reason": "loan_lend",
                    "loan_id": loan.id,
                },
                now,
            )
            session.state.quota_limits[borrower_id] = limits[borrower_id] + amount
            session.record(
                "quota.adjust",
                {
                    "flight_id": borrower_id,
                    "delta": amount,
                    "reason": "loan_lend",
                    "loan_id": loan.id,
                },
                now,
            )
            session.state.quota_loans[loan.id] = loan
            session.record("quota.lend", {"loan": loan.as_dict()}, now)
        return loan

    def repay(self, loan_id: str) -> QuotaLoan:
        """Settle an open loan in full, moving the allowance back."""

        loan = self.get(loan_id)
        if loan.state is not LoanState.OPEN:
            raise ConflictError(
                f"loan {loan.id!r} is already {loan.state.value} and cannot be repaid again"
            )
        remaining = self._store.state().quota_limits.get(loan.borrower_id, 0)
        if remaining < loan.amount:
            raise QuotaError(
                f"flight {loan.borrower_id!r} holds only {remaining} of the borrowed "
                f"{loan.amount}; the loan must wait for close-time rollback"
            )
        now = self._clock.now_iso()
        settled = loan.evolved(
            state=LoanState.REPAID,
            settled_at=now,
            returned=loan.amount,
            bad_debt=0,
        )
        with self._store.session() as session:
            session.state.quota_limits[loan.borrower_id] = remaining - loan.amount
            session.record(
                "quota.adjust",
                {
                    "flight_id": loan.borrower_id,
                    "delta": -loan.amount,
                    "reason": "loan_repay",
                    "loan_id": loan.id,
                },
                now,
            )
            session.state.quota_limits[loan.lender_id] = (
                session.state.quota_limits.get(loan.lender_id, 0) + loan.amount
            )
            session.record(
                "quota.adjust",
                {
                    "flight_id": loan.lender_id,
                    "delta": loan.amount,
                    "reason": "loan_repay",
                    "loan_id": loan.id,
                },
                now,
            )
            session.state.quota_loans[loan.id] = settled
            session.record("quota.repay", {"loan": settled.as_dict()}, now)
        return settled

    def rollback_for_flight(self, flight_id: str) -> list[QuotaLoan]:
        """Settle every open loan touching a closing flight, oldest first.

        The borrower returns what it still holds; the shortfall is bad debt
        borne by the lender. Loans already settled are never touched again,
        so a second rollback for the same flight is a no-op.
        """

        open_loans = [
            loan
            for loan in self.history(flight_id=flight_id, state=LoanState.OPEN.value)
        ]
        if not open_loans:
            return []
        now = self._clock.now_iso()
        settled: list[QuotaLoan] = []
        with self._store.session() as session:
            for loan in open_loans:
                remaining = max(session.state.quota_limits.get(loan.borrower_id, 0), 0)
                returned = min(loan.amount, remaining)
                done = loan.evolved(
                    state=LoanState.ROLLED_BACK,
                    settled_at=now,
                    returned=returned,
                    bad_debt=loan.amount - returned,
                )
                if returned:
                    session.state.quota_limits[loan.borrower_id] = remaining - returned
                    session.record(
                        "quota.adjust",
                        {
                            "flight_id": loan.borrower_id,
                            "delta": -returned,
                            "reason": "loan_rollback",
                            "loan_id": loan.id,
                        },
                        now,
                    )
                    session.state.quota_limits[loan.lender_id] = (
                        session.state.quota_limits.get(loan.lender_id, 0) + returned
                    )
                    session.record(
                        "quota.adjust",
                        {
                            "flight_id": loan.lender_id,
                            "delta": returned,
                            "reason": "loan_rollback",
                            "loan_id": loan.id,
                        },
                        now,
                    )
                session.state.quota_loans[loan.id] = done
                session.record("quota.rollback", {"loan": done.as_dict()}, now)
                settled.append(done)
        return settled

    # -- queries -----------------------------------------------------------

    def get(self, loan_id: str) -> QuotaLoan:
        loan = self._store.state().quota_loans.get(loan_id)
        if loan is None:
            raise NotFoundError(f"quota loan {loan_id!r} is not registered")
        return loan

    def history(self, flight_id: str = "", state: str = "") -> list[QuotaLoan]:
        """Every loan on record, oldest first, optionally filtered."""

        loans = [
            self._store.state().quota_loans[key]
            for key in sorted(self._store.state().quota_loans)
        ]
        if flight_id:
            loans = [
                loan
                for loan in loans
                if loan.lender_id == flight_id or loan.borrower_id == flight_id
            ]
        if state:
            loans = [loan for loan in loans if loan.state.value == state]
        return loans

    def overdue(self, at: str = "") -> list[QuotaLoan]:
        """Open loans whose due time has passed."""

        moment = at or self._clock.now_iso()
        return [
            loan
            for loan in self.history(state=LoanState.OPEN.value)
            if loan.due_at < moment
        ]

    def positions(self, flight_id: str) -> dict[str, object]:
        """One flight's loan position, for reconciling with the allowance ledger."""

        loans = self.history(flight_id=flight_id)
        return {
            "flight_id": flight_id,
            "lent_out": sum(
                loan.amount
                for loan in loans
                if loan.lender_id == flight_id and loan.state is LoanState.OPEN
            ),
            "borrowed_in": sum(
                loan.amount
                for loan in loans
                if loan.borrower_id == flight_id and loan.state is LoanState.OPEN
            ),
            "bad_debt": sum(
                loan.bad_debt for loan in loans if loan.lender_id == flight_id
            ),
        }
