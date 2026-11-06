import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lf_common import LearnFlowError, database, workspace_path
from lf_progress import due_reviews, load_progress, save_progress


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="learnflow-progress-test-")
        self.workspace = workspace_path(Path(self.temp.name) / "study")

    def tearDown(self):
        self.temp.cleanup()

    def evidence(self, identity="E1", **extra):
        return {"id": identity, "task_id": "task-" + identity, "learner_answer": "用户实际给出的解释。",
                "support": "independent", "correct": True, **extra}

    def verification(self, level, *ids):
        return {"concept": {"level": level, "status": "已验证", "evidence_ids": list(ids)}}

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
        evidence[1]["correct"] = False
        with self.assertRaisesRegex(LearnFlowError, "隔时复测"):
            save_progress(self.workspace, "logic", {"evidence": evidence, "mastery": {
                "concept": {**mastery["concept"], "threshold_reason": "单个综合任务含多环节"}}})
        evidence[1]["correct"] = True
        saved = save_progress(self.workspace, "logic", {"evidence": evidence, "mastery": mastery})
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "logic", {"evidence": [self.evidence("E1", learner_answer="改写的答案")]})
        self.assertEqual(load_progress(self.workspace, "logic")["state"], saved["state"])

    def test_wrong_and_ungraded_answers_are_preserved_but_do_not_verify_mastery(self):
        wrong = self.evidence("wrong", correct=False, delayed=True)
        ungraded = self.evidence("ungraded")
        del ungraded["correct"]
        save_progress(self.workspace, "logic", {"evidence": [wrong, ungraded]})
        for level in ("L2", "L3", "L5"):
            with self.subTest(level=level), self.assertRaisesRegex(LearnFlowError, "正确作答"):
                save_progress(self.workspace, "logic", {"mastery": self.verification(level, "wrong", "ungraded")})
        state = load_progress(self.workspace, "logic")["state"]
        self.assertEqual(state["evidence"], [wrong, ungraded])
        self.assertEqual(state["mastery"], {})

    def test_l4_requires_a_successful_transfer_not_just_a_transfer_attempt(self):
        evidence = [self.evidence("A"), self.evidence("B"), self.evidence("wrong-transfer", transfer=True, correct=False)]
        save_progress(self.workspace, "logic", {"evidence": evidence})
        with self.assertRaisesRegex(LearnFlowError, "L4"):
            save_progress(self.workspace, "logic", {"mastery": self.verification("L4", "A", "B", "wrong-transfer")})
        saved = save_progress(self.workspace, "logic", {
            "evidence": [self.evidence("new", transfer=True)], "mastery": self.verification("L4", "A", "new")})
        self.assertEqual(saved["state"]["mastery"]["concept"]["level"], "L4")
        self.assertFalse(saved["mastery_warnings"])

    def test_old_unverified_grade_is_flagged_without_rewriting_history(self):
        attempt = self.evidence("old")
        del attempt["correct"]
        saved = save_progress(self.workspace, "logic", {"evidence": [attempt]})
        prior_state = saved["state"]
        prior_state["mastery"] = self.verification("L2", "old")
        # Simulate a pre-1.5.2 record, when a grade could lack an explicit outcome.
        con = database(self.workspace)
        try:
            with con:
                con.execute("UPDATE progress SET payload=? WHERE topic_id=?", (json.dumps(prior_state), "logic"))
                con.execute("UPDATE progress_history SET payload=? WHERE topic_id=? AND revision=?",
                            (json.dumps(prior_state), "logic", 1))
        finally:
            con.close()
        for revision in (None, 1):
            result = load_progress(self.workspace, "logic", revision)
            self.assertEqual(result["state"], prior_state)
            self.assertEqual(result["mastery_warnings"][0]["concept"], "concept")
        snapshot = save_progress(self.workspace, "logic", {"next_step": "继续当前题"})
        self.assertTrue(snapshot["mastery_warnings"])
        with self.assertRaises(LearnFlowError):
            save_progress(self.workspace, "logic", {"mastery": self.verification("L2", "old")})
        result = save_progress(self.workspace, "logic", {"mastery": {"concept": {"status": "待验证"}}})
        self.assertFalse(result["mastery_warnings"])
        self.assertEqual(load_progress(self.workspace, "logic", 1)["state"], prior_state)

    def test_checkpoint_resumes_exact_question_and_does_not_merge_stale_fields(self):
        checkpoint = {"concept": "平均速度", "step": 3, "question": "第 2 题：停下的时间算不算？", "task_id": "Q2"}
        first = save_progress(self.workspace, "logic", {"checkpoint": checkpoint, "next_step": "答第 2 题",
                                                        "session_status": "等待作答"})
        save_progress(self.workspace, "logic", {}, event="pause")
        resumed = save_progress(self.workspace, "logic", {}, event="resume")
        self.assertEqual(resumed["state"]["checkpoint"], checkpoint)
        self.assertEqual(resumed["state"]["next_step"], "答第 2 题")
        self.assertFalse(resumed["lesson_advanced"])
        with self.assertRaisesRegex(LearnFlowError, "待答断点"):
            save_progress(self.workspace, "logic", {"checkpoint": {"concept": "平均速度", "step": 3}})
        next_question = {"concept": "平均速度", "step": 5, "question": "换一种条件，规则还成立吗？"}
        advanced = save_progress(self.workspace, "logic", {"checkpoint": next_question})
        self.assertEqual(advanced["state"]["checkpoint"], next_question)
        self.assertIsNone(advanced["state"]["next_step"])
        cleared = save_progress(self.workspace, "logic", {"checkpoint": None, "next_step": "开始隔时复测"})
        self.assertIsNone(cleared["state"]["checkpoint"])
        self.assertEqual(cleared["state"]["next_step"], "开始隔时复测")
        self.assertEqual(load_progress(self.workspace, "logic", first["revision"])["state"]["checkpoint"], checkpoint)

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
