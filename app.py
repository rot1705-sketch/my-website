from pathlib import Path

from flask import Flask, abort, render_template, request

import quiz

app = Flask(__name__)
FORMULAS = Path(app.static_folder) / "formulas"


@app.context_processor
def helpers():
    return {"LETTERS": quiz.LETTERS}


@app.route("/")
def home():
    return render_template("index.html", degrees=quiz.load_catalog()["degrees"])


@app.route("/degree/<degree_id>")
def degree(degree_id):
    deg = quiz.find_degree(degree_id) or abort(404)
    courses = [
        {**c, "count": quiz.question_count(quiz.load_course(c["id"]))}
        for c in deg["courses"]
    ]
    return render_template("degree.html", degree=deg, courses=courses)


@app.route("/course/<course_id>")
def course(course_id):
    deg, crs = quiz.find_course(course_id)
    if not crs:
        abort(404)
    count = quiz.question_count(quiz.load_course(course_id))
    formula = (FORMULAS / f"{course_id}.pdf").exists()
    return render_template("course.html", degree=deg, course=crs, count=count, formula=formula)


@app.route("/course/<course_id>/quiz", methods=["GET", "POST"])
def take_quiz(course_id):
    deg, crs = quiz.find_course(course_id)
    data = quiz.load_course(course_id)
    if not crs or not data:
        abort(404)

    if request.method == "POST":
        results, score = quiz.grade(data, request.form)
        return render_template("result.html", degree=deg, course=crs, results=results, score=score)

    wanted = request.args.get("n", 10, type=int)
    wanted = max(1, min(wanted, 50))
    groups = quiz.build_quiz(data, wanted)
    qids = ",".join(item["q"]["id"] for g in groups for item in g["questions"])
    return render_template("quiz.html", degree=deg, course=crs, groups=groups, qids=qids)


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True)
