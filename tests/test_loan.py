"""Temporary allowance lending between flights."""

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
from bagsort.store.replay import replay
from bagsort.store.store import Store
from tests.support import check_in, make_server, register_flight

DUE = "2024-01-01T12:00:00Z"


@pytest.fixture()
def pair(plant):
    lender = register_flight(plant, code="CA1001")
    borrower = register_flight(plant, code="CA1002")
    plant.quota.set_limit(lender.id, 5)
    plant.quota.set_limit(borrower.id, 2)
    return lender, borrower


def test_lend_moves_allowance_into_the_borrowers_limit(plant, pair):
    lender, borrower = pair
    loan = plant.lend_quota(lender.id, borrower.id, 3, DUE)
    assert loan.id == "loan-000001"
    assert loan.state is LoanState.OPEN
    assert loan.amount == 3 and loan.due_at == DUE
    assert plant.quota.available(lender.id) == 2
    assert plant.quota.available(borrower.id) == 5
    assert plant.loans.positions(lender.id) == {
        "flight_id": lender.id,
        "lent_out": 3,
        "borrowed_in": 0,
        "bad_debt": 0,
    }
    assert plant.loans.positions(borrower.id)["borrowed_in"] == 3


def test_lend_lands_in_the_journal_and_the_audit_chain(plant, pair):
    lender, borrower = pair
    loan = plant.lend_quota(lender.id, borrower.id, 3, DUE)
    kinds = plant.store.kinds()
    assert kinds["quota.lend"] == 1
    adjusts = [
        entry
        for entry in plant.store.entries()
        if entry.kind == "quota.adjust" and entry.payload.get("loan_id") == loan.id
    ]
    assert [(entry.payload["flight_id"], entry.payload["delta"]) for entry in adjusts] == [
        (lender.id, -3),
        (borrower.id, 3),
    ]
    entries = plant.audit.for_subject(loan.id)
    assert [entry.kind for entry in entries] == ["quota_lend"]
    assert entries[0].detail["amount"] == 3
    assert entries[0].detail["due_at"] == DUE
    assert plant.audit.verify() is True


def test_lend_rejects_invalid_requests(plant, pair):
    lender, borrower = pair
    with pytest.raises(ValidationError):
        plant.lend_quota(lender.id, lender.id, 1, DUE)
    with pytest.raises(ValidationError):
        plant.lend_quota(lender.id, borrower.id, 0, DUE)
    with pytest.raises(ValidationError):
        plant.lend_quota(lender.id, borrower.id, -2, DUE)
    with pytest.raises(ValidationError):
        plant.lend_quota(lender.id, borrower.id, 1, "  ")
    with pytest.raises(NotFoundError):
        plant.lend_quota(lender.id, "T1-GHOST", 1, DUE)
    with pytest.raises(QuotaError):
        plant.lend_quota(lender.id, borrower.id, 6, DUE)


def test_lend_requires_configured_allowances_on_both_sides(plant, pair):
    lender, borrower = pair
    unlimited = register_flight(plant, code="CA1003")
    with pytest.raises(ValidationError):
        plant.lend_quota(lender.id, unlimited.id, 1, DUE)
    with pytest.raises(ValidationError):
        plant.lend_quota(unlimited.id, borrower.id, 1, DUE)


def test_lend_requires_open_flights(plant, pair):
    lender, borrower = pair
    plant.close_flight(borrower.id)
    with pytest.raises(OrderingError):
        plant.lend_quota(lender.id, borrower.id, 1, DUE)


def test_borrowed_allowance_is_spendable_and_lent_allowance_is_not(plant):
    lender = register_flight(plant, code="CA2001")
    borrower = register_flight(plant, code="CA2002")
    plant.quota.set_limit(lender.id, 2)
    plant.quota.set_limit(borrower.id, 1)
    check_in(plant, borrower.id, 1)
    with pytest.raises(QuotaError):
        plant.check_in("BAG9000", borrower.id)
    plant.lend_quota(lender.id, borrower.id, 2, DUE)
    check_in(plant, borrower.id, 2, prefix="BAG8")
    with pytest.raises(QuotaError):
        plant.check_in("BAG9001", lender.id)


def test_repay_moves_the_allowance_back(plant, pair):
    lender, borrower = pair
    loan = plant.lend_quota(lender.id, borrower.id, 3, DUE)
    settled = plant.repay_quota(loan.id)
    assert settled.state is LoanState.REPAID
    assert settled.returned == 3 and settled.bad_debt == 0
    assert settled.settled_at
    assert plant.quota.available(lender.id) == 5
    assert plant.quota.available(borrower.id) == 2
    entries = plant.audit.for_subject(loan.id)
    assert [entry.kind for entry in entries] == ["quota_lend", "quota_repay"]
    assert plant.audit.verify() is True


def test_the_same_loan_cannot_be_repaid_twice(plant, pair):
    lender, borrower = pair
    loan = plant.lend_quota(lender.id, borrower.id, 3, DUE)
    plant.repay_quota(loan.id)
    with pytest.raises(ConflictError):
        plant.repay_quota(loan.id)
    assert plant.quota.available(lender.id) == 5
    assert plant.quota.available(borrower.id) == 2


def test_repay_fails_when_the_borrower_already_spent_the_allowance(plant, pair):
    lender, borrower = pair
    loan = plant.lend_quota(lender.id, borrower.id, 3, DUE)
    assert plant.quota.consume(borrower.id, 4) is True
    with pytest.raises(QuotaError):
        plant.repay_quota(loan.id)
    assert plant.loans.get(loan.id).state is LoanState.OPEN


def test_overdue_lists_open_loans_whose_due_time_passed(plant, pair):
    lender, borrower = pair
    loan = plant.lend_quota(lender.id, borrower.id, 1, DUE)
    assert plant.loans.overdue() == []
    plant.clock.advance(13 * 3600)
    assert [item.id for item in plant.loans.overdue()] == [loan.id]
    plant.repay_quota(loan.id)
    assert plant.loans.overdue() == []


def test_closing_the_borrower_rolls_back_and_the_lender_takes_the_bad_debt(plant):
    lender = register_flight(plant, code="CA3001")
    borrower = register_flight(plant, code="CA3002")
    plant.quota.set_limit(lender.id, 5)
    plant.quota.set_limit(borrower.id, 1)
    loan = plant.lend_quota(lender.id, borrower.id, 3, DUE)
    assert plant.quota.consume(borrower.id, 3) is True

    plant.close_flight(borrower.id)

    settled = plant.loans.get(loan.id)
    assert settled.state is LoanState.ROLLED_BACK
    assert settled.returned == 1
    assert settled.bad_debt == 2
    # Both allowance ledgers still reconcile: 5 - 3 lent + 1 returned = 3.
    assert plant.quota.available(lender.id) == 3
    assert plant.quota.available(borrower.id) == 0
    assert plant.loans.positions(lender.id)["bad_debt"] == 2
    entries = plant.audit.for_subject(loan.id)
    assert [entry.kind for entry in entries] == ["quota_lend", "quota_rollback"]
    assert entries[-1].detail["bad_debt"] == 2
    assert plant.audit.verify() is True
    assert replay(plant.store.entries()).as_dict() == plant.store.state().as_dict()


def test_closing_the_lender_rolls_back_as_well(plant, pair):
    lender, borrower = pair
    loan = plant.lend_quota(lender.id, borrower.id, 2, DUE)
    plant.close_flight(lender.id)
    settled = plant.loans.get(loan.id)
    assert settled.state is LoanState.ROLLED_BACK
    assert settled.returned == 2 and settled.bad_debt == 0
    assert plant.quota.available(lender.id) == 5
    assert plant.quota.available(borrower.id) == 2


def test_rollback_is_idempotent_and_a_rolled_back_loan_cannot_be_repaid(plant, pair):
    lender, borrower = pair
    loan = plant.lend_quota(lender.id, borrower.id, 2, DUE)
    plant.close_flight(borrower.id)
    assert plant.loans.rollback_for_flight(borrower.id) == []
    with pytest.raises(ConflictError):
        plant.repay_quota(loan.id)
    assert plant.quota.available(lender.id) == 5
    assert plant.quota.available(borrower.id) == 2


def test_loans_survive_a_restart(plant, pair):
    lender, borrower = pair
    first = plant.lend_quota(lender.id, borrower.id, 2, DUE)
    plant.repay_quota(first.id)
    second = plant.lend_quota(lender.id, borrower.id, 1, DUE)
    plant.store.persist()
    reopened = Store.open(plant.store.path)
    state = reopened.state()
    assert state.quota_loans[first.id].state is LoanState.REPAID
    assert state.quota_loans[second.id].state is LoanState.OPEN
    assert state.quota_limits == plant.store.state().quota_limits
    assert replay(reopened.entries()).as_dict() == state.as_dict()


def test_history_is_reviewable_per_flight_and_per_loan(plant, pair):
    lender, borrower = pair
    first = plant.lend_quota(lender.id, borrower.id, 1, DUE)
    second = plant.lend_quota(lender.id, borrower.id, 2, DUE)
    plant.repay_quota(first.id)
    assert [loan.id for loan in plant.loans.history()] == [first.id, second.id]
    assert [loan.id for loan in plant.loans.history(flight_id=borrower.id)] == [
        first.id,
        second.id,
    ]
    assert [loan.id for loan in plant.loans.history(state="open")] == [second.id]
    assert plant.loans.get(second.id).amount == 2
    with pytest.raises(NotFoundError):
        plant.loans.get("loan-999999")


def test_console_loan_endpoints(tmp_path):
    server = make_server(tmp_path)

    def call(method, path, payload=None, query=None):
        response = server.call(method, path, payload, query)
        return response.status, json.loads(response.body)

    def limited_flight(code, limit):
        status, body = call("POST", "/api/flights", {"code": code})
        assert status == 201
        call("POST", "/api/quota", {"flight_id": body["id"], "limit": limit})
        return body["id"]

    lender = limited_flight("CA4001", 5)
    borrower = limited_flight("CA4002", 1)

    status, loan = call(
        "POST",
        "/api/quota/lend",
        {"lender_id": lender, "borrower_id": borrower, "amount": 3, "due_at": DUE},
    )
    assert status == 201
    assert loan["state"] == "open" and loan["amount"] == 3

    status, rows = call("GET", "/api/quota/loans")
    assert [row["id"] for row in rows] == [loan["id"]]
    status, rows = call("GET", "/api/quota/loans", query={"state": ["repaid"]})
    assert rows == []
    status, rows = call("GET", "/api/quota/loans", query={"overdue": ["true"]})
    assert rows == []
    assert call("GET", f"/api/quota/loans/{loan['id']}")[1]["borrower_id"] == borrower
    assert call("GET", "/api/quota/loans/loan-999999")[0] == 404

    status, position = call("GET", f"/api/quota/{lender}")
    assert position["available"] == 2
    assert position["loans"]["lent_out"] == 3

    status, settled = call("POST", "/api/quota/repay", {"loan_id": loan["id"]})
    assert settled["state"] == "repaid" and settled["returned"] == 3
    assert call("POST", "/api/quota/repay", {"loan_id": loan["id"]})[0] == 409
    assert call("GET", "/api/quota/loans", query={"state": ["repaid"]})[1][0]["id"] == loan["id"]

    status, audit = call("GET", f"/api/audit/bag/{loan['id']}")
    assert [entry["kind"] for entry in audit] == ["quota_lend", "quota_repay"]
    assert call("GET", "/api/audit/verify")[1]["intact"] is True

    assert call("POST", "/api/quota/lend", {"lender_id": lender, "borrower_id": borrower, "amount": 0, "due_at": DUE})[0] == 400
    assert call("POST", "/api/quota/lend", {"lender_id": lender, "borrower_id": borrower, "amount": 1, "due_at": ""})[0] == 400
    assert call("POST", "/api/quota/lend", {"lender_id": lender, "borrower_id": borrower, "amount": 99, "due_at": DUE})[0] == 409
