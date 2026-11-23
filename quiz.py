"""Question bank loading, random quiz building and grading.

Data layout (all inside the repo, under data/):
  catalog.json          degrees -> courses
  courses/<id>.json     one file per course with its question groups

Every question is stored the way a "Tofes 0" is written: the FIRST option
is always the correct one. When a quiz is built the options are shuffled,
except the last `pin_last` options (e.g. "אין תשובה נכונה"), which stay last.

Questions live inside groups. A group can carry a shared `context`
(a table or a problem statement); its questions are always drawn together.
"""

import json
import random
from pathlib import Path

DATA = Path(__file__).parent / "data"
LETTERS = "אבגדהוזח"


def load_catalog():
    return json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))


def find_degree(degree_id):
    for degree in load_catalog()["degrees"]:
        if degree["id"] == degree_id:
            return degree
    return None


def find_course(course_id):
    """Return (degree, course) from the catalog, or (None, None)."""
    for degree in load_catalog()["degrees"]:
        for course in degree["courses"]:
            if course["id"] == course_id:
                return degree, course
    return None, None


def load_course(course_id):
    path = DATA / "courses" / f"{course_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def question_count(course_data):
    if not course_data:
        return 0
    return sum(len(g["questions"]) for g in course_data["groups"])


def shuffled_order(question):
    """Random display order of option indexes; pinned options stay last."""
    n = len(question["options"])
    pinned = question.get("pin_last", 0)
    free = list(range(n - pinned))
    random.shuffle(free)
    return free + list(range(n - pinned, n))


def build_quiz(course_data, wanted):
    """Pick random groups until at least `wanted` questions are collected."""
    groups = list(course_data["groups"])
    random.shuffle(groups)
    quiz, count = [], 0
    for group in groups:
        if count >= wanted:
            break
        quiz.append({
            "context": group.get("context"),
            "questions": [{"q": q, "order": shuffled_order(q)} for q in group["questions"]],
        })
        count += len(group["questions"])
    return quiz


def _index(course_data):
    return {q["id"]: (g, q) for g in course_data["groups"] for q in g["questions"]}


def grade(course_data, form):
    """Grade a submitted quiz form. Original option index 0 is the correct one."""
    index = _index(course_data)
    results = []
    for qid in form.get("qids", "").split(","):
        if qid not in index:
            continue
        group, q = index[qid]
        try:
            order = [int(x) for x in form.get(f"order_{qid}", "").split(",")]
        except ValueError:
            order = []
        if sorted(order) != list(range(len(q["options"]))):
            order = list(range(len(q["options"])))
        chosen = form.get(f"ans_{qid}")
        chosen = int(chosen) if chosen is not None and chosen.isdigit() else None
        results.append({
            "q": q,
            "context": group.get("context"),
            "order": order,
            "chosen": chosen,
            "correct": chosen == 0,
        })
    score = round(100 * sum(r["correct"] for r in results) / len(results)) if results else 0
    return results, score
