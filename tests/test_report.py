from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lf_common import LearnFlowError, workspace_path
from lf_progress import load_progress, save_progress
from lf_report import export_report, summarize_report


def attempt(key, support="independent", answer="不应出现在学情单的原始作答", **fields):
    return {"id": key, "task_id": key, "support": support, "learner_answer": answer, **fields}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lf-report-test-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = workspace_path(Path(self.temp.name) / "study")

    def test_session_report_counts_only_eligible_attempts_and_keeps_no_score_for_unmeasured(self):
        first = save_progress(self.workspace, "study", {"evidence": [attempt("earlier", correct=True, concept="旧内容")]})
        save_progress(self.workspace, "study", {"evidence": [
            attempt("right", correct=True, concept="路程"),
            attempt("wrong", correct=False, concept="路程"),
            attempt("hinted", "hinted", correct=True, concept="路程"),
            attempt("seen", "hinted", correct=True, answer_exposed=True, concept="路程"),
            attempt("ungraded", concept="路程"),
            attempt("invalid", correct=True, invalid_question=True, concept="路程"),
            attempt("pending", "not_attempted", "", concept="未测点"),
        ]})
        before = load_progress(self.workspace, "study")
        result = export_report(self.workspace, "study", "reports/one.html", title="当次 <学习>",
                               concepts=["路程", "未测点"], since_revision=first["revision"])
        self.assertEqual(result["totals"], {"correct": 1, "wrong": 1, "hinted": 1, "seen": 1, "ungraded": 1})
        html = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn("独立正确率 50%", html)
        self.assertIn("本范围未测", html)
        self.assertNotIn("旧内容", html)
        self.assertNotIn("不应出现在学情单", html)
        self.assertIn("当次 &lt;学习&gt;", html)
        self.assertEqual(load_progress(self.workspace, "study"), before)

    def test_legacy_unlinked_attempts_not_guessed_and_old_grade_flags_remain_visible(self):
        record = {"state": {"mastery": {"时间": {"level": "L4", "status": "已验证", "evidence_ids": ["a"]}},
                            "evidence": [attempt("a"), attempt("b", correct=False)]},
                  "mastery_warnings": [{"concept": "时间"}]}
        rows = summarize_report(record)["rows"]
        self.assertEqual([(r["concept"], r["status"]) for r in rows], [("时间", "待复核"), (None, "未评估")])
        self.assertEqual((rows[0]["ungraded"], rows[1]["wrong"]), (1, 1))

    def test_no_attempts_no_percentage_and_export_respects_workspace(self):
        save_progress(self.workspace, "study", {})
        result = export_report(self.workspace, "study", "blank.html", concepts=["未测点"], since_revision=0)
        html = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn("暂无已判定的独立作答", html)
        self.assertNotIn("独立正确率 0%", html)
        for filename in ("../outside.html", "blank.html", "bad.txt"):
            with self.subTest(filename=filename), self.assertRaises(LearnFlowError):
                export_report(self.workspace, "study", filename)
        with self.assertRaises(LearnFlowError):
            export_report(self.workspace, "study", "future.html", since_revision=2)

    def test_report_reads_a_locked_exam_and_preserves_incomplete_scores(self):
        plan = {"id": "final", "sections": [{"title": "应用", "items": [
            {"task_id": "q1", "question": "第一题", "criteria": "说明理由得分", "max_points": 10},
            {"task_id": "q2", "question": "第二题", "criteria": "核对单位", "max_points": 20}]}]}
        saved = save_progress(self.workspace, "exam", {"exam_plan": plan})
        save_progress(self.workspace, "exam", {"evidence": [
            attempt("a1", correct=False, task_id="q1", exam_id="final", activity="exam")],
            "exam_grades": [{"exam_id": "final", "task_id": "q1", "evidence_id": "a1", "points": 5}]})
        partial = export_report(self.workspace, "exam", "partial.html",
                                exam_id="final", since_revision=saved["revision"])
        self.assertIsNone(partial["assessment"]["percent"])
        self.assertIn("暂无结课总分", Path(partial["path"]).read_text(encoding="utf-8"))
        save_progress(self.workspace, "exam", {"evidence": [
            attempt("a2", correct=True, task_id="q2", exam_id="final", activity="exam")],
            "exam_grades": [{"exam_id": "final", "task_id": "q2", "evidence_id": "a2", "points": 20}]})
        complete = export_report(self.workspace, "exam", "graded.html", exam_id="final")
        self.assertEqual(complete["assessment"]["percent"], 83.3)
        with self.assertRaises(LearnFlowError):
            export_report(self.workspace, "exam", "invalid.html", exam_id="unknown")

    def test_report_shows_real_feedback_and_retry_without_exposing_raw_answer(self):
        save_progress(self.workspace, "study", {"evidence": [attempt(
            "mistake", concept="用时", correct=False, feedback="漏算了等车时间。",
            retry_question="等车时间 < 10 分钟时怎样计算？")]})
        result = export_report(self.workspace, "study", "feedback.html")
        page = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn("漏算了等车时间。", page)
        self.assertIn("等车时间 &lt; 10 分钟时怎样计算？", page)
        self.assertNotIn("不应出现在学情单", page)
