import json
import os
import secrets
from datetime import timedelta
from functools import wraps
from pathlib import Path

from authlib.integrations.flask_client import OAuth
from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import db
import quiz

app = Flask(__name__)
# Render sits behind a proxy; trust its headers so Google gets an https:// callback URL.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    # Set SECRET_KEY in Render's environment, otherwise everyone is logged out on each restart.
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
FORMULAS = Path(app.static_folder) / "formulas"
PROFILE_OPTIONS = json.loads((quiz.DATA / "institutions.json").read_text(encoding="utf-8"))

GOOGLE_READY = bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

db.init()


# ---------- session, CSRF, login ----------

@app.before_request
def load_user_and_check_csrf():
    uid = session.get("uid")
    g.user = db.get_user(uid) if uid else None
    if uid and not g.user:
        session.clear()
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.context_processor
def helpers():
    return {"LETTERS": quiz.LETTERS, "csrf_token": csrf_token, "user": g.get("user")}


def profile_complete(user):
    return bool(user and user["institution"] and user["study_year"] and user["degree_id"])


def login_required(view):
    """Signed in AND finished the short sign-up form."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.user:
            session["next"] = request.full_path.rstrip("?")
            return redirect(url_for("login"))
        if not profile_complete(g.user):
            return redirect(url_for("profile"))
        return view(*args, **kwargs)
    return wrapper


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("home")


@app.route("/login")
def login():
    if g.user:
        return redirect(url_for("home"))
    return render_template("login.html", google_ready=GOOGLE_READY)


@app.route("/login/google")
def login_google():
    if not GOOGLE_READY:
        abort(503)
    return oauth.google.authorize_redirect(url_for("auth_callback", _external=True))


@app.route("/auth/callback")
def auth_callback():
    if not GOOGLE_READY:
        abort(503)
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        return render_template("login.html", google_ready=True,
                               error="ההתחברות עם Google נכשלה. נסה/י שוב.")
    info = token.get("userinfo") or {}
    if not info.get("sub") or not info.get("email") or not info.get("email_verified"):
        return render_template("login.html", google_ready=True,
                               error="חשבון ה-Google צריך כתובת אימייל מאומתת.")
    uid = db.upsert_google_user(
        info["sub"], info["email"].lower(), (info.get("name") or info["email"].split("@")[0])[:100]
    )
    next_url = session.pop("next", None)
    session.clear()
    session.permanent = True
    session["uid"] = uid
    user = db.get_user(uid)
    if not profile_complete(user):
        session["next"] = next_url
        return redirect(url_for("profile"))
    return redirect(safe_next(next_url))


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if not g.user:
        return redirect(url_for("login"))
    degrees = quiz.load_catalog()["degrees"]
    degree_ids = {d["id"] for d in degrees}
    first_time = not profile_complete(g.user)
    error = None
    form = {
        "institution": g.user["institution"] or "",
        "study_year": g.user["study_year"] or "",
        "degree_id": g.user["degree_id"] or "",
    }
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in form}
        if form["institution"] not in PROFILE_OPTIONS["institutions"]:
            error = "יש לבחור מוסד אקדמי מהרשימה."
        elif form["study_year"] not in PROFILE_OPTIONS["years"]:
            error = "יש לבחור שנת לימוד."
        elif form["degree_id"] not in degree_ids:
            error = "יש לבחור תחום לימוד."
        else:
            db.update_profile(g.user["id"], form["institution"], form["study_year"], form["degree_id"])
            return redirect(safe_next(session.pop("next", None)))
    return render_template("profile.html", form=form, error=error, first_time=first_time,
                           options=PROFILE_OPTIONS, degrees=degrees)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------- pages ----------

@app.route("/")
def home():
    if not g.user:
        return render_template("landing.html")
    if not profile_complete(g.user):
        return redirect(url_for("profile"))
    return redirect(url_for("degree", degree_id=g.user["degree_id"]))


@app.route("/degrees")
@login_required
def degrees():
    return render_template("index.html", degrees=quiz.load_catalog()["degrees"])


@app.route("/degree/<degree_id>")
@login_required
def degree(degree_id):
    deg = quiz.find_degree(degree_id) or abort(404)
    courses = [
        {**c, "count": quiz.question_count(quiz.load_course(c["id"]))}
        for c in deg["courses"]
    ]
    return render_template("degree.html", degree=deg, courses=courses)


@app.route("/course/<course_id>")
@login_required
def course(course_id):
    deg, crs = quiz.find_course(course_id)
    if not crs:
        abort(404)
    count = quiz.question_count(quiz.load_course(course_id))
    formula = (FORMULAS / f"{course_id}.pdf").exists()
    return render_template("course.html", degree=deg, course=crs, count=count, formula=formula)


@app.route("/course/<course_id>/quiz", methods=["GET", "POST"])
@login_required
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
    qids = ",".join(item["q"]["id"] for grp in groups for item in grp["questions"])
    return render_template("quiz.html", degree=deg, course=crs, groups=groups, qids=qids)


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True)
