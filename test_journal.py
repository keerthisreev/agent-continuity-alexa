"""Tests for the SQLite operation journal and the lost-ack scenario.

Covers: intent/commit/reconcile lifecycle, the REUSE path (same key +
same payload -> existing receipt, no duplicate effect), the CONFLICT path
(same key + different payload -> IdempotencyConflict, never silent reuse),
crash recovery (close/reopen -> reconcile returns the committed receipt),
baseline-vs-protected (naive retry double-books; journal discipline books
once), and the recovery receipt (every field from real records).
Deterministic, no randomness, no network.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from continuity.journal import (IdempotencyConflict, OperationJournal,
                                _fingerprint)
from sim.lost_ack import (SimulatedProvider, run_baseline_lost_ack,
                          run_protected_lost_ack)
from sim.receipt import NOT_RECORDED, receipt_from_lost_ack, render_text_lines


def _tmp_journal() -> OperationJournal:
    fd, path = tempfile.mkstemp(prefix="test-journal-", suffix=".db")
    os.close(fd)
    return OperationJournal(path)


def test_fingerprint_canonical():
    a = _fingerprint({"b": 1, "a": 2})
    b = _fingerprint({"a": 2, "b": 1})
    c = _fingerprint({"a": 2, "b": 3})
    assert a == b, "key order must not change the fingerprint"
    assert a != c, "different payload must fingerprint differently"
    print("PASS journal: canonical payload fingerprint")


def test_intent_commit_lifecycle():
    j = _tmp_journal()
    try:
        rec = j.record_intent("op-1", "key-1", {"ride": "AUS"})
        assert rec["status"] == "pending", rec
        rec = j.record_commit("op-1", {"booking_id": "RIDE-1"})
        assert rec["status"] == "committed", rec
        assert rec["receipt"] == {"booking_id": "RIDE-1"}, rec
    finally:
        j.close()
    print("PASS journal: intent -> commit lifecycle")


def test_retry_same_key_same_payload_reuses_receipt():
    """(a) The lost-ack core: retry of the same logical op reuses the
    committed receipt; the provider is never hit twice."""
    j = _tmp_journal()
    provider = SimulatedProvider()
    try:
        op, key = "op-ride", "ride-key"
        params = {"pickup": "home", "dropoff": "AUS"}
        j.record_intent(op, key, params)
        receipt, created = provider.execute("reserve", key, params)
        assert created is True
        j.record_commit(op, receipt)
        # SIMULATED: the acknowledgement is lost.
        j.mark_unknown(op)
        # The agent retries the SAME logical op: journal first.
        again = j.record_intent(op, key, params)
        assert again["status"] == "unknown", again
        assert again["receipt"] == receipt, "existing receipt must be returned"
        final = j.reconcile(op)
        assert final["status"] == "reconciled", final
        assert final["receipt"] == receipt, final
        assert final["recovery_decision"] == \
            "reconciled_ambiguous_commit__receipt_reused"
        # No second provider call happened on the retry path:
        assert provider.calls == 1, provider.calls
        assert len(provider.created_receipts) == 1
    finally:
        j.close()
    print("PASS journal: same key+payload retry reuses receipt, single effect")


def test_same_key_different_payload_is_conflict():
    """(b) Same key, different payload: loud conflict, original untouched."""
    j = _tmp_journal()
    try:
        j.record_intent("op-1", "key-1", {"ride": "AUS"})
        j.record_commit("op-1", {"booking_id": "RIDE-1"})
        try:
            j.record_intent("op-1", "key-1", {"ride": "DFW"})
        except IdempotencyConflict as exc:
            assert exc.idempotency_key == "key-1"
        else:
            raise AssertionError("expected IdempotencyConflict")
        rec = j.get("op-1")
        assert rec["status"] == "committed", rec
        assert rec["receipt"] == {"booking_id": "RIDE-1"}, rec
        assert rec["payload_fingerprint"] == _fingerprint({"ride": "AUS"})
    finally:
        j.close()
    print("PASS journal: same key + different payload -> conflict, never silent")


def test_crash_recovery_close_reopen():
    """(c) Simulated process restart: records survive close/reopen and
    reconcile returns the committed receipt."""
    fd, path = tempfile.mkstemp(prefix="test-crash-", suffix=".db")
    os.close(fd)
    j = OperationJournal(path)
    receipt = {"booking_id": "RIDE-7", "status": "confirmed"}
    j.record_intent("op-x", "key-x", {"ride": "AUS"})
    j.record_commit("op-x", receipt)
    j.close()
    # "Restart": a brand-new connection to the same file.
    j2 = OperationJournal(path)
    try:
        rec = j2.reconcile("op-x")
        assert rec["status"] == "reconciled", rec
        assert rec["receipt"] == receipt, rec
        assert rec["recovery_decision"] == "reuse_committed_receipt", rec
    finally:
        j2.close()
        os.unlink(path)
    print("PASS journal: state survives close/reopen (crash recovery)")


def test_reconcile_without_receipt_orders_provider_check():
    j = _tmp_journal()
    try:
        j.record_intent("op-n", "key-n", {"x": 1})
        j.mark_unknown("op-n")  # ack lost before any commit was recorded
        rec = j.reconcile("op-n")
        assert rec["receipt"] is None, rec
        assert rec["recovery_decision"] == \
            "no_recorded_effect__verify_provider_before_retry", rec
    finally:
        j.close()
    print("PASS journal: unknown with no receipt -> verify provider, never blind retry")


def test_baseline_double_applies_protected_single():
    """(d) End-to-end: naive retry books twice; journal discipline books once."""
    baseline = run_baseline_lost_ack("INC-J1")
    protected = run_protected_lost_ack("INC-J2")
    try:
        assert baseline["ride_bookings"] == 2, baseline
        assert baseline["duplicate_effects"] == 1, baseline
        assert protected["ride_bookings"] == 1, protected
        assert protected["provider_calls"] == 3, protected  # no 2nd ride call
        reused = [s for s in protected["steps"] if s.get("reused")]
        assert len(reused) == 1, protected["steps"]
        assert reused[0]["receipt"] == reused[0]["receipt"]
        # The journal agrees with the provider: one effect, receipt on file.
        rec = protected["journal"].get(reused[0]["op_id"])
        assert rec["status"] == "reconciled", rec
        assert rec["receipt"] == reused[0]["receipt"], rec
    finally:
        protected["journal"].close()
    print("PASS scenario: baseline double-books, protected books exactly once")


def test_store_backstop_refuses_duplicate_key():
    """Belt and suspenders: even if the agent ignored the journal, the
    store's idempotent apply refuses the same action id twice."""
    protected = run_protected_lost_ack("INC-J3")
    try:
        store, layer = protected["store"], protected["layer"]
        first = protected["steps"][0]
        action = {"kind": "reserve", "target": "airport-pickup", "params": {}}
        again = store.apply_effect(
            "sim-user-task", "remediation",
            protected["fencing_generation"], first["key"], action,
            tick=layer.clock.now())
        assert again is False, "store must refuse the duplicate action id"
    finally:
        protected["journal"].close()
    print("PASS store: duplicate action id refused even past the journal")


def test_receipt_fields_come_from_records():
    protected = run_protected_lost_ack("INC-J4")
    try:
        receipt = receipt_from_lost_ack(protected)
        assert receipt["incident_id"] == "INC-J4"
        assert len(receipt["operations"]) == 3, receipt["operations"]
        by_label = {o["label"]: o for o in receipt["operations"]}
        ride = by_label["Reserve airport pickup"]
        assert ride["retry_decision"] == "reused", ride
        assert ride["effect_receipt"]["effect_id"].startswith("RESERVE-"), ride
        assert ride["effect_receipt"] == \
            protected["journal"].get(
                protected["steps"][0]["op_id"])["receipt"]
        cal = by_label["Add pickup to shared calendar"]
        assert cal["retry_decision"] == \
            "committed first try (no retry needed)", cal
        # Global fields are derived, not hard-coded.
        assert receipt["checkpoint"] != NOT_RECORDED
        assert receipt["fencing"]["stale_writes_rejected"] == 0
        assert receipt["fencing"]["current_generations"]["remediation"] == \
            protected["fencing_generation"]
        assert receipt["final_state"]["disposition"] == "completed clean", \
            receipt["final_state"]
        lines = render_text_lines(receipt)
        assert any("Reserve airport pickup" in ln for ln in lines)
        assert any("reused" in ln for ln in lines)
    finally:
        protected["journal"].close()
    print("PASS receipt: every field read off journal/ledger/store")


def test_journal_stays_offline_with_key_set():
    old = os.environ.get("NEBIUS_API_KEY")
    old_live = os.environ.get("CONTINUITY_LIVE")
    os.environ["NEBIUS_API_KEY"] = "test-only-fake-key"
    os.environ.pop("CONTINUITY_LIVE", None)
    try:
        protected = run_protected_lost_ack("INC-J5")
        try:
            assert protected["layer"].live is False
            assert protected["ride_bookings"] == 1
        finally:
            protected["journal"].close()
    finally:
        if old is None:
            os.environ.pop("NEBIUS_API_KEY", None)
        else:
            os.environ["NEBIUS_API_KEY"] = old
        if old_live is not None:
            os.environ["CONTINUITY_LIVE"] = old_live
    print("PASS offline: key in env cannot flip the journal scenario online")


def test_no_banned_language_in_new_files():
    # Built dynamically so this file's own source doesn't contain the term.
    banned = "2" + "0k"
    new_files = ["continuity/journal.py", "sim/lost_ack.py",
                 "sim/receipt.py", "sim/ablation.py", "test_journal.py",
                 "dashboard/app.py", "sim/alexa_plus_sim.py"]
    root = os.path.dirname(os.path.abspath(__file__))
    for rel in new_files:
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            text = fh.read().lower()
        if rel == "test_journal.py":
            # This test's own references to the banned term don't count.
            text = text.replace(banned, "")
        assert banned not in text, \
            f"{rel} contains banned language"
    print("PASS honesty: no banned language in new/changed files")


TESTS = [
    test_fingerprint_canonical,
    test_intent_commit_lifecycle,
    test_retry_same_key_same_payload_reuses_receipt,
    test_same_key_different_payload_is_conflict,
    test_crash_recovery_close_reopen,
    test_reconcile_without_receipt_orders_provider_check,
    test_baseline_double_applies_protected_single,
    test_store_backstop_refuses_duplicate_key,
    test_receipt_fields_come_from_records,
    test_journal_stays_offline_with_key_set,
    test_no_banned_language_in_new_files,
]


def main() -> int:
    failed = 0
    for test in TESTS:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} journal tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
