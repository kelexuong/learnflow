"""Render a private learning report from recorded attempts, without scoring answers."""

from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from string import Template

from lf_common import LearnFlowError, SKILL_ROOT, digest_file
from lf_outputs import output_path, string
from lf_progress import load_progress


SERIES = (
    ("correct", "独立答对"),
    ("wrong", "独立答错"),
    ("hinted", "提示后作答"),
    ("seen", "看答案后作答"),
    ("ungraded", "独立未判定"),
)


def text(value):
    return value.strip() if isinstance(value, str) else ""


def score_exam(exam):
    scores = []
    for section in exam["plan"]["sections"]:
        earned = graded_max = 0
        count = 0
        for item in section["items"]:
            history = exam["grades"].get(item["task_id"])
            if history:
                earned += history[-1]["points"]
                graded_max += item["max_points"]
                count += 1
        scores.append({"title": section["title"], "graded": count, "items": len(section["items"]),
                       "earned": earned, "graded_max": graded_max,
                       "max_points": sum(item["max_points"] for item in section["items"])})
    complete = all(row["graded"] == row["items"] for row in scores)
    return {"id": exam["plan"]["id"], "sections": scores, "percent": (
        round(100 * sum(row["earned"] for row in scores) / sum(row["max_points"] for row in scores), 1)
        if complete else None)}


def summarize_report(record, concepts=(), excluded_ids=(), *, session=False, next_task=None):
    state = record["state"]
    mastery = state["mastery"]
    warned = {item["concept"] for item in record.get("mastery_warnings", [])}
    links = defaultdict(set)
    for name, entry in mastery.items():
        for key in entry.get("evidence_ids", []):
            links[key].add(name)

    rows = {}

    def row_for(name):
        return rows.setdefault(name, {"concept": name, **dict.fromkeys((key for key, _ in SERIES), 0),
                                      "transfer": 0, "delayed": 0, "feedback": "", "retry_question": ""})

    for concept in concepts:
        row_for(string(concept, "知识点").strip())
    if not session:
        for concept in mastery:
            row_for(concept)
    excluded_ids = set(excluded_ids)
    for item in state["evidence"]:
        if (item["id"] in excluded_ids or item.get("invalid_question") or
                not text(item.get("learner_answer")) or item["support"] == "not_attempted"):
            continue
        linked = links.get(item["id"], set())
        name = text(item.get("concept")) or (next(iter(linked)) if len(linked) == 1 else None)
        row = row_for(name)
        if item.get("correct") is False or item["support"] in {"hinted", "answer_seen"}:
            feedback, retry = text(item.get("feedback")), text(item.get("retry_question"))
            if feedback or retry:
                row.update(feedback=feedback, retry_question=retry)
        if item["support"] == "answer_seen" or item.get("answer_exposed"):
            row["seen"] += 1
        elif item["support"] == "hinted":
            row["hinted"] += 1
        elif item.get("correct") is True:
            row["correct"] += 1
            row["transfer"] += int(bool(item.get("transfer")))
            row["delayed"] += int(bool(item.get("delayed")))
        elif item.get("correct") is False:
            row["wrong"] += 1
        else:
            row["ungraded"] += 1

    if None in rows:
        rows[None] = rows.pop(None)
    totals = {key: sum(row[key] for row in rows.values()) for key, _ in SERIES}
    for name, row in rows.items():
        entry = mastery.get(name, {})
        row["level"] = entry.get("level")
        row["status"] = "待复核" if name in warned else entry.get("status", "未评估")
    checkpoint = state.get("checkpoint")
    if next_task is not None:
        action = string(next_task, "下一步").strip()
    elif checkpoint:
        position = f"「{checkpoint['phase']}」阶段" if checkpoint.get("phase") else f"第 {checkpoint['step']} 步"
        action = f"接回「{checkpoint['concept']}」{position}的待答题。"
    elif text(state.get("next_step")):
        action = text(state["next_step"])
    else:
        weaker = next((name for name, row in rows.items() if name and
                       (row["wrong"] or row["hinted"] or row["seen"])), None)
        action = f"换一道题，独立解释「{weaker}」的判断依据。" if weaker else (
            "挑一个核心知识点，闭卷用自己的话解释，再决定是否做变式。")
    return {"rows": list(rows.values()), "totals": totals, "next_task": action}


def render_report(data, title, scope):
    def render_row(row):
        name = escape(row["concept"] if row["concept"] is not None else "未归类作答")
        total = sum(row[key] for key, _ in SERIES)
        pieces = "".join(f'<span class="{key}" style="flex-grow:{row[key]}"></span>'
                         for key, _ in SERIES if row[key])
        bar = f'<div class="bar" aria-hidden="true">{pieces}</div>' if total else '<div class="bar empty" aria-hidden="true"></div>'
        captions = "、".join(f"{label} {row[key]}" for key, label in SERIES if row[key]) or "本范围未测"
        level = f'{escape(row["level"])} · {escape(row["status"])}' if row["level"] else escape(row["status"])
        evidence = (f'<p class="evidence">迁移答对 {row["transfer"]} · 隔时答对 {row["delayed"]}</p>'
                    if row["transfer"] or row["delayed"] else "")
        coaching = "".join(f'<p class="coaching"><strong>{label}</strong>{escape(row[key])}</p>'
                           for key, label in (("feedback", "曾卡在哪："), ("retry_question", "下次复测："))
                           if row[key])
        return (f'<li class="trace"><div><h3>{name}</h3><p class="status">当前记录：{level}</p></div>'
                f'<div>{bar}<p class="counts">{captions}</p>'
                f'{evidence}{coaching}</div></li>')

    totals = data["totals"]
    attempts = sum(totals.values())
    judged = totals["correct"] + totals["wrong"]
    ratio = f'{totals["correct"]} / {judged}' if judged else "未测"
    explanation = f"全过程独立正确率 {100 * totals['correct'] / judged:.0f}%" if judged else "暂无已判定的独立作答"
    legend = "".join(f'<li><i class="{key}"></i>{label}</li>' for key, label in SERIES)
    rows = "".join(render_row(row) for row in data["rows"]) or (
        '<li class="empty-row">还没有可归类的作答。完成一个核心问题后，可以再生成反馈。</li>')
    scores = ""
    if assessment := data.get("assessment"):
        percent = assessment["percent"]
        label = "部分测评 · 暂无结课总分" if percent is None else f"结课总分 {percent:g} / 100"
        detail = ""
        for row in assessment["sections"]:
            value = f'{row["earned"]:g} / {row["graded_max"]:g}（已评分题）' if row["graded"] else "未评分"
            detail += (f'<li><strong>{escape(row["title"])}</strong><span>{value}；'
                       f'{row["graded"]} / {row["items"]} 题已评分</span></li>')
        scores = (f'<section class="scores"><h2>{label}</h2><p>已锁定的测验 · {escape(assessment["id"])}</p>'
                  f'<ul>{detail}</ul></section>')
    template = Template((SKILL_ROOT / "assets" / "learning-report.html").read_text(encoding="utf-8"))
    return template.substitute(title=escape(title), scope=escape(scope), ratio=ratio, explanation=explanation,
                               attempts=attempts, concepts=len(data["rows"]), legend=legend, rows=rows,
                               next_task=escape(data["next_task"]), scores=scores)


def export_report(workspace, topic_id, output, *, title=None, concepts=(), since_revision=None,
                  next_task=None, exam_id=None):
    if Path(output).suffix.lower() != ".html":
        raise LearnFlowError("学情单输出须为 .html。")
    record = load_progress(workspace, topic_id)
    if since_revision is not None and not 0 <= since_revision <= record["revision"]:
        raise LearnFlowError("起始版本须在 0 与当前记录版本之间。")
    prior = load_progress(workspace, topic_id, since_revision) if since_revision else None
    excluded = {item["id"] for item in prior["state"]["evidence"]} if prior else set()
    data = summarize_report(record, concepts, excluded, session=since_revision is not None, next_task=next_task)
    if exam_id is not None:
        exam = record["state"].get("locked_exams", {}).get(exam_id)
        if not exam:
            raise LearnFlowError("找不到该场已锁定测验；请先保存 exam_plan。")
        data["assessment"] = score_exam(exam)
    scope = "本次新增作答" if since_revision is not None else "主题累计作答"
    heading = string(title, "标题").strip() if title is not None else f"{topic_id} 学情反馈"
    content = render_report(data, heading, scope)
    path = output_path(workspace, output)
    with path.open("x", encoding="utf-8", newline="\n") as file:
        file.write(content)
    return {"path": str(path), "scope": scope, "totals": data["totals"],
            "assessment": data.get("assessment"), "sha256": digest_file(path),
            "offline": True, "mastery_updated": False}
