"""Persist supplied observations; never infer mastery or advance a lesson."""

from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path

from lf_common import LearnFlowError, database, safe_id


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


def validate_progress(value: dict):
    if value.get("session_status") not in SESSION_STATES:
        raise LearnFlowError("会话状态须沿用原设定：进行中、等待作答、已暂停、已结束。")
    if value.get("unit_status") not in UNIT_STATES:
        raise LearnFlowError("单元状态无效。")
    if not isinstance(value.get("reading"), dict) or not isinstance(value.get("mastery"), dict):
        raise LearnFlowError("reading 与 mastery 必须分开保存为对象。")
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
    for concept, state in value["mastery"].items():
        if not isinstance(state, dict):
            raise LearnFlowError(f"知识点 {concept} 的状态须为对象。")
        level = state.get("level")
        if level is not None and level not in {f"L{i}" for i in range(7)}:
            raise LearnFlowError("能力等级保留 L0–L6，不接受其他体系。")
        if state.get("status", "未评估") not in EVIDENCE_STATES:
            raise LearnFlowError("证据状态无效。")
        references = state.get("evidence_ids", [])
        if not isinstance(references, list) or any(e not in by_id for e in references):
            raise LearnFlowError("掌握状态引用了不存在的证据。")
        if state.get("status") == "已验证" and level not in (None, "L0"):
            independent = [by_id[e] for e in references if by_id[e]["support"] == "independent"
                           and not by_id[e].get("invalid_question")]
            matching = independent if level in {"L3", "L4", "L5", "L6"} else [
                by_id[e] for e in references if by_id[e]["support"] in {"independent", "hinted"}
                and by_id[e]["learner_answer"].strip() and not by_id[e].get("invalid_question")]
            if not matching:
                raise LearnFlowError("已验证等级需要原规则对应的表现证据，不能用读完或看答案替代。")
            if level in {"L3", "L4", "L5", "L6"} and len({e.get("task_id", e["id"]) for e in independent}) < 2 and not state.get("threshold_reason"):
                raise LearnFlowError("应用及以上等级默认需不同任务交叉验证；复杂任务调整门槛时记录 threshold_reason。")
            if level == "L5" and not any(e.get("delayed") for e in independent):
                raise LearnFlowError("L5 必须包含实际延迟复测证据；即时换题不算延迟。")
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
        additions = patch.pop("evidence", [])
        if not isinstance(additions, list):
            raise LearnFlowError("evidence 须为列表。")
        for item in additions:
            if not isinstance(item, dict) or "id" not in item:
                raise LearnFlowError("证据项缺少 id。")
            if item["id"] in old_evidence:
                if old_evidence[item["id"]] != item:
                    raise LearnFlowError("已保存原始证据不能覆盖；请用新 ID 记录纠正并注明原 ID。")
            else:
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
        validate_progress(state)
        payload = json.dumps(state, ensure_ascii=False, allow_nan=False)
        con.execute("INSERT INTO progress_history VALUES(?,?,?)", (topic_id, revision + 1, payload))
        con.execute("INSERT INTO progress VALUES(?,?,?) ON CONFLICT(topic_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload",
                    (topic_id, revision + 1, payload))
        con.commit()
        return {"topic_id": topic_id, "revision": revision + 1, "event": event, "state": state,
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
        return {"topic_id": topic_id, "revision": row["revision"], "state": json.loads(row["payload"])}
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
