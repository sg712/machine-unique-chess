"""Private first-party activity counts, with optional consenting browser histories.

Callers own transactions: no function commits or rolls back. Anonymous events
have no visitor, visit, or account link. The schema deliberately has no fields
for IP addresses, full user agents, URL queries, emails, or arbitrary metadata.
All SQL also works through the application's ``?``-to-Postgres adapter.
"""
from datetime import datetime, timezone
import ipaddress
import math
import re
import time
from urllib.parse import urlsplit


RETENTION_DAYS = 90
EVENT_NAMES = frozenset({
    "page_view", "practice_started", "test_started", "practice_answer",
    "test_completed", "study_completed", "registered", "login", "review_started", "study_opened",
})
DEVICE_CLASSES = frozenset({"desktop", "mobile", "tablet", "unknown"})
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ACCOUNT = re.compile(r"[A-Z0-9]{6}\Z")
_HOST = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_STATIC_PATHS = frozenset({
    "/", "/learn", "/research", "/test", "/register", "/login", "/claim",
    "/review", "/me", "/logout", "/privacy", "/api/answer", "/api/blindspot",
})

SCHEMA_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS analytics_meta (key TEXT PRIMARY KEY, at DOUBLE PRECISION NOT NULL)",
    """CREATE TABLE IF NOT EXISTS analytics_visitor (
        id TEXT PRIMARY KEY, first_at DOUBLE PRECISION NOT NULL,
        last_at DOUBLE PRECISION NOT NULL, excluded INTEGER NOT NULL DEFAULT 0
        CHECK (excluded IN (0, 1)))""",
    """CREATE TABLE IF NOT EXISTS analytics_event (
        id TEXT PRIMARY KEY, visitor_id TEXT, visit_id TEXT, account_code TEXT,
        at DOUBLE PRECISION NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
        concept INTEGER, correct INTEGER, n INTEGER,
        source_host TEXT NOT NULL DEFAULT '', device TEXT NOT NULL DEFAULT 'unknown',
        CHECK (visitor_id IS NOT NULL OR (visit_id IS NULL AND account_code IS NULL)))""",
    "CREATE INDEX IF NOT EXISTS analytics_event_at ON analytics_event(at)",
    "CREATE INDEX IF NOT EXISTS analytics_event_visitor_at ON analytics_event(visitor_id, at)",
    "CREATE INDEX IF NOT EXISTS analytics_event_account_at ON analytics_event(account_code, at)",
)


def _identifier(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def _timestamp(value):
    value = time.time() if value is None else value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid timestamp")
    if not math.isfinite(value) or value < 0 or value > 253402214400:
        raise ValueError("Invalid timestamp")
    return float(value)


def canonical_path(value):
    """Allow only known public page shapes; never preserve a query or token."""
    if not isinstance(value, str):
        raise ValueError("Invalid analytics path")
    if value in _STATIC_PATHS:
        return value
    match = re.fullmatch(r"/(?:pattern|concept)/(\d{1,2})(/drill|/studied)?", value)
    if match:
        return f"/pattern/{int(match[1])}{match[2] or ''}"
    raise ValueError("Invalid analytics path")


def source_host(value):
    """Reduce a browser referrer to a validated hostname; discard credentials/IPs.

    This is an ingress helper. ``insert_event`` accepts only its resulting
    hostname, never a raw referrer URL.
    """
    if not isinstance(value, str) or len(value) > 4096:
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            return ""
        return _source_host(parsed.hostname or "")
    except ValueError:
        return ""


def _source_host(value):
    if not isinstance(value, str):
        raise ValueError("Invalid source hostname")
    value = value.lower().rstrip(".")
    if not value:
        return ""
    if not _HOST.fullmatch(value):
        raise ValueError("Invalid source hostname")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError("Source must be a hostname, not an IP address")


def upsert_visitor(conn, visitor_id, at=None):
    """Remember only an opted-in random browser identifier and its activity dates."""
    visitor_id = _identifier(visitor_id, _HEX32, "visitor ID")
    at = _timestamp(at)
    conn.execute("""INSERT INTO analytics_visitor (id, first_at, last_at, excluded)
        VALUES (?, ?, ?, 0) ON CONFLICT(id) DO UPDATE SET
        first_at = CASE WHEN excluded.first_at < analytics_visitor.first_at
                        THEN excluded.first_at ELSE analytics_visitor.first_at END,
        last_at = CASE WHEN excluded.last_at > analytics_visitor.last_at
                       THEN excluded.last_at ELSE analytics_visitor.last_at END""",
                 (visitor_id, at, at))


def insert_event(conn, *, event_id, name, path, at=None, visitor_id=None,
                 visit_id=None, account_code=None, concept=None, correct=None,
                 n=None, source_host="", device="unknown"):
    """Insert a server-validated event once; return False for an already saved ID.

    IDs for real completions must derive from the existing durable action ID.
    The caller supplies authenticated account codes only after browser opt-in.
    Excluded browsers remain excluded when subsequent events arrive.
    """
    event_id = _identifier(event_id, _HEX64, "event ID")
    if not isinstance(name, str) or name not in EVENT_NAMES:
        raise ValueError("Invalid analytics event")
    path = canonical_path(path)
    at = _timestamp(at)
    if visitor_id is not None:
        _identifier(visitor_id, _HEX32, "visitor ID")
    elif visit_id is not None or account_code is not None:
        raise ValueError("Anonymous events cannot link a visit or account")
    if visit_id is not None:
        _identifier(visit_id, _HEX32, "visit ID")
    if account_code is not None:
        _identifier(account_code, _ACCOUNT, "account code")
    if not isinstance(device, str) or device not in DEVICE_CLASSES:
        raise ValueError("Invalid device class")
    source_host = _source_host(source_host)
    for label, value, minimum, maximum in (
        ("concept", concept, 0, 99), ("correct", correct, 0, 1000), ("n", n, 1, 1000),
    ):
        if value is not None and (type(value) is not int or not minimum <= value <= maximum):
            raise ValueError(f"Invalid {label}")
    if correct is not None and n is not None and correct > n:
        raise ValueError("Correct count cannot exceed the total")
    if name == "practice_answer" and correct is not None and correct not in (0, 1):
        raise ValueError("A practice answer has one correctness result")
    cursor = conn.execute("""INSERT INTO analytics_event
        (id, visitor_id, visit_id, account_code, at, name, path, concept, correct, n, source_host, device)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
        (event_id, visitor_id, visit_id, account_code, at, name, path,
         concept, correct, n, source_host, device))
    inserted = cursor.rowcount == 1
    if inserted and visitor_id is not None:
        upsert_visitor(conn, visitor_id, at)
    if inserted:
        conn.execute("""INSERT INTO analytics_meta (key, at) VALUES ('tracking_started', ?)
            ON CONFLICT(key) DO UPDATE SET at = CASE WHEN excluded.at < analytics_meta.at
            THEN excluded.at ELSE analytics_meta.at END""", (at,))
    return inserted


def set_visitor_excluded(conn, visitor_id, excluded):
    _identifier(visitor_id, _HEX32, "visitor ID")
    if type(excluded) is not bool:
        raise ValueError("Excluded must be a boolean")
    result = conn.execute("UPDATE analytics_visitor SET excluded = ? WHERE id = ?",
                          (int(excluded), visitor_id))
    return result.rowcount == 1


def _window(days, now):
    if type(days) is not int or not 1 <= days <= RETENTION_DAYS:
        raise ValueError("Date range must be between 1 and 90 days")
    now = _timestamp(now)
    start = max(0, math.floor(now / 86400) * 86400 - (days - 1) * 86400)
    return float(start), now


def _filter(start, end, exclude_accounts):
    accounts = tuple(exclude_accounts)
    if len(accounts) > 100:
        raise ValueError("Too many excluded accounts")
    for account in accounts:
        _identifier(account, _ACCOUNT, "excluded account code")
    condition = "e.at >= ? AND e.at <= ? AND COALESCE(v.excluded, 0) = 0"
    params = [start, end]
    if accounts:
        condition += " AND (e.account_code IS NULL OR e.account_code NOT IN (" + ",".join("?" for _ in accounts) + "))"
        params.extend(accounts)
    return condition, params


def _rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def dashboard_summary(conn, *, days=30, now=None, exclude_accounts=(), recent_limit=60):
    """Aggregate UTC calendar days ending now, excluding flagged browser IDs.

    A browser ID is a consenting browser, never a person. Returning browser IDs
    were first seen before this range or have multiple identified visits within
    it. Anonymous events contribute counts but never visits, IDs, or histories.
    Queries aggregate in the database; activity/visitor/group lists are bounded.
    """
    start, end = _window(days, now)
    if type(recent_limit) is not int or not 0 <= recent_limit <= 200:
        raise ValueError("Activity limit must be between 0 and 200")
    where, params = _filter(start, end, exclude_accounts)
    base = " FROM analytics_event e LEFT JOIN analytics_visitor v ON v.id = e.visitor_id WHERE " + where
    totals = dict(conn.execute("""SELECT COUNT(*) AS events,
        SUM(CASE WHEN e.name = 'page_view' THEN 1 ELSE 0 END) AS page_views,
        SUM(CASE WHEN e.name = 'page_view' AND e.visitor_id IS NULL THEN 1 ELSE 0 END) AS anonymous_page_views,
        COUNT(DISTINCT e.visitor_id) AS browser_ids,
        COUNT(DISTINCT e.visit_id) AS visits,
        SUM(CASE WHEN e.name = 'practice_started' THEN 1 ELSE 0 END) AS practice_started,
        SUM(CASE WHEN e.name = 'review_started' THEN 1 ELSE 0 END) AS reviews_started,
        SUM(CASE WHEN e.name = 'study_opened' THEN 1 ELSE 0 END) AS studies_opened,
        SUM(CASE WHEN e.name = 'practice_answer' THEN 1 ELSE 0 END) AS practice_answers,
        SUM(CASE WHEN e.name = 'practice_answer' THEN COALESCE(e.correct, 0) ELSE 0 END) AS practice_correct,
        SUM(CASE WHEN e.name = 'test_started' THEN 1 ELSE 0 END) AS tests_started,
        SUM(CASE WHEN e.name = 'test_completed' THEN 1 ELSE 0 END) AS tests_completed,
        SUM(CASE WHEN e.name = 'study_completed' THEN 1 ELSE 0 END) AS studies_completed,
        SUM(CASE WHEN e.name = 'registered' THEN 1 ELSE 0 END) AS registrations,
        SUM(CASE WHEN e.name = 'login' THEN 1 ELSE 0 END) AS logins""" + base, params).fetchone())
    totals = {key: int(value or 0) for key, value in totals.items()}
    returning = conn.execute("SELECT COUNT(*) AS n FROM (SELECT e.visitor_id" + base +
        " AND e.visitor_id IS NOT NULL GROUP BY e.visitor_id HAVING MIN(v.first_at) < ? OR COUNT(DISTINCT e.visit_id) > 1) returning_ids",
        [*params, start]).fetchone()
    totals["returning_browser_ids"] = int(returning["n"])
    daily_rows = _rows(conn, """SELECT CAST(FLOOR(e.at / 86400) AS INTEGER) AS day_number,
        COUNT(*) AS events, COUNT(DISTINCT e.visitor_id) AS browser_ids,
        COUNT(DISTINCT e.visit_id) AS visits,
        SUM(CASE WHEN e.name = 'page_view' THEN 1 ELSE 0 END) AS page_views,
        SUM(CASE WHEN e.name = 'practice_answer' THEN 1 ELSE 0 END) AS practice_answers,
        SUM(CASE WHEN e.name = 'test_completed' THEN 1 ELSE 0 END) AS tests_completed""" +
        base + " GROUP BY CAST(FLOOR(e.at / 86400) AS INTEGER) ORDER BY day_number", params)
    by_day = {int(row.pop("day_number")): row for row in daily_rows}
    daily = []
    for number in range(int(start // 86400), int(end // 86400) + 1):
        day = datetime.fromtimestamp(number * 86400, timezone.utc).strftime("%Y-%m-%d")
        daily.append({"day": day, **by_day.get(number, dict.fromkeys(
            ("events", "browser_ids", "visits", "page_views", "practice_answers", "tests_completed"), 0))})
    pages = _rows(conn, "SELECT e.path, COUNT(*) AS events, COUNT(DISTINCT e.visitor_id) AS browser_ids, "
        "SUM(CASE WHEN e.name = 'page_view' THEN 1 ELSE 0 END) AS page_views" + base +
        " GROUP BY e.path ORDER BY page_views DESC, events DESC, e.path LIMIT 50", params)
    sources = _rows(conn, "SELECT e.source_host, COUNT(*) AS events, "
        "SUM(CASE WHEN e.name = 'page_view' THEN 1 ELSE 0 END) AS page_views" + base +
        " GROUP BY e.source_host ORDER BY page_views DESC, events DESC, e.source_host LIMIT 50", params)
    devices = _rows(conn, "SELECT e.device, COUNT(*) AS events, "
        "SUM(CASE WHEN e.name = 'page_view' THEN 1 ELSE 0 END) AS page_views" + base +
        " GROUP BY e.device ORDER BY page_views DESC, events DESC, e.device LIMIT 4", params)
    events = _rows(conn, "SELECT e.name, COUNT(*) AS events, COUNT(DISTINCT e.visitor_id) AS browser_ids" +
        base + " GROUP BY e.name ORDER BY events DESC, e.name", params)
    visitors = _rows(conn, """SELECT e.visitor_id AS id, MIN(v.first_at) AS first_at,
        MAX(e.at) AS last_at, COUNT(*) AS events, COUNT(DISTINCT e.visit_id) AS visits,
        SUM(CASE WHEN e.name = 'page_view' THEN 1 ELSE 0 END) AS page_views,
        SUM(CASE WHEN e.name = 'practice_answer' THEN 1 ELSE 0 END) AS practice_answers,
        SUM(CASE WHEN e.name = 'test_completed' THEN 1 ELSE 0 END) AS tests_completed,
        MAX(e.account_code) AS account_code""" + base +
        " AND e.visitor_id IS NOT NULL GROUP BY e.visitor_id ORDER BY last_at DESC, e.visitor_id LIMIT 100", params)
    recent = _rows(conn, "SELECT e.*" + base + " ORDER BY e.at DESC, e.id DESC LIMIT ?", [*params, recent_limit])
    excluded = _rows(conn, "SELECT id, first_at, last_at, excluded FROM analytics_visitor WHERE excluded = 1 ORDER BY last_at DESC, id LIMIT 100")
    recorded_since = conn.execute("SELECT at FROM analytics_meta WHERE key = 'tracking_started'").fetchone()
    return {"days": days, "start_at": start, "end_at": end, "retention_days": RETENTION_DAYS,
            "recorded_since_at": recorded_since["at"] if recorded_since else None,
            "totals": totals, "daily": daily, "pages": pages, "sources": sources,
            "devices": devices, "events": events, "visitors": visitors,
            "recent_activity": recent, "excluded_visitors": excluded}


def visitor_timeline(conn, visitor_id, *, days=30, now=None, limit=100, exclude_accounts=()):
    _identifier(visitor_id, _HEX32, "visitor ID")
    if type(limit) is not int or not 0 <= limit <= 200:
        raise ValueError("Timeline limit must be between 0 and 200")
    start, end = _window(days, now)
    where, params = _filter(start, end, exclude_accounts)
    return _rows(conn, "SELECT e.* FROM analytics_event e LEFT JOIN analytics_visitor v ON v.id = e.visitor_id WHERE " +
                 where + " AND e.visitor_id = ? ORDER BY e.at DESC, e.id DESC LIMIT ?", [*params, visitor_id, limit])


def prune_retention(conn, *, now=None, retention_days=RETENTION_DAYS):
    """Remove analytics-only records older than 90 days, transaction-neutrally.

    Call on a bounded maintenance cadence (for example, once per owner dashboard
    day), rather than every public request. Functional progress is untouched.
    """
    if type(retention_days) is not int or not 1 <= retention_days <= RETENTION_DAYS:
        raise ValueError("Retention must be between 1 and 90 days")
    cutoff = _timestamp(now) - retention_days * 86400
    events = conn.execute("DELETE FROM analytics_event WHERE at < ?", (cutoff,)).rowcount
    visitors = conn.execute("""DELETE FROM analytics_visitor WHERE last_at < ?
        AND NOT EXISTS (SELECT 1 FROM analytics_event e WHERE e.visitor_id = analytics_visitor.id)""", (cutoff,)).rowcount
    return {"events_deleted": events, "visitors_deleted": visitors, "cutoff": cutoff}


def claim_retention_due(conn, now=None, interval_seconds=86400):
    """Atomically claim a cleanup interval; caller prunes and commits together."""
    now = _timestamp(now)
    if type(interval_seconds) is not int or not 3600 <= interval_seconds <= 7 * 86400:
        raise ValueError("Retention cadence must be between one hour and seven days")
    result = conn.execute("""INSERT INTO analytics_meta (key, at) VALUES ('retention_ran', ?)
        ON CONFLICT(key) DO UPDATE SET at = excluded.at
        WHERE analytics_meta.at <= excluded.at - ?""", (now, interval_seconds))
    return result.rowcount == 1
