"""First-party analytics ingress and an independently authenticated owner view.

Only successful application writes enqueue completion events. Optional analytics
uses a separate connection so a measurement failure cannot undo saved progress.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
import time

from flask import g, jsonify, redirect, render_template, request, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import site_analytics as store

OWNER_SCHEMA = """CREATE TABLE IF NOT EXISTS analytics_owner_session (
    token_hash TEXT PRIMARY KEY, key_version TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL)"""
USAGE_COOKIE = "muc_usage"
OWNER_COOKIE = "muc_owner"
COOKIE_DAYS = 90
VISIT_IDLE_SECONDS = 1800
OWNER_SECONDS = 12 * 3600
HEX32 = re.compile(r"[a-f0-9]{32}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
BOT = re.compile(r"bot|spider|crawler|headless|curl|wget|python|lighthouse|slurp|monitor|preview", re.I)
PUBLIC_PAGES = {
    "index": "home", "learn": "learn", "research": "research",
    "concept": "study", "drill": "practice", "review": "review",
    "blindspot_test": "test", "profile": "account", "register": "account",
    "login": "account", "claim": "account", "privacy": "privacy",
}
STARTS = {"practice": "practice_started", "review": "review_started",
          "test": "test_started", "study": "study_opened"}


def queue_activity(name, path, *, identity=None, **values):
    """Called only after the app commits a new successful action, never recovery."""
    g.analytics_completion = {"name": name, "path": path,
                              "identity": identity or secrets.token_hex(32), **values}


def install_analytics(app, *, connect, actor, config_path, secure, origin_matches):
    app.config["ANALYTICS_OWNER_KEY_SHA256"] = json.loads(config_path.read_text())["access_key_sha256"]
    app.config["ANALYTICS_SECURE_COOKIE"] = secure

    @contextmanager
    def connection():
        conn = connect()
        try:
            yield conn
        finally:
            conn.close()

    def signer(salt):
        return URLSafeTimedSerializer(app.secret_key, salt=salt)

    def usage():
        if hasattr(g, "analytics_usage"):
            return g.analytics_usage
        value = {}
        try:
            saved = signer("usage-preference-v1").loads(request.cookies.get(USAGE_COOKIE, ""), max_age=COOKIE_DAYS * 86400)
            if isinstance(saved, dict):
                value = saved
        except (BadSignature, SignatureExpired, TypeError, ValueError):
            pass
        clean = {"consent": value.get("consent") if value.get("consent") in ("yes", "no") else "unset",
                 "excluded": value.get("excluded") is True, "owner": value.get("owner") is True}
        if clean["consent"] == "yes" and HEX32.fullmatch(str(value.get("visitor", ""))):
            clean["visitor"] = value["visitor"]
            if HEX32.fullmatch(str(value.get("visit", ""))):
                clean["visit"] = value["visit"]
            seen = value.get("seen")
            if type(seen) in (int, float) and 0 <= seen <= time.time() + 60:
                clean["seen"] = seen
        if request.headers.get("Sec-GPC") == "1" or request.headers.get("DNT") == "1":
            clean = {"consent": "no", "excluded": clean["excluded"], "owner": clean["owner"]}
            g.analytics_usage_dirty = True
        g.analytics_usage = clean
        return clean

    def bot_request():
        ua = request.headers.get("User-Agent", "")
        return not ua or bool(BOT.search(ua)) or request.headers.get("Purpose") == "prefetch" or request.headers.get("Sec-Purpose", "").startswith("prefetch")

    def device():
        ua = request.headers.get("User-Agent", "").lower()
        if "ipad" in ua or "tablet" in ua:
            return "tablet"
        if "mobile" in ua or "iphone" in ua or "android" in ua:
            return "mobile"
        return "desktop" if ua else "unknown"

    def source():
        host = store.source_host(request.referrer or "")
        return "" if host == request.host.split(":")[0].lower() else host

    def linked_identity(consent_allowed=True):
        pref = usage()
        if pref["consent"] != "yes" or not consent_allowed:
            return {}
        now = time.time()
        pref.setdefault("visitor", secrets.token_hex(16))
        if not pref.get("visit") or now - pref.get("seen", 0) >= VISIT_IDLE_SECONDS:
            pref["visit"] = secrets.token_hex(16)
        pref["seen"] = now
        g.analytics_usage_dirty = True
        return {"visitor_id": pref["visitor"], "visit_id": pref["visit"], "account_code": actor()}

    def emit(events, *, consent_allowed=True):
        if usage()["excluded"] or usage()["owner"] or bot_request():
            return False
        try:
            links = linked_identity(consent_allowed)
            with connection() as conn:
                if store.claim_retention_due(conn):
                    store.prune_retention(conn)
                    conn.execute("DELETE FROM analytics_owner_session WHERE expires_at < ?", (time.time(),))
                for event in events:
                    store.insert_event(conn, **event, **links)
                conn.commit()
            return True
        except Exception as exc:
            # Do not log tokens, request data, database URLs, or SQL arguments.
            app.logger.warning("analytics_write_failed:%s", type(exc).__name__)
            return False

    def page_context():
        if request.endpoint not in PUBLIC_PAGES:
            return None
        pref = usage()
        # Flask's integer routes also accept /pattern/0001. Use their canonical
        # URL so optional measurement never breaks an otherwise valid page.
        path = store.canonical_path(url_for(request.endpoint, **(request.view_args or {})))
        payload = {"nonce": secrets.token_hex(16), "path": path,
                   "kind": PUBLIC_PAGES[request.endpoint],
                   "concept": (request.view_args or {}).get("cid"),
                   "source_host": source(), "device": device()}
        return {"page_token": signer("usage-page-v1").dumps(payload),
                "consent": pref["consent"], "excluded": pref["excluded"] or pref["owner"] or bot_request(),
                "path": path, "kind": payload["kind"], "concept": payload["concept"]}

    @app.context_processor
    def analytics_template_context():
        if not hasattr(g, "analytics_context"):
            g.analytics_context = page_context()
        return {"analytics_context": g.analytics_context}

    def read_page(data):
        if not isinstance(data, dict) or not isinstance(data.get("page_token"), str) or len(data["page_token"]) > 4096:
            raise ValueError("Invalid page token")
        payload = signer("usage-page-v1").loads(data["page_token"], max_age=1800)
        if not isinstance(payload, dict) or not HEX32.fullmatch(str(payload.get("nonce", ""))):
            raise ValueError("Invalid page token")
        store.canonical_path(payload["path"])
        if payload["kind"] not in set(PUBLIC_PAGES.values()):
            raise ValueError("Invalid page kind")
        return payload

    @app.post("/api/analytics/page")
    def analytics_page():
        data = request.get_json(silent=True)
        try:
            page = read_page(data)
        except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
            return jsonify(error="Reload this page to record its visit."), 400
        names = ["page_view"] + ([STARTS[page["kind"]]] if page["kind"] in STARTS else [])
        events = [{"event_id": hashlib.sha256((page["nonce"] + ":" + name).encode()).hexdigest(),
                   "name": name, "path": page["path"], "concept": page["concept"],
                   "source_host": page["source_host"], "device": page["device"]} for name in names]
        emit(events, consent_allowed=data.get("visitor_consent") is True)
        return "", 204

    def change_preference(data):
        evidence = request.headers.get("Origin") or request.headers.get("Referer")
        if not evidence or not origin_matches(evidence):
            raise ValueError("Use a same-origin privacy form")
        read_page(data)
        choice = data.get("choice")
        if choice not in ("yes", "no", "exclude", "include"):
            raise ValueError("Invalid choice")
        pref = usage()
        owner = pref["owner"]
        if choice == "exclude" and pref.get("visitor"):
            with connection() as conn:
                store.set_visitor_excluded(conn, pref["visitor"], True)
                conn.commit()
        excluded = True if owner or choice == "exclude" else False if choice in ("yes", "include") else pref["excluded"]
        consent = "yes" if choice == "yes" else "no"
        if request.headers.get("Sec-GPC") == "1" or request.headers.get("DNT") == "1":
            consent = "no"
        new = {"consent": consent, "excluded": excluded, "owner": owner}
        if consent == "yes" and not excluded and pref.get("visitor"):
            new.update({key: pref[key] for key in ("visitor", "visit", "seen") if key in pref})
        elif consent == "yes" and not excluded:
            # Allocate once on opt-in, before concurrent page/action requests.
            new.update(visitor=secrets.token_hex(16), visit=secrets.token_hex(16), seen=time.time())
        g.analytics_usage = new
        g.analytics_usage_dirty = True
        return {"consent": consent, "excluded": excluded}

    @app.post("/api/analytics/preference")
    def analytics_preference():
        try:
            return jsonify(change_preference(request.get_json(silent=True)))
        except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
            return jsonify(error="Reload the page and try again."), 400

    @app.post("/analytics/preference")
    def analytics_preference_form():
        try:
            change_preference(request.form.to_dict())
        except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError):
            return "Reload the privacy page and try again.", 400
        return redirect(url_for("privacy"))

    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html", code=None)

    def owner_key_hash():
        value = app.config.get("ANALYTICS_OWNER_KEY_SHA256", "")
        return value if isinstance(value, str) and HEX64.fullmatch(value) else ""

    def owner_session():
        token = request.cookies.get(OWNER_COOKIE, "")
        if not HEX64.fullmatch(token) or not owner_key_hash():
            return None
        with connection() as conn:
            row = conn.execute("SELECT token_hash FROM analytics_owner_session WHERE token_hash = ? AND key_version = ? AND expires_at > ?",
                               (hashlib.sha256(token.encode()).hexdigest(), owner_key_hash(), time.time())).fetchone()
        return token if row else None

    def csrf(token):
        return hmac.new(token.encode(), b"analytics-owner-write-v1", hashlib.sha256).hexdigest()

    def check_owner_write():
        token = owner_session()
        supplied = request.form.get("csrf_token", "")
        return token if token and isinstance(supplied, str) and hmac.compare_digest(csrf(token), supplied) else None

    @app.template_filter("analytics_utc")
    def analytics_utc(value):
        return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M") if value is not None else "—"

    @app.route("/owner/login", methods=["GET", "POST"])
    def analytics_owner_login():
        error = None
        if request.method == "POST":
            key = request.form.get("access_key", "")
            expected = owner_key_hash()
            if not expected or not isinstance(key, str) or len(key) > 256 or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), expected):
                error = "That access key did not match."
            else:
                token = secrets.token_hex(32)
                pref = usage()
                with connection() as conn:
                    if pref.get("visitor"):
                        store.set_visitor_excluded(conn, pref["visitor"], True)
                    conn.execute("INSERT INTO analytics_owner_session (token_hash, key_version, expires_at) VALUES (?, ?, ?)",
                                 (hashlib.sha256(token.encode()).hexdigest(), expected, time.time() + OWNER_SECONDS))
                    conn.commit()
                g.analytics_usage = {"consent": "no", "excluded": True, "owner": True}
                g.analytics_usage_dirty = True
                response = redirect(url_for("analytics_owner_dashboard"))
                response.set_cookie(OWNER_COOKIE, token, max_age=OWNER_SECONDS, httponly=True,
                                    secure=app.config["ANALYTICS_SECURE_COOKIE"], samesite="Strict", path="/owner")
                return response
        return render_template("analytics_login.html", error=error, csrf_token=None), 403 if error else 200

    @app.get("/owner/analytics")
    def analytics_owner_dashboard():
        token = owner_session()
        if not token:
            return redirect(url_for("analytics_owner_login"))
        days = 7 if request.args.get("days") == "7" else 30
        visitor = request.args.get("visitor", "")
        selected_visitor = visitor if HEX32.fullmatch(visitor) else None
        with connection() as conn:
            summary = store.dashboard_summary(conn, days=days)
            if selected_visitor:
                summary["recent_activity"] = store.visitor_timeline(conn, selected_visitor, days=days)
        return render_template("analytics.html", summary=summary, csrf_token=csrf(token), message=None,
                               owner_browser_excluded=True, selected_visitor=selected_visitor)

    @app.post("/owner/analytics/exclude")
    def analytics_owner_exclude():
        if not check_owner_write():
            return "Owner sign-in and a fresh form are required.", 403
        visitor = request.form.get("visitor_id", "")
        excluded = request.form.get("excluded")
        if not HEX32.fullmatch(visitor) or excluded not in ("0", "1"):
            return "Choose an existing visitor.", 400
        with connection() as conn:
            store.set_visitor_excluded(conn, visitor, excluded == "1")
            conn.commit()
        return redirect(url_for("analytics_owner_dashboard", days=7 if request.form.get("days") == "7" else 30))

    @app.post("/owner/logout")
    def analytics_owner_logout():
        token = check_owner_write()
        if not token:
            return "Owner sign-in and a fresh form are required.", 403
        with connection() as conn:
            conn.execute("DELETE FROM analytics_owner_session WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
            conn.commit()
        pref = usage()
        pref["owner"] = False
        g.analytics_usage_dirty = True
        response = redirect(url_for("analytics_owner_login"))
        response.delete_cookie(OWNER_COOKIE, path="/owner", secure=app.config["ANALYTICS_SECURE_COOKIE"], httponly=True, samesite="Strict")
        return response

    @app.after_request
    def analytics_after_request(response):
        event = getattr(g, "analytics_completion", None)
        if event and 200 <= response.status_code < 400:
            event = dict(event)
            identity = event.pop("identity")
            event.update(event_id=hmac.new(app.secret_key.encode(), (event["name"] + ":" + identity).encode(), hashlib.sha256).hexdigest(),
                         source_host=source(), device=device())
            emit([event])
        if getattr(g, "analytics_usage_dirty", False):
            response.set_cookie(USAGE_COOKIE, signer("usage-preference-v1").dumps(usage()),
                                max_age=COOKIE_DAYS * 86400, httponly=True, secure=app.config["ANALYTICS_SECURE_COOKIE"],
                                samesite="Lax")
        if request.endpoint in PUBLIC_PAGES or request.path.startswith(("/api/analytics/", "/analytics/", "/owner/")):
            # Preserve stricter responses already supplied by the write guard.
            if not response.cache_control.no_store:
                response.headers["Cache-Control"] = "private, no-store"
        if request.path.startswith("/owner/"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response
