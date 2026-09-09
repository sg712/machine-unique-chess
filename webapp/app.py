"""Machine Unique Chess: practice engine moves assigned low probability by Maia.

Eight exploratory groups drawn from a corpus of 123,405 real positions.
Learning effectiveness and conceptual novelty have not been established.

    python webapp/app.py            # http://127.0.0.1:5055
"""
import json
import hashlib
import math
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
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = pathlib.Path(os.environ.get("DB_PATH", ROOT / "webapp" / "study.db"))
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row


class _PG:
    """Minimal adapter so the sqlite-style call sites work on Postgres:
    same execute/commit/close surface, '?' placeholders translated."""

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, params=()):
        return self._c.execute(sql.replace("?", "%s"), params)

    def commit(self):
        self._c.commit()

    def close(self):
        self._c.close()
CODE_RE = re.compile(r"^[A-Z0-9]{6}$")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "unnamed-concepts-local-dev")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=bool(os.environ.get("VERCEL")),
                  MAX_CONTENT_LENGTH=64 * 1024)

CONCEPTS = json.load(open(ROOT / "webapp" / "concepts.json"))
BY_ID = {c["id"]: c for c in CONCEPTS}
TEST_DATA = json.load(open(ROOT / "webapp" / "test_items.json"))
VALIDATION = {
    "cluster": json.load(open(ROOT / "results" / "18_validation.json")),
    "embed": json.load(open(ROOT / "results" / "19_embedding_value.json")),
    "difficulty": json.load(open(ROOT / "results" / "20_difficulty.json")),
    "curve": json.load(open(ROOT / "results" / "21_learning_curve.json")),
    "bands": json.load(open(ROOT / "results" / "23_band_value.json")),
    "audit": json.load(open(ROOT / "results" / "30_research_audit.json")),
    "embedding_audit": json.load(open(ROOT / "results" / "31_embedding_audit.json")),
    "contrast": json.load(open(ROOT / "results" / "26_why_invisible.json")),
}
RESEARCH_EXAMPLES = json.load(open(ROOT / "webapp" / "research_examples.json"))
MINING_V2 = json.load(open(ROOT / "results" / "mining_v2_summary.json"))


def _optional_result(name):
    path = ROOT / "results" / name
    return json.loads(path.read_text()) if path.exists() else None


MINING_V3_DATASET = _optional_result("mining_v3_dataset.json")
MINING_V3 = _optional_result("mining_v3_summary.json")
MINING_V3_PROVENANCE = _optional_result("mining_v3_provenance.json")
MINING_V3_DEEP200 = _optional_result("mining_v3_deep200.json")
STUDY_NOTES = {n["id"]: n for n in json.load(open(ROOT / "webapp" / "study_notes.json"))["items"]}


# ── storage ───────────────────────────────────────────────────────────────────
def db():
    if "db" not in g:
        if DATABASE_URL:
            g.db = _PG(psycopg.connect(DATABASE_URL, row_factory=dict_row))
            return g.db
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    if (conn := g.pop("db", None)) is not None:
        conn.close()


PG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS player (
        code TEXT PRIMARY KEY, name TEXT, rating INTEGER, created_at DOUBLE PRECISION);
    CREATE TABLE IF NOT EXISTS attempt (
        id SERIAL PRIMARY KEY,
        code TEXT NOT NULL, concept INTEGER NOT NULL, idx INTEGER NOT NULL,
        fen TEXT, picked TEXT, best TEXT, correct INTEGER,
        human_p DOUBLE PRECISION, seconds DOUBLE PRECISION, created_at DOUBLE PRECISION);
    CREATE TABLE IF NOT EXISTS studied (
        code TEXT NOT NULL, concept INTEGER NOT NULL, at DOUBLE PRECISION,
        PRIMARY KEY (code, concept));
    CREATE INDEX IF NOT EXISTS a_code ON attempt(code, concept);
    CREATE TABLE IF NOT EXISTS account (
        email TEXT PRIMARY KEY, pw_hash TEXT NOT NULL,
        code TEXT UNIQUE NOT NULL, created_at DOUBLE PRECISION);
    CREATE TABLE IF NOT EXISTS blindspot (
        id SERIAL PRIMARY KEY,
        code TEXT NOT NULL, at DOUBLE PRECISION, n INTEGER, correct INTEGER,
        band TEXT, detail TEXT);
"""


def init_db():
    if DATABASE_URL:
        conn = psycopg.connect(DATABASE_URL)
        for stmt in PG_SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.execute("""CREATE TABLE IF NOT EXISTS submission (
            id TEXT PRIMARY KEY, code TEXT NOT NULL, payload_hash TEXT NOT NULL,
            response TEXT NOT NULL)""")
        conn.commit()
        conn.close()
        return
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS submission (
        id TEXT PRIMARY KEY, code TEXT NOT NULL, payload_hash TEXT NOT NULL,
        response TEXT NOT NULL);
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
    CREATE TABLE IF NOT EXISTS blindspot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL, at REAL, n INTEGER, correct INTEGER,
        band TEXT, detail TEXT);
    """)
    conn.commit()
    conn.close()


def me():
    code = session.get("code")
    if not code:
        return None
    account = db().execute("SELECT email FROM account WHERE code=?", (code,)).fetchone()
    # A legacy recovery cookie proves possession of a code, not account ownership.
    if account and session.get("authenticated_code") != code:
        return None
    row = db().execute("SELECT * FROM player WHERE code=?", (code,)).fetchone()
    return code if row else None


def ensure_player() -> str:
    """Every visitor gets a player row on first action, no signup wall."""
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
    code = me()
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
        """SELECT concept, COUNT(DISTINCT idx) n,
           COUNT(DISTINCT CASE WHEN correct=1 THEN idx END) c FROM attempt
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


def study_line(note, key):
    # Keep the replay focused, including every move cited by the explanation.
    last_claim = max((claim["ply"] for claim in note.get("claims", [])
                      if claim["line"] == key), default=0)
    return frames_of(note["fen"], note[key]["pv"][:max(12, last_claim)])


# ── pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    code = me()
    previews = {c["id"]: {"fen": c["study"][0]["fen"],
                          "orientation": c["study"][0]["stm"],
                          "best": c["study"][0]["best"]} for c in CONCEPTS}
    rows = curriculum(code)
    nxt = next((r for r in rows if r["state"] != "done"), rows[0])
    featured = RESEARCH_EXAMPLES["examples"][0]["primary"]
    featured_board = chess.svg.board(chess.Board(featured["fen"]),
        orientation=chess.BLACK, size=360,
        colors={"square light": "#f2ece0", "square dark": "#b9906b"})
    return render_template("index.html", code=code, concepts=CONCEPTS, nxt=nxt,
                           prog=concept_progress(code), totals=totals(),
                           previews=previews, pieces=piece_svgs(),
                           featured=featured, featured_board=featured_board)


def curriculum(code=None):
    """Concepts ordered easiest-first by the difficulty model's predicted find-rate
    for a 1900, a measured ordering rather than the arbitrary cluster numbering."""
    prog = concept_progress(code)
    rows = []
    for c in CONCEPTS:
        pred = c["signature"].get("predicted_find_1900") or 0.1
        rows.append({"c": c, "pred": pred, "p": prog[c["id"]]})
    rows.sort(key=lambda r: -r["pred"])
    for i, r in enumerate(rows, start=1):
        p = r["p"]
        r["n"] = i
        r["tier"] = ("Standard" if r["pred"] >= 0.116
                     else "Harder" if r["pred"] >= 0.10 else "Hardest")
        r["pct"] = round(100 * p["n"] / max(p["of"], 1))
        r["state"] = ("done" if p["n"] >= p["of"] else
                      "going" if p["n"] > 0 else
                      "studied" if p["studied"] else "new")
    return rows


@app.route("/learn")
def learn():
    code = me()
    rows = curriculum(code)
    nxt = next((r for r in rows if r["state"] != "done"), None)
    tot = {"solved": sum(r["p"]["correct"] for r in rows),
           "tried": sum(r["p"]["n"] for r in rows),
           "of": sum(r["p"]["of"] for r in rows),
           "done": sum(1 for r in rows if r["state"] == "done"),
           "started": sum(1 for r in rows if r["state"] != "new")}
    return render_template("learn.html", rows=rows, nxt=nxt, tot=tot, code=code,
                           previews={r["c"]["id"]: {
                               "fen": r["c"]["study"][0]["fen"],
                               "orientation": r["c"]["study"][0]["stm"]} for r in rows},
                           pieces=PIECES)


@app.route("/pattern/<int:cid>")
def concept(cid):
    if cid not in BY_ID:
        return redirect(url_for("index"))
    c = BY_ID[cid]
    code = me()
    p = concept_progress(code)[cid]
    lines = []
    for index, st in enumerate(c["study"]):
        note = STUDY_NOTES[f"{cid}:{index}"]
        if (note["fen"], note["best"]) != (st["fen"], st["best"]):
            raise ValueError("Study explanation does not match the position")
        line = study_line(note, "engine")
        line["note"] = {key: note[key] for key in ("title", "why", "alternative", "notice")}
        line["comparison"] = study_line(note, "comparison")
        line["comparison"]["san"] = note["comparison"]["san"]
        line["variations"] = [{"label": v["label"], **frames_of(st["fen"], v["pv"])}
                              for v in note.get("variations", [])]
        line.update(board_of(st["fen"]))
        line["best"] = st["best"]
        line["best_san"] = st["best_san"]
        line["p_best"] = st.get("p_best", 0)
        lines.append(line)
    rows = curriculum(code)
    here = next((r for r in rows if r["c"]["id"] == cid), None)
    nxt = None
    if here:
        i = rows.index(here)
        nxt = rows[i + 1]["c"] if i + 1 < len(rows) else None
    return render_template("concept.html", c=c, lines=lines, pieces=PIECES,
                           prog=p, code=code, here=here, nxt=nxt)


@app.post("/pattern/<int:cid>/studied")
@app.post("/concept/<int:cid>/studied")
def mark_studied(cid):
    if cid not in BY_ID:
        return {"error": "Choose an existing pattern."}, 404
    code = ensure_player()
    if DATABASE_URL:
        db().execute("INSERT INTO studied(code, concept, at) VALUES(?,?,?) "
                     "ON CONFLICT (code, concept) DO UPDATE SET at = EXCLUDED.at",
                     (code, cid, time.time()))
    else:
        db().execute("INSERT OR REPLACE INTO studied(code, concept, at) VALUES(?,?,?)",
                     (code, cid, time.time()))
    db().commit()
    return redirect(url_for("drill", cid=cid))


@app.route("/concept/<int:cid>")
def concept_legacy(cid):
    return redirect(url_for("concept", cid=cid), 301)


@app.route("/concept/<int:cid>/drill")
def drill_legacy(cid):
    return redirect(url_for("drill", cid=cid), 301)


@app.route("/pattern/<int:cid>/drill")
def drill(cid):
    if cid not in BY_ID:
        return redirect(url_for("index"))
    c = BY_ID[cid]
    code = ensure_player()
    seen, solved = set(), set()
    if code:
        for r in db().execute("SELECT idx, MAX(correct) correct FROM attempt WHERE code=? AND concept=? GROUP BY idx",
                              (code, cid)).fetchall():
            seen.add(r["idx"])
            if r["correct"]:
                solved.add(r["idx"])
    mode = request.args.get("mode", "continue")
    if mode not in ("continue", "restart", "missed"):
        mode = "continue"
    order = list(range(len(c["drill"])))
    if mode == "missed":
        order = sorted(seen - solved)
    elif mode == "continue":
        order = [i for i in order if i not in seen]
    positions = [{**board_of(c["drill"][i]["fen"]), "idx": i} for i in order]
    return render_template("drill.html", c=c, positions=positions, pieces=PIECES,
                           mode=mode, code=code)


def legal_pick(fen, picked):
    if not isinstance(picked, str) or len(picked) not in (4, 5):
        return False
    try:
        return chess.Move.from_uci(picked) in chess.Board(fen).legal_moves
    except ValueError:
        return False


def reserve_submission(key, code, payload):
    """Reserve the write in the same transaction as its effects, so retries are safe."""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    inserted = db().execute(
        "INSERT INTO submission(id,code,payload_hash,response) VALUES(?,?,?,?) "
        "ON CONFLICT (id) DO NOTHING RETURNING id", (key, code, digest, "")).fetchone()
    if inserted:
        return None
    existing = db().execute("SELECT * FROM submission WHERE id=?", (key,)).fetchone()
    if existing["code"] != code or existing["payload_hash"] != digest:
        return jsonify(error="This answer was already saved differently. Reload to continue."), 409
    return jsonify(json.loads(existing["response"]))


def finish_submission(key, result):
    db().execute("UPDATE submission SET response=? WHERE id=?", (json.dumps(result), key))
    db().commit()
    return jsonify(result)


@app.post("/api/answer")
def api_answer():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify(error="Choose a move before saving your answer."), 400
    cid, idx = d.get("concept"), d.get("idx")
    if type(cid) is not int or type(idx) is not int or cid not in BY_ID or not 0 <= idx < len(BY_ID[cid]["drill"]):
        return jsonify(error="That position is unavailable. Reload to continue."), 400
    pos = BY_ID[cid]["drill"][idx]
    picked = d.get("picked")
    if not legal_pick(pos["fen"], picked):
        return jsonify(error="Choose a legal move on the board."), 400
    seconds = d.get("seconds", 0)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 86400:
        return jsonify(error="The answer time is invalid. Reload to continue."), 400
    key = d.get("request_id")
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9-]{32,36}", key):
        return jsonify(error="Reload this practice session before saving."), 400
    code = ensure_player()
    key = "drill:" + key
    cached = reserve_submission(key, code, {"concept": cid, "idx": idx, "picked": picked})
    if cached is not None:
        return cached
    b = chess.Board(pos["fen"])

    hp = next((h["p"] for h in pos["human"] if h["uci"] == picked), 0.0)
    correct = picked == pos["best"]
    db().execute(
        """INSERT INTO attempt(code,concept,idx,fen,picked,best,correct,human_p,seconds,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (code, cid, idx, pos["fen"], picked, pos["best"], int(correct), hp,
         seconds, time.time()))

    try:
        picked_san = b.san(chess.Move.from_uci(picked))
    except Exception:
        picked_san = picked
    result = dict(
        correct=correct, best=pos["best"], best_san=pos["best_san"],
        picked_san=picked_san, human_p=hp, p_best=pos["p_best"],
        model_move_cost_cp=pos["cost_cp"], gap_cp=pos["gap_cp"],
        predicted=pos.get("predicted_find_1900"),
        human=pos["human"][:3], line=frames_of(pos["fen"], pos["pv"]),
    )
    return finish_submission(key, result)


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
    bs = db().execute("SELECT * FROM blindspot WHERE code=? ORDER BY at DESC LIMIT 1",
                      (code,)).fetchone()
    return render_template("me.html", code=code, concepts=CONCEPTS, stats=stats,
                           tot=dict(tot), prog=concept_progress(code),
                           bs=dict(bs) if bs else None)


@app.route("/research")
def research():
    examples = []
    for example in RESEARCH_EXAMPLES["examples"]:
        item = dict(example)
        for key in ("primary", "related"):
            pos = dict(example[key])
            board = chess.Board(pos["fen"])
            pos["svg"] = chess.svg.board(board, orientation=board.turn,
                size=360, colors={"square light": "#f2ece0", "square dark": "#b9906b"})
            pos["stm"] = "White" if board.turn else "Black"
            pos["line"] = frames_of(pos["fen"], pos["pv"])
            pos["human_line"] = frames_of(pos["fen"], pos["human"]["pv"])
            item[key] = pos
        examples.append(item)
    return render_template("research.html", concepts=CONCEPTS, totals=totals(),
                           v=VALIDATION["cluster"], e=VALIDATION["embed"],
                           d=VALIDATION["difficulty"], lc=VALIDATION["curve"],
                           bv=VALIDATION["bands"], r=VALIDATION["audit"],
                           a=VALIDATION["embedding_audit"]["part_a"],
                           contrast=VALIDATION["contrast"], examples=examples, pieces=PIECES,
                           mining_v2=MINING_V2, mining_v3_dataset=MINING_V3_DATASET,
                           mining_v3=MINING_V3, mining_v3_provenance=MINING_V3_PROVENANCE,
                           mining_v3_deep200=MINING_V3_DEEP200)


def test_signer():
    return URLSafeTimedSerializer(app.secret_key, salt="blindspot-v2")


def read_test(token):
    try:
        data = test_signer().loads(token, max_age=7 * 86400)
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            return None
        keys = data.get("items")
        if not isinstance(keys, list) or len(keys) != 12 or len(set(keys)) != 12:
            return None
        if not all(k in TEST_DATA["items"] for k in keys):
            return None
        return data
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None


@app.route("/test")
def blindspot_test():
    import random
    token = request.args.get("attempt")
    if not token and request.args.get("new") != "1":
        return render_template("test_start.html", code=me(), error=None)
    if not token:
        cids = list(BY_ID)
        random.shuffle(cids)
        picks = cids + random.sample(cids, 4)
        keys = []
        for cid in picks:
            remaining = [f"{cid}:{i}" for i in range(len(BY_ID[cid]["drill"]))
                         if f"{cid}:{i}" not in keys]
            keys.append(random.choice(remaining))
        token = test_signer().dumps({"id": secrets.token_hex(16), "items": keys})
        return redirect(url_for("blindspot_test", attempt=token))
    attempt = read_test(token)
    if attempt is None:
        return render_template("test_start.html", code=me(),
                               error="This test link has expired or is invalid. Start a fresh test."), 400
    payload = []
    for key in attempt["items"]:
        cid, i = map(int, key.split(":"))
        payload.append(board_of(BY_ID[cid]["drill"][i]["fen"]))
    return render_template("test.html", items=payload, pieces=PIECES,
                           token=token, attempt_id=attempt["id"], code=ensure_player())


@app.post("/api/blindspot")
def api_blindspot():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {"error": "No test answers were received."}, 400
    attempt = read_test(data.get("attempt"))
    picks = data.get("picks")
    if attempt is None:
        return {"error": "This test link has expired. Start a fresh test."}, 400
    keys = attempt["items"]
    if not isinstance(picks, list) or len(picks) != len(keys):
        return {"error": "Answer all twelve positions before saving your result."}, 400
    for key, picked in zip(keys, picks):
        cid, i = map(int, key.split(":"))
        if not legal_pick(BY_ID[cid]["drill"][i]["fen"], picked):
            return {"error": "One answer is not a legal move. Return to that position and choose again."}, 400
    code = ensure_player()
    receipt = "test:" + attempt["id"]
    cached = reserve_submission(receipt, code, {"picks": picks})
    if cached is not None:
        return cached
    correct, reveal = 0, []
    loglik = [0.0] * len(TEST_DATA["band_labels"])
    for key, picked in zip(keys, picks):
        cid, i = map(int, key.split(":"))
        pos = BY_ID[cid]["drill"][i]
        hit = picked == pos["best"]
        correct += int(hit)
        b = chess.Board(pos["fen"])
        reveal.append({"fen": pos["fen"], "best_san": pos["best_san"],
                       "picked_san": b.san(chess.Move.from_uci(picked)), "hit": hit,
                       "picked": picked, "concept": BY_ID[cid]["label"], "cid": cid,
                       "line": frames_of(pos["fen"], pos["pv"])})
        for bi, pr in enumerate(TEST_DATA["items"][key]):
            pr = min(max(pr, 0.03), 0.97)
            loglik[bi] += math.log(pr if hit else 1.0 - pr)
    best_band = max(range(len(loglik)), key=lambda i: loglik[i])
    db().execute("INSERT INTO blindspot(code, at, n, correct, band, detail) VALUES(?,?,?,?,?,?)",
                 (code, time.time(), len(keys), correct,
                  TEST_DATA["band_labels"][best_band], json.dumps({"keys": keys, "picks": picks})))
    return finish_submission(receipt, {
        "n": len(keys), "correct": correct,
        "band": TEST_DATA["band_labels"][best_band], "band_idx": best_band,
        "band_labels": TEST_DATA["band_labels"], "staircase": TEST_DATA["staircase"],
        "reveal": reveal})


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
            error = "That email is already registered. Sign in instead."
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
            session["authenticated_code"] = code
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
            session["authenticated_code"] = row["code"]
            session.permanent = True
            return redirect(url_for("profile"))
        error = "Wrong email or password."
    return render_template("login.html", error=error, code=me())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/claim", methods=["GET", "POST"])
def claim():
    if request.method == "POST":
        resume = (request.form.get("resume") or "").strip().upper()
        if CODE_RE.match(resume) and db().execute(
                "SELECT 1 FROM player WHERE code=?", (resume,)).fetchone():
            if db().execute("SELECT 1 FROM account WHERE code=?", (resume,)).fetchone():
                return render_template("claim.html", code=me(),
                    error="This progress is linked to an email account. Sign in with your email and password."), 403
            session.pop("authenticated_code", None)
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
