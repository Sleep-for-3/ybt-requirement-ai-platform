"""Run with unittest; this guard needs neither the app nor a database fixture."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("rag_goal_check", Path(__file__).resolve().parents[1] / "scripts/rag_goal_check.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class GoalGuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in guard.REQUIRED_FILES:
            (self.root / name).write_text("checkpoint", encoding="utf-8")
        self.goals = [{"id": goal_id, "status": "pending", "evidence": []} for goal_id in guard.POLICY]
        self.budget = dict.fromkeys(("max_new_provider_requests", "max_new_total_tokens", "provider_requests_used", "provider_requests_reserved", "total_tokens_used", "unknown_usage_requests"), 0)
        self.save()

    def save(self):
        (self.root / "GOALS.json").write_text(json.dumps({"goals": self.goals}), encoding="utf-8")
        (self.root / "BUDGET.json").write_text(json.dumps(self.budget), encoding="utf-8")

    def close(self, goal_id):
        goal = next(item for item in self.goals if item["id"] == goal_id)
        evidence = self.root / "result.txt"
        evidence.write_text("isolated result", encoding="utf-8")
        result = {"passed": True, "path": evidence.name, "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
        record = {"goal_id": goal_id, "source_hash": "a" * 64, "criteria": {key: result.copy() for key in guard.POLICY[goal_id][1]}}
        closure = self.root / f"{goal_id}.json"
        closure.write_text(json.dumps(record), encoding="utf-8")
        goal.update(status="verified", closure_record=closure.name)
        self.save()
        return closure

    def test_pending_ledger_is_consistent_but_not_complete(self):
        result = guard.check(self.root)
        self.assertTrue(result["consistent"])
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["remaining"]), 18)
        self.assertFalse(guard.check(self.root, require_complete=True)["consistent"])

    def test_dropped_or_duplicate_goals_are_rejected(self):
        self.goals[-1] = self.goals[0].copy()
        self.save()
        self.assertIn("goal coverage changed", " ".join(guard.check(self.root)["errors"]))

    def test_missing_evidence_is_rejected(self):
        self.goals[0]["evidence"] = ["missing.json"]
        self.save()
        self.assertFalse(guard.check(self.root)["consistent"])

    def test_verified_without_closure_is_rejected(self):
        self.goals[0]["status"] = "verified"
        self.save()
        self.assertFalse(guard.check(self.root)["consistent"])

    def test_valid_closure_matches_candidate(self):
        self.close("G-UX-AUDIT")
        self.assertTrue(guard.check(self.root, source_hash="a" * 64)["consistent"])
        self.assertFalse(guard.check(self.root, source_hash="b" * 64)["consistent"])

    def test_changed_evidence_is_rejected(self):
        self.close("G-UX-AUDIT")
        (self.root / "result.txt").write_text("changed result", encoding="utf-8")
        self.assertIn("hash mismatch", " ".join(guard.check(self.root)["errors"]))

    def test_missing_criterion_is_rejected(self):
        path = self.close("G-UX-AUDIT")
        closure = json.loads(path.read_text(encoding="utf-8"))
        closure["criteria"].pop("current_ui")
        path.write_text(json.dumps(closure), encoding="utf-8")
        self.assertFalse(guard.check(self.root)["consistent"])

    def test_dependencies_block_premature_phase_closure(self):
        self.close("G-P1-A")
        self.assertIn("unverified dependency G-P0-B", " ".join(guard.check(self.root)["errors"]))

    def test_budget_reservations_and_noninteger_counters(self):
        for value in (1, -1, True, "1"):
            with self.subTest(value=value):
                self.budget["provider_requests_reserved"] = value
                self.save()
                self.assertFalse(guard.check(self.root)["consistent"])

    def test_final_delivery_needs_all_other_goals(self):
        self.close("G-FINAL-DELIVERY")
        self.assertEqual(sum("unverified dependency" in error for error in guard.check(self.root)["errors"]), 17)

    def test_malformed_json_and_status_are_errors(self):
        self.goals[0]["status"] = []
        self.save()
        self.assertFalse(guard.check(self.root)["consistent"])
        (self.root / "GOALS.json").write_text("not json", encoding="utf-8")
        self.assertFalse(guard.check(self.root)["consistent"])


if __name__ == "__main__":
    unittest.main()
