"""Lock exam plans before answering and keep an auditable score history."""

from lf_common import LearnFlowError, safe_id


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def identifier(value, label):
    if not isinstance(value, str):
        raise LearnFlowError(f"{label} 须为文字。")
    return safe_id(value, label)


def questions(plan):
    return {item["task_id"]: item for section in plan["sections"] for item in section["items"]}


def register_exam(state, plan, revision):
    if not isinstance(plan, dict) or not isinstance(plan.get("sections"), list) or not plan["sections"]:
        raise LearnFlowError("开考前须保存 exam_plan 和非空 sections。")
    exam_id = identifier(plan.get("id"), "测验 ID")
    seen = set()
    for section in plan["sections"]:
        if (not isinstance(section, dict) or not nonblank(section.get("title"))
                or not isinstance(section.get("items"), list) or not section["items"]):
            raise LearnFlowError("测验板块需要名称与题目。")
        for item in section["items"]:
            if not isinstance(item, dict):
                raise LearnFlowError("测验题须为对象。")
            task = identifier(item.get("task_id"), "测验题 ID")
            maximum = item.get("max_points")
            if task in seen or not all(nonblank(item.get(key)) for key in ("question", "criteria")):
                raise LearnFlowError("测验题需要唯一 ID、题目原文和评分标准。")
            if type(maximum) not in (int, float) or not 0 < maximum <= 10000:
                raise LearnFlowError("测验题满分须大于零且不超过 10000。")
            seen.add(task)
    exams = state.setdefault("locked_exams", {})
    if exam_id in exams:
        if exams[exam_id]["plan"] != plan:
            raise LearnFlowError("同一场测验的题目、满分和评分规则已锁定；新测验请使用新 ID。")
    else:
        exams[exam_id] = {"plan": plan, "opened_revision": revision, "grades": {},
                         "evidence_start": len(state["evidence"])}


def validate_exam_evidence(item, prior_exams):
    if item.get("activity") != "exam" and item.get("exam_id") is None:
        return
    exam_id = identifier(item.get("exam_id"), "作答的测验 ID")
    task_id = identifier(item.get("task_id"), "作答的测验题 ID")
    if item.get("activity") != "exam" or exam_id not in prior_exams:
        raise LearnFlowError("正式作答须绑定已经保存的测验；先锁定试题，再单独保存作答。")
    if task_id not in questions(prior_exams[exam_id]["plan"]):
        raise LearnFlowError("作答题目不属于这场已锁定测验。")


def submitted(evidence, exam):
    first = {}
    for item in evidence[exam["evidence_start"]:]:
        if (item.get("activity") == "exam" and item.get("exam_id") == exam["plan"]["id"] and
                (item.get("answer_exposed") or item.get("support") == "answer_seen"
                 or (item.get("support") != "not_attempted" and nonblank(item.get("learner_answer"))))):
            first.setdefault(item["task_id"], item)
    return first


def apply_grades(state, grading, revision):
    if not isinstance(grading, list):
        raise LearnFlowError("exam_grades 须为列表。")
    touched = set()
    attempts = {}
    for grade in grading:
        if not isinstance(grade, dict):
            raise LearnFlowError("测验给分须为对象。")
        exam_id = identifier(grade.get("exam_id"), "测验 ID")
        task = identifier(grade.get("task_id"), "测验题 ID")
        exam = state.get("locked_exams", {}).get(exam_id)
        if not exam or task not in questions(exam["plan"]):
            raise LearnFlowError("不能给未锁定的测验或题目评分。")
        if (exam_id, task) in touched:
            raise LearnFlowError("同一道题在一次保存中只能记一次分。")
        touched.add((exam_id, task))
        if exam_id not in attempts:
            attempts[exam_id] = submitted(state["evidence"], exam)
        answer = attempts[exam_id].get(task)
        if (not answer or answer["id"] != grade.get("evidence_id") or answer["support"] != "independent"
                or answer.get("invalid_question") or answer.get("answer_exposed")
                or not nonblank(answer.get("learner_answer")) or type(answer.get("correct")) is not bool):
            raise LearnFlowError("正式评分只接受同场同题首次、已判定的独立作答；练习和重试不计入。")
        maximum = questions(exam["plan"])[task]["max_points"]
        points = grade.get("points")
        if type(points) not in (int, float) or not 0 <= points <= maximum:
            raise LearnFlowError("实际得分须在 0 和本题满分之间。")
        if points == maximum and not answer["correct"]:
            raise LearnFlowError("标为答错的正式作答不能给满分。")
        history = exam["grades"].setdefault(task, [])
        if history and points == history[-1]["points"]:
            continue
        reason = grade.get("reason")
        if history and not nonblank(reason):
            raise LearnFlowError("修订已保存的成绩需要说明原因；原给分会保留。")
        history.append({"evidence_id": answer["id"], "points": points, "revision": revision,
                        **({"reason": reason.strip()} if nonblank(reason) else {})})


def exam_resume(state):
    exam_id = (state.get("course") or {}).get("exam_id")
    exam = state.get("locked_exams", {}).get(exam_id)
    if not exam:
        return None
    items = questions(exam["plan"])
    answers = submitted(state["evidence"], exam)
    return {"exam_id": exam_id,
            "unanswered": [key for key in items if key not in answers],
            "ungraded": [key for key in items if key in answers and key not in exam["grades"]]}
