"""Unnamed Concepts — a trainer for chess ideas that have no name.

Eight concepts mined from 123,405 real positions: patterns where a strong engine
is decisively right and essentially no human plays the move. Each concept is
studied by example, then drilled on fresh positions from the same family.

    python webapp/app.py            # http://127.0.0.1:5055
"""
import json
import os
import pathlib
import re
import secrets
import sqlite3
import time

import chess
from werkzeug.security import check_password_hash, generate_password_hash
import chess.svg
from flask import (Flask, g, jsonify, redirect, render_template, request,
                   session, url_for)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = pathlib.Path(os.environ.get("DB_PATH", ROOT / "webapp" / "study.db"))
CODE_RE = re.compile(r"^[A-Z0-9]{6}$")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "unnamed-concepts-local-dev")

CONCEPTS = json.load(open(ROOT / "webapp" / "concepts.json"))
BY_ID = {c["id"]: c for c in CONCEPTS}
VALIDATION = {
    "cluster": json.load(open(ROOT / "results" / "18_validation.json")),
    "embed": json.load(open(ROOT / "results" / "19_embedding_value.json")),
    "difficulty": json.load(open(ROOT / "results" / "20_difficulty.json")),
    "curve": json.load(open(ROOT / "results" / "21_learning_curve.json")),
    "bands": json.load(open(ROOT / "results" / "23_band_value.json")),
}


# ── storage ───────────────────────────────────────────────────────────────────
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    if (conn := g.pop("db", None)) is not None:
        conn.close()


def init_db():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS player (
        code TEXT PRIMARY KEY, name TEXT, rating INTEGER, created_at REAL);
    CREATE TABLE IF NOT EXISTS attempt (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL, concept INTEGER NOT NULL, idx INTEGER NOT NULL,
        fen TEXT, picked TEXT, best TEXT, correct INTEGER,
        human_p REAL, seconds REAL, created_at REAL);
    CREATE TABLE IF NOT EXISTS studied (
        code TEXT NOT NULL, concept INTEGER NOT NULL, at REAL,
        PRIMARY KEY (code, concept));
    CREATE INDEX IF NOT EXISTS a_code ON attempt(code, concept);
    CREATE TABLE IF NOT EXISTS account (
        email TEXT PRIMARY KEY, pw_hash TEXT NOT NULL,
        code TEXT UNIQUE NOT NULL, created_at REAL);
    """)
    conn.commit()
    conn.close()


def me():
    code = session.get("code")
    if not code:
        return None
    row = db().execute("SELECT * FROM player WHERE code=?", (code,)).fetchone()
    return code if row else None


def ensure_player() -> str:
    """Every visitor gets a player row on first action — no signup wall."""
    code = me()
    if code:
        return code
    code = secrets.token_hex(3).upper()
    db().execute("INSERT INTO player(code, created_at) VALUES(?,?)", (code, time.time()))
    db().commit()
    session["code"] = code
    session.permanent = True
    return code


def current_email():
    code = session.get("code")
    if not code:
        return None
    row = db().execute("SELECT email FROM account WHERE code=?", (code,)).fetchone()
    return row["email"] if row else None


@app.context_processor
def inject_account():
    return {"email": current_email()}


def concept_progress(code: str) -> dict:
    """Per-concept: studied?, drills attempted, drills correct."""
    out = {}
    if not code:
        return {c["id"]: {"studied": False, "n": 0, "correct": 0, "of": len(c["drill"])}
                for c in CONCEPTS}
    st = {r["concept"] for r in db().execute("SELECT concept FROM studied WHERE code=?", (code,))}
    rows = db().execute(
        """SELECT concept, COUNT(DISTINCT idx) n, SUM(correct) c FROM attempt
           WHERE code=? GROUP BY concept""", (code,)).fetchall()
    agg = {r["concept"]: (r["n"], r["c"] or 0) for r in rows}
    for c in CONCEPTS:
        n, corr = agg.get(c["id"], (0, 0))
        out[c["id"]] = {"studied": c["id"] in st, "n": n, "correct": corr,
                        "of": len(c["drill"])}
    return out


def piece_svgs() -> dict:
    out = {}
    for sym in "KQRBNPkqrbnp":
        svg = chess.svg.piece(chess.Piece.from_symbol(sym))
        out[sym] = svg[svg.index(">", svg.index("<svg")) + 1:svg.rindex("</svg>")]
    return out


PIECES = piece_svgs()


def board_of(fen: str) -> dict:
    b = chess.Board(fen)
    return {"fen": fen, "orientation": "w" if b.turn else "b",
            "stm": "White" if b.turn else "Black",
            "legal": sorted(m.uci() for m in b.legal_moves)}


def frames_of(fen: str, pv: list) -> dict:
    b = chess.Board(fen)
    out = {"orientation": "w" if b.turn else "b",
           "frames": [{"fen": b.fen(), "last": None}], "sans": []}
    for step in pv:
        mv = chess.Move.from_uci(step["uci"])
        out["sans"].append(step["san"])
        b.push(mv)
        out["frames"].append({"fen": b.fen(), "last": step["uci"]})
    return out


# ── pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    code = me()
    previews = {c["id"]: {"fen": c["study"][0]["fen"],
                          "orientation": c["study"][0]["stm"],
                          "best": c["study"][0]["best"]} for c in CONCEPTS}
    blurbs = {}
    for c in CONCEPTS:
        sig = c["signature"]
        phase = max(sig["phase"], key=sig["phase"].get)
        piece = max(sig["pieces"], key=sig["pieces"].get)
        quiet = "quiet " if sig["quiet_share"] >= 0.75 else ""
        blurbs[c["id"]] = f"Mostly {phase}s; the answer is usually a {quiet}{piece} move."
    return render_template("index.html", code=code, concepts=CONCEPTS,
                           prog=concept_progress(code), totals=totals(),
                           previews=previews, pieces=piece_svgs(), blurbs=blurbs)


@app.route("/concept/<int:cid>")
def concept(cid):
    if cid not in BY_ID:
        return redirect(url_for("index"))
    c = BY_ID[cid]
    code = me()
    p = concept_progress(code)[cid]
    lines = []
    for st in c["study"]:
        line = frames_of(st["fen"], st["pv"])
        line.update(board_of(st["fen"]))
        line["best"] = st["best"]
        line["best_san"] = st["best_san"]
        line["p_best"] = st.get("p_best", 0)
        lines.append(line)
    return render_template("concept.html", c=c, lines=lines, pieces=PIECES,
                           prog=p, code=code)


@app.post("/concept/<int:cid>/studied")
def mark_studied(cid):
    code = ensure_player()
    db().execute("INSERT OR REPLACE INTO studied(code, concept, at) VALUES(?,?,?)",
                 (code, cid, time.time()))
    db().commit()
    return redirect(url_for("drill", cid=cid))


@app.route("/concept/<int:cid>/drill")
def drill(cid):
    if cid not in BY_ID:
        return redirect(url_for("index"))
    c = BY_ID[cid]
    code = me()
    done = 0
    if code:
        r = db().execute("SELECT COUNT(DISTINCT idx) n FROM attempt WHERE code=? AND concept=?",
                         (code, cid)).fetchone()
        done = r["n"]
    positions = []
    for i, d in enumerate(c["drill"]):
        positions.append({**board_of(d["fen"]), "idx": i})
    return render_template("drill.html", c=c, positions=positions, pieces=PIECES,
                           start=min(done, len(positions) - 1), code=code)


@app.post("/api/answer")
def api_answer():
    code = ensure_player()
    d = request.get_json(force=True)
    cid, idx = int(d.get("concept", -1)), int(d.get("idx", -1))
    if cid not in BY_ID or not 0 <= idx < len(BY_ID[cid]["drill"]):
        return jsonify(error="bad position"), 400
    pos = BY_ID[cid]["drill"][idx]
    picked = str(d.get("picked", ""))[:5]
    b = chess.Board(pos["fen"])

    hp = next((h["p"] for h in pos["human"] if h["uci"] == picked), 0.0)
    correct = picked == pos["best"]
    db().execute(
        """INSERT INTO attempt(code,concept,idx,fen,picked,best,correct,human_p,seconds,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (code, cid, idx, pos["fen"], picked, pos["best"], int(correct), hp,
         float(d.get("seconds", 0)), time.time()))
    db().commit()

    try:
        picked_san = b.san(chess.Move.from_uci(picked))
    except Exception:
        picked_san = picked
    return jsonify(
        correct=correct, best=pos["best"], best_san=pos["best_san"],
        picked_san=picked_san, human_p=hp, p_best=pos["p_best"],
        cost_cp=pos["cost_cp"], gap_cp=pos["gap_cp"],
        predicted=pos.get("predicted_find_1900"),
        human=pos["human"][:3], line=frames_of(pos["fen"], pos["pv"]),
    )


@app.route("/me")
def profile():
    code = me()
    if not code:
        return redirect(url_for("index"))
    rows = db().execute(
        """SELECT concept, COUNT(*) tries, COUNT(DISTINCT idx) seen, SUM(correct) hits,
                  AVG(human_p) avg_human FROM attempt WHERE code=? GROUP BY concept""",
        (code,)).fetchall()
    stats = {r["concept"]: dict(r) for r in rows}
    tot = db().execute(
        "SELECT COUNT(*) n, SUM(correct) c, AVG(human_p) h FROM attempt WHERE code=?",
        (code,)).fetchone()
    return render_template("me.html", code=code, concepts=CONCEPTS, stats=stats,
                           tot=dict(tot), prog=concept_progress(code))


@app.route("/research")
def research():
    return render_template("research.html", concepts=CONCEPTS, totals=totals(),
                           v=VALIDATION["cluster"], e=VALIDATION["embed"],
                           d=VALIDATION["difficulty"], lc=VALIDATION["curve"],
                           bv=VALIDATION["bands"])


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        if "@" not in email or "." not in email.split("@")[-1]:
            error = "That doesn't look like an email address."
        elif len(pw) < 8:
            error = "Password needs at least 8 characters."
        elif db().execute("SELECT 1 FROM account WHERE email=?", (email,)).fetchone():
            error = "That email is already registered — sign in instead."
        else:
            code = ensure_player()
            # if this browser's progress already belongs to another account,
            # start the new account on a fresh slate instead of stealing it
            if db().execute("SELECT 1 FROM account WHERE code=?", (code,)).fetchone():
                code = secrets.token_hex(3).upper()
                db().execute("INSERT INTO player(code, created_at) VALUES(?,?)",
                             (code, time.time()))
                session["code"] = code
            db().execute("INSERT INTO account(email, pw_hash, code, created_at) VALUES(?,?,?,?)",
                         (email, generate_password_hash(pw), code, time.time()))
            db().commit()
            session.permanent = True
            return redirect(url_for("profile"))
    return render_template("register.html", error=error, code=me())


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        row = db().execute("SELECT * FROM account WHERE email=?", (email,)).fetchone()
        if row and check_password_hash(row["pw_hash"], pw):
            session["code"] = row["code"]
            session.permanent = True
            return redirect(url_for("profile"))
        error = "Wrong email or password."
    return render_template("login.html", error=error, code=me())


@app.route("/logout")
def logout():
    session.pop("code", None)
    return redirect(url_for("index"))


@app.route("/claim", methods=["GET", "POST"])
def claim():
    if request.method == "POST":
        resume = (request.form.get("resume") or "").strip().upper()
        if CODE_RE.match(resume) and db().execute(
                "SELECT 1 FROM player WHERE code=?", (resume,)).fetchone():
            session["code"] = resume
            session.permanent = True
            return redirect(url_for("profile"))
        return render_template("claim.html", error="No player with that code.", code=me())
    return render_template("claim.html", error=None, code=me())


def totals() -> dict:
    r = db().execute("SELECT COUNT(*) n, SUM(correct) c FROM attempt").fetchone()
    p = db().execute("SELECT COUNT(*) n FROM player").fetchone()
    return {"attempts": r["n"] or 0, "correct": r["c"] or 0, "players": p["n"] or 0,
            "pct": round(100 * (r["c"] or 0) / r["n"], 1) if r["n"] else None,
            "positions": sum(len(c["drill"]) + len(c["study"]) for c in CONCEPTS)}


# Under gunicorn there is no __main__, so the schema has to be created at import
# time or the first request hits a missing table.
init_db()

if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5055)))
