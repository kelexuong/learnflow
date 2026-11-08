import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lf_common import LearnFlowError, workspace_path
from lf_progress import load_progress, save_progress


def plan():
    return {"id": "ride-final", "sections": [{"title": "应用", "items": [
        {"task_id": "Q1", "question": "全程平均速度是多少？", "criteria": "答案和单位各 5 分", "max_points": 10},
        {"task_id": "Q2", "question": "停顿时间要算进去吗？", "criteria": "判断和理由各 5 分", "max_points": 10},
    ]}]}


def answer(key, **values):
    return {"id": key, "task_id": "Q1", "activity": "exam", "exam_id": "ride-final",
            "learner_answer": "演示答案", "support": "independent", "correct": True, **values}


def grade(key, points, **values):
    return {"exam_id": "ride-final", "task_id": "Q1", "evidence_id": key, "points": points, **values}


class ExamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lf-exam-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = workspace_path(Path(self.temp.name) / "study")

    def save(self, patch, event="snapshot"):
        return save_progress(self.work, "ride", patch, event=event)

    def test_plan_cannot_be_created_with_first_answer_or_rewritten_afterwards(self):
        with self.assertRaisesRegex(LearnFlowError, "先锁定"):
            self.save({"exam_plan": plan(), "evidence": [answer("early")]})
        self.save({"exam_plan": plan()})
        altered = copy.deepcopy(plan())
        altered["sections"][0]["items"][0]["max_points"] = 20
        with self.assertRaisesRegex(LearnFlowError, "已锁定"):
            self.save({"exam_plan": altered})
        with self.assertRaises(LearnFlowError):
            self.save({"locked_exams": {}})
        self.assertEqual(load_progress(self.work, "ride")["state"]["locked_exams"]["ride-final"]["plan"], plan())

    def test_practice_and_later_retry_cannot_replace_the_first_exam_attempt(self):
        practice = answer("practice", activity="practice", exam_id=None)
        self.save({"evidence": [practice], "exam_plan": plan()})
        self.save({"evidence": [answer("first", correct=False), answer("retry")]})
        for rejected in (grade("practice", 10), grade("retry", 10), grade("first", 10)):
            with self.subTest(grade=rejected), self.assertRaises(LearnFlowError):
                self.save({"exam_grades": [rejected]})
        self.save({"exam_grades": [grade("first", 4)]})

    def test_pause_resumes_course_context_and_preserves_regrading_history(self):
        course = {"goal": "会算平均速度", "phase": "测", "exam_id": "ride-final",
                  "remaining": ["答 Q2", "结课反馈"], "return_to": "补讲后回 Q2", "time_plan": "讲 5、练 3、测 2 分钟"}
        self.save({"exam_plan": plan(), "course": course})
        self.save({"evidence": [answer("first")], "exam_grades": [grade("first", 8)]})
        pending = {"concept": "停顿", "phase": "测", "question": "停顿时间要算进去吗？"}
        self.save({"checkpoint": pending}, "pause")
        resumed = self.save({}, "resume")
        self.assertEqual(resumed["state"]["course"], course)
        self.assertEqual(resumed["state"]["checkpoint"], pending)
        self.assertEqual(resumed["exam_resume"]["unanswered"], ["Q2"])
        with self.assertRaisesRegex(LearnFlowError, "说明原因"):
            self.save({"exam_grades": [grade("first", 9)]})
        fixed = self.save({"exam_grades": [grade("first", 9, reason="核对后确认单位正确。")]})
        history = fixed["state"]["locked_exams"]["ride-final"]["grades"]["Q1"]
        self.assertEqual([g["points"] for g in history], [8, 9])
        self.assertEqual(history[-1]["reason"], "核对后确认单位正确。")
