"""Temporary allowance loans between flights.

Covers the loan lifecycle: borrow, repay, close-time rollback, bad debt
ownership, double-repayment protection, restart persistence and the
cross-check between the loan book, the journal, the audit chain and flights.
"""

from __future__ import annotations

import json

import pytest

from bagsort.errors import (
    ConflictError,
    NotFoundError,
    OrderingError,
    QuotaError,
    ValidationError,
)
from bagsort.model.enums import LoanState
from bagsort.store.store import Store
from tests.support import check_in, register_flight


@pytest.fixture()
def lender(plant):
    return register_flight(plant, code="CA1111")


@pytest.fixture()
def borrower(plant):
    return register_flight(plant, code="CA9999")


@pytest.fixture()
def funded(plant, lender, borrower):
    plant.quota.set_limit(lender.id, 10)
    plant.quota.set_limit(borrower.id, 2)
    return lender, borrower


def journal_entries(plant, kind, loan_id=None):
    entries = [
        entry for entry in plant.store.journal.committed() if entry.kind == kind
    ]
    if loan_id is None:
        return entries
    return [
        entry
        for entry in entries
        if entry.payload.get("loan_id") == loan_id
        or entry.payload.get("loan", {}).get("id") == loan_id
    ]


def test_lend_moves_allowance_and_journals_every_leg(plant, funded):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5, due_at="2026-10-07T12:00:00")

    assert loan.id == "LOAN-000001"
    assert loan.state is LoanState.OPEN
    assert loan.amount == 5
    assert loan.outstanding == 5
    assert loan.due_at == "2026-10-07T12:00:00"
    assert loan.borrowed_at != ""
    # The borrowed allowance merges into the borrower's own limit.
    assert plant.quota.limit(lender.id) == 5
    assert plant.quota.limit(borrower.id) == 7

    kinds = [entry.kind for entry in journal_entries(plant, "quota.loan_open", loan.id)]
    assert kinds == ["quota.loan_open"]
    adjusts = journal_entries(plant, "quota.adjust")
    assert [(e.payload["flight_id"], e.payload["delta"]) for e in adjusts] == [
        (lender.id, -5),
        (borrower.id, 5),
    ]
    assert plant.verify_quota() == []


def test_borrowed_allowance_is_spendable_at_the_desk(plant, funded):
    lender, borrower = funded
    plant.lend_quota(lender.id, borrower.id, 3)
    check_in(plant, borrower.id, 5)  # 2 own + 3 borrowed
    assert plant.quota.limit(borrower.id) == 0
    assert plant.quota.allowed(borrower.id) is False
    with pytest.raises(QuotaError):
        plant.check_in("BAG9999", borrower.id)


def test_lend_validates_inputs(plant, funded):
    lender, borrower = funded
    with pytest.raises(ValidationError):
        plant.quota.lend(lender.id, lender.id, 1)
    with pytest.raises(ValidationError):
        plant.quota.lend(lender.id, borrower.id, 0)
    with pytest.raises(ValidationError):
        plant.quota.lend(lender.id, borrower.id, -3)
    with pytest.raises(ValidationError):
        plant.quota.lend("", borrower.id, 1)
    with pytest.raises(QuotaError):
        plant.quota.lend("T1-UNLIMITED", borrower.id, 1)
    with pytest.raises(QuotaError):
        plant.quota.lend(lender.id, "T1-UNLIMITED", 1)
    with pytest.raises(QuotaError):
        plant.quota.lend(lender.id, borrower.id, 11)


def test_lend_requires_both_flights_open(plant, funded):
    lender, borrower = funded
    plant.close_flight(borrower.id)
    with pytest.raises(OrderingError):
        plant.lend_quota(lender.id, borrower.id, 1)
    with pytest.raises(NotFoundError):
        plant.lend_quota(lender.id, "T1-GONE", 1)


def test_repay_returns_allowance_and_settles(plant, funded):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5)

    partial = plant.repay_quota(loan.id, 2)
    assert partial.state is LoanState.OPEN
    assert (partial.repaid, partial.outstanding) == (2, 3)
    assert plant.quota.limit(lender.id) == 7
    assert plant.quota.limit(borrower.id) == 5

    settled = plant.repay_quota(loan.id)  # defaults to the full balance
    assert settled.state is LoanState.SETTLED
    assert settled.outstanding == 0
    assert settled.settled_at != ""
    assert plant.quota.limit(lender.id) == 10
    assert plant.quota.limit(borrower.id) == 2
    assert plant.verify_quota() == []


def test_the_same_loan_cannot_be_repaid_twice(plant, funded):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5)
    plant.repay_quota(loan.id)
    with pytest.raises(ConflictError):
        plant.repay_quota(loan.id)
    with pytest.raises(ConflictError):
        plant.repay_quota(loan.id, 1)
    # The book is untouched by the rejected attempts.
    assert plant.quota.loan(loan.id).repaid == 5
    assert plant.quota.limit(lender.id) == 10


def test_repay_never_exceeds_the_outstanding_balance(plant, funded):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5)
    with pytest.raises(ValidationError):
        plant.repay_quota(loan.id, 6)
    plant.repay_quota(loan.id, 4)
    with pytest.raises(ValidationError):
        plant.repay_quota(loan.id, 2)
    with pytest.raises(NotFoundError):
        plant.repay_quota("LOAN-999999")


def test_repay_is_capped_by_what_the_borrower_can_cover(plant, funded):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5)
    assert plant.quota.consume(borrower.id, 6) is True  # borrower down to 1

    repaid = plant.repay_quota(loan.id)  # asks for 5, only 1 is coverable
    assert (repaid.repaid, repaid.outstanding) == (1, 4)
    assert plant.quota.limit(borrower.id) == 0
    assert plant.quota.limit(lender.id) == 6

    # The shortfall is on record: requested 5, applied 1.
    (entry,) = journal_entries(plant, "quota.loan_repay", loan.id)
    assert (entry.payload["requested"], entry.payload["count"]) == (5, 1)

    # Nothing left to repay with: the attempt fails loudly, debt stays booked.
    with pytest.raises(QuotaError):
        plant.repay_quota(loan.id)
    assert plant.quota.loan(loan.id).outstanding == 4


def test_close_rolls_back_unreturned_loans_and_the_lender_takes_the_loss(
    plant, funded
):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5)
    check_in(plant, borrower.id, 6)  # borrower spent down to 1 of 7

    plant.close_flight(borrower.id)

    rolled = plant.quota.loan(loan.id)
    assert rolled.state is LoanState.ROLLED_BACK
    assert rolled.settled_at != ""
    # Only the bag the borrower could still cover comes back; the rest is
    # bad debt borne by the lender.
    assert (rolled.repaid, rolled.written_off, rolled.outstanding) == (1, 4, 0)
    assert plant.quota.limit(borrower.id) == 0
    assert plant.quota.limit(lender.id) == 6

    (entry,) = journal_entries(plant, "quota.loan_rollback", loan.id)
    assert (entry.payload["returned"], entry.payload["written_off"]) == (1, 4)
    assert plant.verify_quota() == []


def test_closing_the_lender_recalls_the_loan_from_the_borrower(plant, funded):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5)

    plant.close_flight(lender.id)

    rolled = plant.quota.loan(loan.id)
    assert rolled.state is LoanState.ROLLED_BACK
    assert (rolled.repaid, rolled.written_off) == (5, 0)
    assert plant.quota.limit(lender.id) == 10
    assert plant.quota.limit(borrower.id) == 2
    assert plant.quota.allowed(borrower.id) is True
    assert plant.verify_quota() == []


def test_rollback_is_idempotent(plant, funded):
    lender, borrower = funded
    plant.lend_quota(lender.id, borrower.id, 5)

    plant.close_flight(borrower.id)
    after_close = plant.store.watermark
    assert plant.quota.rollback_for_flight(borrower.id) == []
    assert plant.store.watermark == after_close


def test_loans_survive_a_restart(plant, funded):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5, due_at="2026-10-07T12:00:00")
    plant.repay_quota(loan.id, 2)
    plant.store.persist()

    reopened = Store.open(plant.store.path)
    restored = reopened.state().quota_loans[loan.id]
    assert restored.as_dict() == plant.quota.loan(loan.id).as_dict()
    assert reopened.state().quota_limits[lender.id] == 7
    assert reopened.state().quota_limits[borrower.id] == 5


def test_loan_history_is_reviewable_entry_by_entry(plant, funded):
    lender, borrower = funded
    first = plant.lend_quota(lender.id, borrower.id, 3)
    second = plant.lend_quota(lender.id, borrower.id, 2)
    plant.repay_quota(first.id, 1)

    loans = plant.quota.loans()
    assert [loan.id for loan in loans] == [first.id, second.id]
    assert plant.quota.loans(borrower.id) == loans
    assert plant.quota.loans("T1-UNINVOLVED") == []
    assert plant.quota.loan(first.id).repaid == 1
    assert plant.quota.open_loans() == loans
    assert plant.quota.outstanding() == 4
    assert plant.quota.outstanding(borrower.id) == 4

    # Every movement of one loan is individually inspectable in the journal.
    assert len(journal_entries(plant, "quota.loan_open", first.id)) == 1
    assert len(journal_entries(plant, "quota.loan_repay", first.id)) == 1
    assert journal_entries(plant, "quota.loan_repay", second.id) == []


def test_audit_trail_mirrors_the_loan_book(plant, funded):
    lender, borrower = funded
    loan = plant.lend_quota(lender.id, borrower.id, 5)
    plant.repay_quota(loan.id, 2)
    plant.close_flight(borrower.id)

    kinds = plant.audit.by_kind()
    assert kinds["quota_loan"] == 1
    assert kinds["quota_repay"] == 1
    assert kinds["quota_loan_rollback"] == 1
    subjects = [entry.subject for entry in plant.audit.entries()]
    assert subjects.count(loan.id) == 3
    assert plant.verify() is True
    assert plant.verify_quota() == []


def test_verify_quota_flags_a_closed_flight_with_an_open_loan(plant, funded):
    lender, borrower = funded
    loan = plant.quota.lend(lender.id, borrower.id, 5)
    # Close through the closer directly, skipping the plant's rollback step.
    plant.closer.close(borrower.id, plant.injector)

    problems = plant.verify_quota()
    assert any(loan.id in problem and "closed" in problem for problem in problems)


def test_console_loan_endpoints(server):
    def call(method, path, payload=None, query=None):
        response = server.call(method, path, payload, query)
        return response.status, json.loads(response.body)

    for code in ("CA1111", "CA9999"):
        status, _ = call("POST", "/api/flights", {"code": code})
        assert status == 201
    assert call("POST", "/api/quota", {"flight_id": "T1-CA1111", "limit": 10})[0] == 200
    assert call("POST", "/api/quota", {"flight_id": "T1-CA9999", "limit": 2})[0] == 200

    status, loan = call(
        "POST",
        "/api/quota/lend",
        {"lender": "T1-CA1111", "borrower": "T1-CA9999", "amount": 4},
    )
    assert status == 200
    assert loan["outstanding"] == 4 and loan["state"] == "open"

    status, rows = call("GET", "/api/quota/loans")
    assert [row["id"] for row in rows] == [loan["id"]]
    status, one = call("GET", f"/api/quota/loans/{loan['id']}")
    assert one["amount"] == 4
    status, rows = call("GET", "/api/quota/loans", query={"flight": ["T1-CA9999"]})
    assert len(rows) == 1

    status, repaid = call("POST", "/api/quota/repay", {"loan_id": loan["id"], "count": 1})
    assert (repaid["repaid"], repaid["outstanding"]) == (1, 3)

    status, verdict = call("GET", "/api/quota/loans/verify")
    assert verdict == {"consistent": True, "problems": []}

    # A literal route is not swallowed by the parameterised allowance route.
    status, allowance = call("GET", "/api/quota/T1-CA1111")
    assert allowance["limit"] == 7
