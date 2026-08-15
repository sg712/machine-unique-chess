"""Study platform for the machine-unique chess experiment.

Participants get a resumable code, work through baseline -> study -> retest,
and every answer is stored as it happens. Aggregate results are computed across
all participants, which is what turns the n=1 protocol into a real sample.

    python webapp/app.py           # http://127.0.0.1:5000
"""
import json
import os
import pathlib
import re
import secrets
import sqlite3
import time

import chess
import chess.svg
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "webapp" / "study.db"
PHASES = ("baseline", "study", "retest")
CODE_RE = re.compile(r"^[A-Z0-9]{6}$")

app = Flask(__name__)
app.secret_key = "unnamed-concepts-local-dev"


# ── data ──────────────────────────────────────────────────────────────────────
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
    CREATE TABLE IF NOT EXISTS participant (
        code TEXT PRIMARY KEY, name TEXT, rating INTEGER,
        created_at REAL, study_done_at REAL);
    CREATE TABLE IF NOT EXISTS response (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL, phase TEXT NOT NULL, idx INTEGER NOT NULL,
        fen TEXT, picked TEXT, best TEXT, human_top TEXT,
        correct INTEGER, matched_human INTEGER, seconds REAL, created_at REAL,
        UNIQUE(code, phase, idx));
    CREATE INDEX IF NOT EXISTS resp_code ON response(code);
    """)
    conn.commit()
    conn.close()


def load_sets() -> dict:
    """Position sets: baseline/retest from the manifest, study from prototypes."""
    man = json.load(open(ROOT / "results" / "experiment" / "manifest.json"))
    pub = json.load(open(ROOT / "results" / "experiment" / "public_test.json"))
    pvs = json.load(open(ROOT / "results" / "experiment" / "study_pvs.json"))

    def clean(rows):
        out = []
        for r in rows:
            b = chess.Board(r["fen"])
            mv = chess.Move.from_uci(r["best"])
            if mv not in b.legal_moves:
                continue
            out.append({"fen": r["fen"], "best": r["best"],
                        "human_top": str(r.get("human_top") or ""),
                        "cost_cp": round(float(r.get("cost_cp") or 0))})
        return out

    baseline = clean(pub)                      # 8 public, depth-20 verified
    retest = clean(man["retest"])[:10]
    study = []
    for r in man["study"]:
        pv = pvs.get(r["fen"])
        if not pv or pv[0] != r["best"]:       # drop depth-unstable prototypes
            continue
        study.append({"fen": r["fen"], "pv": pv[:6]})
    return {"baseline": baseline, "study": study, "retest": retest}


SETS = load_sets()

# ── piece art (rendered once, embedded in the page) ───────────────────────────
def piece_svgs() -> dict:
    out = {}
    for sym in "KQRBNPkqrbnp":
        svg = chess.svg.piece(chess.Piece.from_symbol(sym))
        out[sym] = svg[svg.index(">", svg.index("<svg")) + 1: svg.rindex("</svg>")]
    return out


PIECES = piece_svgs()


# ── helpers ───────────────────────────────────────────────────────────────────
def board_payload(fen: str) -> dict:
    b = chess.Board(fen)
    return {
        "fen": fen,
        "orientation": "w" if b.turn else "b",
        "stm": "White" if b.turn else "Black",
        "legal": sorted(m.uci() for m in b.legal_moves),
        "check": b.is_check(),
    }


def line_payload(fen: str, pv: list) -> dict:
    """Board states and SAN for a principal variation, for the study phase."""
    b = chess.Board(fen)
    orient = "w" if b.turn else "b"
    frames, sans = [{"fen": b.fen(), "last": None}], []
    for uci in pv:
        mv = chess.Move.from_uci(uci)
        num, white = b.fullmove_number, b.turn
        sans.append(("%d." % num if white else "%d..." % num) + " " + b.san(mv))
        b.push(mv)
        frames.append({"fen": b.fen(), "last": uci})
    return {"orientation": orient, "frames": frames, "sans": sans}


def current(code: str) -> sqlite3.Row | None:
    return db().execute("SELECT * FROM participant WHERE code=?", (code,)).fetchone()


def done_count(code: str, phase: str) -> int:
    r = db().execute("SELECT COUNT(*) c FROM response WHERE code=? AND phase=?",
                     (code, phase)).fetchone()
    return r["c"]


def progress(code: str) -> dict:
    p = current(code)
    return {
        "baseline": done_count(code, "baseline"),
        "baseline_n": len(SETS["baseline"]),
        "study_done": bool(p and p["study_done_at"]),
        "retest": done_count(code, "retest"),
        "retest_n": len(SETS["retest"]),
    }


def require_code():
    code = session.get("code")
    return code if code and current(code) else None


# ── routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    code = require_code()
    return render_template("index.html", code=code,
                           prog=progress(code) if code else None,
                           n_baseline=len(SETS["baseline"]), n_retest=len(SETS["retest"]),
                           stats=aggregate())


@app.route("/join", methods=["GET", "POST"])
def join():
    if request.method == "POST":
        resume = (request.form.get("resume") or "").strip().upper()
        if resume:
            if not CODE_RE.match(resume) or not current(resume):
                return render_template("join.html", error="No study with that code.")
            session["code"] = resume
            return redirect(url_for("index"))
        code = secrets.token_hex(3).upper()
        rating = request.form.get("rating", "").strip()
        db().execute("INSERT INTO participant(code,name,rating,created_at) VALUES(?,?,?,?)",
                     (code, (request.form.get("name") or "").strip()[:40],
                      int(rating) if rating.isdigit() else None, time.time()))
        db().commit()
        session["code"] = code
        return redirect(url_for("index"))
    return render_template("join.html", error=None)


@app.route("/logout")
def logout():
    session.pop("code", None)
    return redirect(url_for("index"))


@app.route("/test/<phase>")
def test(phase):
    if phase not in ("baseline", "retest"):
        return redirect(url_for("index"))
    code = require_code()
    if not code:
        return redirect(url_for("join"))
    if phase == "retest" and not progress(code)["study_done"]:
        return redirect(url_for("index"))
    rows = SETS[phase]
    start = done_count(code, phase)
    if start >= len(rows):
        return redirect(url_for("results"))
    payload = [board_payload(r["fen"]) for r in rows]
    return render_template("test.html", phase=phase, start=start, n=len(rows),
                           positions=payload, pieces=PIECES)


@app.post("/answer")
def answer():
    code = require_code()
    if not code:
        return jsonify(error="no session"), 403
    d = request.get_json(force=True)
    phase, idx = d.get("phase"), int(d.get("idx", -1))
    if phase not in ("baseline", "retest") or not 0 <= idx < len(SETS[phase]):
        return jsonify(error="bad index"), 400
    row = SETS[phase][idx]
    picked = str(d.get("picked", ""))[:5]
    db().execute(
        """INSERT OR IGNORE INTO response
           (code,phase,idx,fen,picked,best,human_top,correct,matched_human,seconds,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (code, phase, idx, row["fen"], picked, row["best"], row["human_top"],
         int(picked == row["best"]), int(picked == row["human_top"]),
         float(d.get("seconds", 0)), time.time()))
    db().commit()
    return jsonify(ok=True, done=done_count(code, phase), of=len(SETS[phase]))


@app.route("/study")
def study():
    code = require_code()
    if not code:
        return redirect(url_for("join"))
    lines = [line_payload(r["fen"], r["pv"]) for r in SETS["study"]]
    return render_template("study.html", lines=lines, pieces=PIECES,
                           done=progress(code)["study_done"])


@app.post("/study/done")
def study_done():
    code = require_code()
    if code:
        db().execute("UPDATE participant SET study_done_at=? WHERE code=?", (time.time(), code))
        db().commit()
    return redirect(url_for("index"))


@app.route("/results")
def results():
    code = require_code()
    if not code:
        return redirect(url_for("join"))
    rows = db().execute("SELECT * FROM response WHERE code=? ORDER BY phase,idx", (code,)).fetchall()
    mine = {}
    for ph in ("baseline", "retest"):
        rs = [r for r in rows if r["phase"] == ph]
        if rs:
            mine[ph] = {
                "n": len(rs), "correct": sum(r["correct"] for r in rs),
                "matched": sum(r["matched_human"] for r in rs),
                "rows": [dict(r) for r in rs],
            }
    return render_template("results.html", mine=mine, stats=aggregate(),
                           prog=progress(code), code=code)


def aggregate() -> dict:
    conn = db()
    out = {}
    for ph in ("baseline", "retest"):
        r = conn.execute(
            """SELECT COUNT(DISTINCT code) p, COUNT(*) n, SUM(correct) c, SUM(matched_human) m
               FROM response WHERE phase=?""", (ph,)).fetchone()
        out[ph] = {"participants": r["p"] or 0, "answers": r["n"] or 0,
                   "correct": r["c"] or 0, "matched": r["m"] or 0,
                   "pct": round(100 * (r["c"] or 0) / r["n"], 1) if r["n"] else None,
                   "pct_human": round(100 * (r["m"] or 0) / r["n"], 1) if r["n"] else None}
    both = conn.execute(
        """SELECT code FROM response WHERE phase='baseline' GROUP BY code
           INTERSECT SELECT code FROM response WHERE phase='retest' GROUP BY code""").fetchall()
    out["completed"] = len(both)
    if both:
        codes = tuple(r["code"] for r in both)
        q = ("SELECT phase, AVG(correct)*100 p FROM response WHERE code IN (%s) "
             "AND phase IN ('baseline','retest') GROUP BY phase" % ",".join("?" * len(codes)))
        paired = {r["phase"]: round(r["p"], 1) for r in conn.execute(q, codes).fetchall()}
        out["paired"] = paired
        if "baseline" in paired and "retest" in paired:
            out["delta"] = round(paired["retest"] - paired["baseline"], 1)
    return out


@app.route("/paper")
def paper():
    return render_template("paper.html", stats=aggregate())


if __name__ == "__main__":
    init_db()
    app.run(debug=False, port=int(os.environ.get("PORT", 5055)))
