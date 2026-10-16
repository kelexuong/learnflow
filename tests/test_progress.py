from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lf_common import LearnFlowError, workspace_path
from lf_progress import due_reviews, load_progress, save_progress


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="learnflow-progress-test-")
        self.workspace = workspace_path(Path(self.temp.name) / "study")

    def tearDown(self):
        self.temp.cleanup()

    def evidence(self, identity="E1", **extra):
        return {"id": identity, "task_id": "task-" + identity, "learner_answer": "用户实际给出的解释。", "support": "independent", **extra}

    def test_record_only_preserves_next_entry_and_does_not_end(self):
        first = save_progress(self.workspace, "logic", {"unit_status": "进行中", "next_step": "继续当前题", "reading": {"chapter": "第一章", "page": 2}})
        snapshot = save_progress(self.workspace, "logic", {"note": "记录一下"}, expected_revision=first["revision"])
        self.assertEqual(snapshot["state"]["session_status"], "进行中")
        self.assertEqual(snapshot["state"]["next_step"], "继续当前题")
        self.assertEqual(snapshot["state"]["reading"]["page"], 2)
        self.assertFalse(snapshot["lesson_advanced"])
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "logic", {"session_status": "已结束"})

    def test_pause_needs_no_test_and_resume_preserves_history(self):
        initial = save_progress(self.workspace, "topic", {"next_step": "尚未完成的知识点"})
        paused = save_progress(self.workspace, "topic", {}, event="pause")
        self.assertEqual(paused["state"]["session_status"], "已暂停")
        self.assertEqual(save_progress(self.workspace, "topic", {}, event="resume")["state"]["next_step"], "尚未完成的知识点")
        self.assertEqual(load_progress(self.workspace, "topic", 1)["state"], initial["state"])

    def test_reading_is_not_mastery_and_levels_remain_l0_to_l6(self):
        state = save_progress(self.workspace, "book", {"reading": {"status": "已读"}})["state"]
        self.assertEqual(state["mastery"], {})
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "book", {"mastery": {"concept": {"level": "L7"}}})
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "book", {"mastery": {"concept": {"level": "L3", "status": "已验证"}}})

    def test_exposed_answer_cannot_be_independent_evidence(self):
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "logic", {"evidence": [self.evidence(answer_exposed=True)]})
        saved = save_progress(self.workspace, "logic", {"evidence": [self.evidence(support="answer_seen", answer_exposed=True)]})
        self.assertEqual(saved["state"]["mastery"], {})

    def test_l5_requires_delayed_evidence_and_original_answers_stay_immutable(self):
        evidence = [self.evidence("E1"), self.evidence("E2")]
        mastery = {"concept": {"level": "L5", "status": "已验证", "evidence_ids": ["E1", "E2"]}}
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "logic", {"evidence": evidence, "mastery": mastery})
        evidence[1]["delayed"] = True
        saved = save_progress(self.workspace, "logic", {"evidence": evidence, "mastery": mastery})
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "logic", {"evidence": [self.evidence("E1", learner_answer="改写的答案")]})
        self.assertEqual(load_progress(self.workspace, "logic")["state"], saved["state"])

    def test_stale_revision_and_uncreated_reminder_are_rejected(self):
        first = save_progress(self.workspace, "logic", {})
        save_progress(self.workspace, "logic", {"note": "新记录"})
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "logic", {"note": "过期记录"}, expected_revision=first["revision"])
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "logic", {"review": [{"reminder_created": True}]})

    def test_review_observes_explicit_agreement_without_advancing(self):
        save_progress(self.workspace, "logic", {"review": [
            {"concept": "A", "suggested_on": "2026-10-15", "agreed_on": "2026-10-18"},
            {"concept": "B", "suggested_on": "2026-10-15"}]})
        result = due_reviews(self.workspace, "logic", "2026-10-16")
        self.assertEqual([r["concept"] for r in result["items"]], ["B"])
        self.assertFalse(result["reminder_created"])
        self.assertFalse(result["reading_progress_changed"])
