"""Persist supplied observations; never infer mastery or advance a lesson."""

from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path

from lf_common import LearnFlowError, database, safe_id
from lf_exams import apply_grades, exam_resume, nonblank, register_exam, validate_exam_evidence


SESSION_STATES = {"进行中", "等待作答", "已暂停", "已结束"}
UNIT_STATES = {"未开始", "进行中", "目标达成", "暂停待续", "主动跳过"}
EVIDENCE_STATES = {"未评估", "待验证", "已验证"}
SUPPORT = {"independent", "hinted", "answer_seen", "not_attempted"}


def merge_dict(base: dict, patch: dict):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_dict(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def verification_issue(state, by_id):
    level = state.get("level")
    if state.get("status") != "已验证" or level in (None, "L0"):
        return None
    qualifying = {"independent"} if level in {"L3", "L4", "L5", "L6"} else {"independent", "hinted"}
    successful = [
        item for key in state.get("evidence_ids", [])
        if (item := by_id[key])["support"] in qualifying and item.get("correct") is True
        and item["learner_answer"].strip() and not item.get("invalid_question")
        and not item.get("answer_exposed")
    ]
    if not successful:
        return "已验证等级需要符合要求的正确作答；独立作答、答错或结果未判定本身不能证明掌握。"
    if level in {"L3", "L4", "L5", "L6"}:
        tasks = {task.strip() for item in successful
                 if isinstance(task := item.get("task_id"), str) and task.strip()}
        reason = state.get("threshold_reason")
        if len(tasks) < 2 and not (isinstance(reason, str) and reason.strip()):
            return "应用及以上等级默认需要两项不同任务的独立正确作答；调整门槛须说明原因。"
    if level == "L4" and not any(item.get("transfer") for item in successful):
        return "L4 需要新情境中的独立正确作答，不能用普通题代替迁移。"
    if level == "L5" and not any(item.get("delayed") for item in successful):
        return "L5 需要隔时复测的独立正确作答；同轮换题或隔时答错都不算。"
    return None


def validate_progress(value: dict, *, retained_mastery=()):
    if value.get("session_status") not in SESSION_STATES:
        raise LearnFlowError("会话状态须沿用原设定：进行中、等待作答、已暂停、已结束。")
    if value.get("unit_status") not in UNIT_STATES:
        raise LearnFlowError("单元状态无效。")
    if not isinstance(value.get("reading"), dict) or not isinstance(value.get("mastery"), dict):
        raise LearnFlowError("reading 与 mastery 必须分开保存为对象。")
    course = value.get("course")
    if course is not None:
        if (not isinstance(course, dict) or not nonblank(course.get("goal"))
                or course.get("phase") not in ("讲", "练", "测", "评")
                or not isinstance(course.get("remaining"), list)
                or any(not nonblank(item) for item in course["remaining"])
                or any(key in course and not nonblank(course[key]) for key in ("return_to", "time_plan"))):
            raise LearnFlowError("课程断点需要目标 goal、阶段 phase 和剩余任务列表 remaining。")
        if "exam_id" in course and (not isinstance(course["exam_id"], str)
                                   or course["exam_id"] not in value.get("locked_exams", {})):
            raise LearnFlowError("课程断点的 exam_id 必须指向已锁定的测验。")
    checkpoint = value.get("checkpoint")
    if checkpoint is not None:
        if not isinstance(checkpoint, dict):
            raise LearnFlowError("待答断点须为对象。")
        step, phase = checkpoint.get("step"), checkpoint.get("phase")
        numbered = type(step) is int and 1 <= step <= 5 and phase is None
        staged = step is None and isinstance(phase, str) and phase in {"讲", "练", "测", "评"}
        if (not (numbered or staged)
                or any(not isinstance(checkpoint.get(field), str) or not checkpoint[field].strip()
                       for field in ("concept", "question"))):
            raise LearnFlowError("待答断点需要 concept、原题 question，以及 step（1–5）或 phase（讲/练/测/评）。")
    evidence = value.get("evidence", [])
    if not isinstance(evidence, list):
        raise LearnFlowError("evidence 必须是证据列表。")
    by_id = {}
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise LearnFlowError("每条证据需要实际的 id。")
        if item["id"] in by_id:
            raise LearnFlowError("证据 ID 不可重复。")
        if item.get("support") not in SUPPORT:
            raise LearnFlowError("证据 support 须区分 independent、hinted、answer_seen、not_attempted。")
        if "learner_answer" not in item or not isinstance(item["learner_answer"], str):
            raise LearnFlowError("证据需保存实际原始作答；未作答时显式留空，不生成答案。")
        if item["support"] == "independent" and not item["learner_answer"].strip():
            raise LearnFlowError("没有原始作答的记录不能标为独立完成。")
        for field in ("delayed", "transfer", "answer_exposed", "invalid_question"):
            if field in item and not isinstance(item[field], bool):
                raise LearnFlowError(f"证据 {field} 必须为布尔值。")
        if item.get("answer_exposed") and item["support"] == "independent":
            raise LearnFlowError("已暴露答案的这次作答不能标为独立证据。")
        by_id[item["id"]] = item
    warnings = []
    for concept, state in value["mastery"].items():
        if not isinstance(state, dict):
            raise LearnFlowError(f"知识点 {concept} 的状态须为对象。")
        level = state.get("level")
        if level is not None and level not in {f"L{i}" for i in range(7)}:
            raise LearnFlowError("能力等级保留 L0–L6，不接受其他体系。")
        if state.get("status", "未评估") not in EVIDENCE_STATES:
            raise LearnFlowError("证据状态无效。")
        references = state.get("evidence_ids", [])
        if not isinstance(references, list) or any(not isinstance(e, str) or e not in by_id for e in references):
            raise LearnFlowError("掌握状态引用了不存在的证据。")
        issue = verification_issue(state, by_id)
        if issue:
            if concept not in retained_mastery:
                raise LearnFlowError(issue)
            warnings.append({"concept": concept, "level": level, "reason": issue})
    for entry in value.get("review", []):
        if not isinstance(entry, dict):
            raise LearnFlowError("复习队列项须为对象。")
        for field in ("suggested_on", "agreed_on"):
            if entry.get(field):
                try:
                    date.fromisoformat(entry[field])
                except (TypeError, ValueError) as exc:
                    raise LearnFlowError("复习日期须是明确的 YYYY-MM-DD；相对时间可另记 note。") from exc
        if entry.get("reminder_created") and not entry.get("reminder_receipt"):
            raise LearnFlowError("没有实际工具回执，不能声称已创建提醒。")
    return warnings


def save_progress(workspace: Path, topic_id: str, patch: dict, *, event="snapshot", expected_revision=None) -> dict:
    safe_id(topic_id, "主题 ID")
    if not isinstance(patch, dict) or event not in {"snapshot", "pause", "end", "resume"}:
        raise LearnFlowError("进度输入须为对象，event 须为 snapshot/pause/end/resume。")
    con = database(workspace)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT revision,payload FROM progress WHERE topic_id=?", (topic_id,)).fetchone()
        revision = row["revision"] if row else 0
        if expected_revision is not None and expected_revision != revision:
            raise LearnFlowError("进度已被其他操作更新；请重新读取后合并，未覆盖旧记录。")
        state = json.loads(row["payload"]) if row else {
            "schema_version": 1, "topic_id": topic_id, "session_status": "进行中",
            "unit_status": "未开始", "reading": {}, "mastery": {}, "evidence": [],
            "review": [], "next_step": None}
        if patch.get("topic_id", topic_id) != topic_id:
            raise LearnFlowError("输入的 topic_id 与目标记录不一致。")
        if event == "snapshot" and patch.get("session_status") in {"已暂停", "已结束"} and patch.get("session_status") != state["session_status"]:
            raise LearnFlowError("仅记录不能结束会话；明确暂停或结束时使用对应 event。")
        old_evidence = {e["id"]: e for e in state["evidence"]}
        patch = copy.deepcopy(patch)
        if "locked_exams" in patch:
            raise LearnFlowError("不能直接改写测验档案；使用 exam_plan 或 exam_grades。")
        prior_exams = dict(state.get("locked_exams", {}))
        if "exam_plan" in patch:
            register_exam(state, patch.pop("exam_plan"), revision + 1)
        grading = patch.pop("exam_grades", [])
        if "course" in patch:
            state["course"] = patch.pop("course")
        mastery_patch = patch.get("mastery", {})
        if not isinstance(mastery_patch, dict):
            raise LearnFlowError("mastery 必须是对象。")
        retained_mastery = state["mastery"].keys() - mastery_patch.keys()
        if "checkpoint" in patch:
            checkpoint = patch.pop("checkpoint")
            if state.get("checkpoint") is not None and checkpoint != state["checkpoint"] and "next_step" not in patch:
                state["next_step"] = None
            state["checkpoint"] = checkpoint
        additions = patch.pop("evidence", [])
        if not isinstance(additions, list):
            raise LearnFlowError("evidence 须为列表。")
        for item in additions:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise LearnFlowError("证据项缺少 id。")
            if item["id"] in old_evidence:
                if old_evidence[item["id"]] != item:
                    raise LearnFlowError("已保存原始证据不能覆盖；请用新 ID 记录纠正并注明原 ID。")
            else:
                if "correct" in item and not isinstance(item["correct"], bool):
                    raise LearnFlowError("证据 correct 须为布尔值；尚未判定时省略。")
                validate_exam_evidence(item, prior_exams)
                state["evidence"].append(item)
                old_evidence[item["id"]] = item
        merge_dict(state, patch)
        state["topic_id"] = topic_id
        state["schema_version"] = 1
        if event == "pause":
            state["session_status"] = "已暂停"
        elif event == "end":
            state["session_status"] = "已结束"
        elif event == "resume":
            state["session_status"] = "进行中"
        warnings = validate_progress(state, retained_mastery=retained_mastery)
        apply_grades(state, grading, revision + 1)
        payload = json.dumps(state, ensure_ascii=False, allow_nan=False)
        con.execute("INSERT INTO progress_history VALUES(?,?,?)", (topic_id, revision + 1, payload))
        con.execute("INSERT INTO progress VALUES(?,?,?) ON CONFLICT(topic_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload",
                    (topic_id, revision + 1, payload))
        con.commit()
        return {"topic_id": topic_id, "revision": revision + 1, "event": event, "state": state,
                "mastery_warnings": warnings, "exam_resume": exam_resume(state),
                "lesson_advanced": False, "reminder_created": False}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def load_progress(workspace: Path, topic_id: str, revision=None):
    con = database(workspace)
    try:
        if revision is None:
            row = con.execute("SELECT revision,payload FROM progress WHERE topic_id=?", (topic_id,)).fetchone()
        else:
            row = con.execute("SELECT revision,payload FROM progress_history WHERE topic_id=? AND revision=?", (topic_id, revision)).fetchone()
        if row is None:
            raise LearnFlowError("没有这份历史记录；不假设过去的学习进度。")
        state = json.loads(row["payload"])
        warnings = validate_progress(state, retained_mastery=state["mastery"])
        return {"topic_id": topic_id, "revision": row["revision"], "state": state,
                "mastery_warnings": warnings, "exam_resume": exam_resume(state)}
    finally:
        con.close()


def due_reviews(workspace: Path, topic_id: str, on: str):
    try:
        target = date.fromisoformat(on)
    except ValueError as exc:
        raise LearnFlowError("请用 --on 指定用户当地的 YYYY-MM-DD，不推测日期。") from exc
    record = load_progress(workspace, topic_id)
    items = []
    for item in record["state"].get("review", []):
        due = item.get("agreed_on") or item.get("suggested_on")
        if due and date.fromisoformat(due) <= target and not item.get("completed"):
            items.append(item)
    return {"topic_id": topic_id, "on": on, "items": items,
            "reminder_created": False, "reading_progress_changed": False}
