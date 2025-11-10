from flask import Flask, request, redirect, jsonify, Response, render_template, url_for
import sqlite3, uuid, datetime, requests, os, jwt, csv, io
from urllib.parse import urlparse
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(
    __name__,
    static_folder=os.path.join("templates", "assets"),
    static_url_path="/assets",
)
APP_UI_FOLDER = os.path.join(app.root_path, "app_ui")
if os.path.isdir(APP_UI_FOLDER):
    app.jinja_loader.searchpath.append(APP_UI_FOLDER)
limiter = Limiter(get_remote_address, app=app, default_limits=[])

DB_PATH = "data/tokens.db"
GHOST_URL = os.getenv("GHOST_URL", "https://example.com")
GHOST_ADMIN_KEY = os.getenv("GHOST_ADMIN_KEY", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")
DEFAULT_REDIRECT = os.getenv("DEFAULT_REDIRECT", f"{GHOST_URL}/#/portal/signup")
CUSTOM_CSS_URL = os.getenv("CUSTOM_CSS_URL", "").strip()
SITE_TITLE = os.getenv("SITE_TITLE", "").strip()
SITE_DESCRIPTION = os.getenv("SITE_DESCRIPTION", "").strip()
SITE_ICON_URL = os.getenv("SITE_ICON_URL", "").strip()
SITE_LOGO_URL = os.getenv("SITE_LOGO_URL", "").strip()
TOKEN_EXPIRY_DAYS = int(os.getenv("TOKEN_EXPIRY_DAYS", "0"))  # Default: no expiration. Set to N for N-day default.
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()
ACCESS_LOG_RETENTION_DAYS = int(os.getenv("ACCESS_LOG_RETENTION_DAYS", "60"))  # 60-day retention by default. 0 disables logging, negative keeps forever.
BASIC_AUTH_USERNAME = os.getenv("BASIC_AUTH_USERNAME", "admin").strip()
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", ADMIN_API_KEY or "admin").strip()
DEFAULT_RATE_LIMIT = os.getenv("DEFAULT_RATE_LIMIT", "240/hour")
ADMIN_RATE_LIMIT = os.getenv("ADMIN_RATE_LIMIT", "60/minute")
GENERATE_RATE_LIMIT = os.getenv("GENERATE_RATE_LIMIT", "20/minute")
ENFORCE_HTTPS = os.getenv("ENFORCE_HTTPS", "true").lower() == "true"
PROXY_FORWARDED_FOR = int(os.getenv("PROXY_FORWARDED_FOR", "1"))
PROXY_FORWARDED_PROTO = int(os.getenv("PROXY_FORWARDED_PROTO", "1"))

if DEFAULT_RATE_LIMIT:
    limiter.default_limits = [DEFAULT_RATE_LIMIT]

if PROXY_FORWARDED_FOR or PROXY_FORWARDED_PROTO:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=PROXY_FORWARDED_FOR,
        x_proto=PROXY_FORWARDED_PROTO
    )

os.makedirs("data", exist_ok=True)

# Initialize SQLite database
with sqlite3.connect(DB_PATH) as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            slug TEXT,
            referrer TEXT,
            created_at TEXT,
            expires_at TEXT,
            valid INTEGER
        )
    """)
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "referrer_posts" not in tables and "referrer_slugs" in tables:
        try:
            conn.execute("ALTER TABLE referrer_slugs RENAME TO referrer_posts")
            tables.add("referrer_posts")
        except Exception:
            pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS allowed_referrers (
            referrer TEXT PRIMARY KEY,
            created_at TEXT,
            active INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrer_posts (
            referrer TEXT,
            slug TEXT,
            active INTEGER,
            created_at TEXT,
            PRIMARY KEY (referrer, slug),
            FOREIGN KEY (referrer) REFERENCES allowed_referrers(referrer)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT,
            referrer TEXT,
            ip_address TEXT,
            user_agent TEXT,
            accessed_at TEXT,
            referer_domain TEXT,
            FOREIGN KEY (token) REFERENCES tokens(token)
        )
    """)
    conn.commit()
    
    # Ensure referer_domain column exists for older databases
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(access_logs)").fetchall()
    }
    if "referer_domain" not in columns:
        conn.execute("ALTER TABLE access_logs ADD COLUMN referer_domain TEXT")
        conn.commit()
    
    if ACCESS_LOG_RETENTION_DAYS > 0:
        enforce_access_log_retention(conn)


# --- JWT Authentication for Ghost Admin API ---
def make_ghost_admin_jwt():
    """Generate a signed JWT for Ghost Admin API authentication."""
    key_id, secret = GHOST_ADMIN_KEY.split(':')
    iat = int(datetime.datetime.utcnow().timestamp())
    exp = iat + 5 * 60  # token valid for 5 minutes
    header = {'alg': 'HS256', 'kid': key_id}
    payload = {'iat': iat, 'exp': exp, 'aud': '/v5/admin/'}
    token = jwt.encode(payload, bytes.fromhex(secret), algorithm='HS256', headers=header)
    return token


def ghost_api_url(slug):
    return f"{GHOST_URL}/ghost/api/admin/posts/slug/{slug}/?formats=html"


def get_ghost_site_settings():
    """Fetch site settings from Ghost Content API (public, no auth needed)."""
    site_info = {
        'title': SITE_TITLE,
        'description': SITE_DESCRIPTION,
        'icon': SITE_ICON_URL,
        'logo': SITE_LOGO_URL,
    }
    
    # Try to fetch from Ghost Content API (fill missing values only)
    try:
        settings_url = f"{GHOST_URL}/ghost/api/content/settings/"
        r = requests.get(settings_url, timeout=3)
        if r.status_code == 200:
            settings = r.json().get('settings', {})
            site_info['title'] = site_info['title'] or settings.get('title', '')
            site_info['description'] = site_info['description'] or settings.get('description', '')
            site_info['icon'] = site_info['icon'] or settings.get('icon', '')
            site_info['logo'] = site_info['logo'] or settings.get('logo', '')
    except:
        # Silently fail - we'll use defaults
        pass
    
    return site_info


def check_admin_auth():
    """Check if request has valid admin API key."""
    if not ADMIN_API_KEY:
        return True  # No auth required if ADMIN_API_KEY not set
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        provided_key = auth_header[7:]
        return provided_key == ADMIN_API_KEY
    auth = request.authorization
    if auth and auth.type and auth.type.lower() == "basic":
        if BASIC_AUTH_USERNAME and auth.username == BASIC_AUTH_USERNAME and auth.password == BASIC_AUTH_PASSWORD:
            return True
    return False


def enforce_basic_auth():
    """Apply HTTP Basic auth when username/password are configured."""
    if not BASIC_AUTH_USERNAME or not BASIC_AUTH_PASSWORD:
        return None
    auth = request.authorization
    if auth and auth.type and auth.type.lower() == "basic":
        if auth.username == BASIC_AUTH_USERNAME and auth.password == BASIC_AUTH_PASSWORD:
            return None
    return Response(
        "Unauthorized",
        401,
        {"WWW-Authenticate": 'Basic realm="FriendLink Admin"'}
    )


@app.before_request
def enforce_https_requirement():
    if not ENFORCE_HTTPS:
        return
    proto = request.headers.get("X-Forwarded-Proto")
    if request.is_secure or proto == "https":
        return
    if request.path.startswith('/health'):
        return
    return jsonify({"error": "HTTPS is required"}), 400


def is_referrer_allowed(ref):
    """Check if referrer is in allowed_referrers table and active."""
    if not ref:
        return False
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT active FROM allowed_referrers WHERE referrer = ?",
            (ref,)
        ).fetchone()
        return row is not None and row[0] == 1


def is_post_allowed_for_ref(ref, slug):
    """Ensure referrer is allowed to access a specific Ghost post (by slug)."""
    if not ref or not slug:
        return False
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT active FROM referrer_posts WHERE referrer = ? AND slug = ?",
            (ref, slug)
        ).fetchone()
        return row is not None and row[0] == 1


def enforce_access_log_retention(conn, days=None):
    """Delete access log rows older than the retention window."""
    retention_days = ACCESS_LOG_RETENTION_DAYS if days is None else days
    if retention_days is None or retention_days <= 0:
        return 0
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)).isoformat()
    cursor = conn.execute(
        "DELETE FROM access_logs WHERE accessed_at < ?",
        (cutoff,)
    )
    conn.commit()
    return cursor.rowcount


def extract_referer_domain(raw_referer):
    """Return normalized domain (without scheme/path) from Referer header."""
    if not raw_referer:
        return None
    try:
        parsed = urlparse(raw_referer)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def daterange(start_date, end_date):
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max)
    return start_dt, end_dt


def get_preset_range(name):
    """Return (since, until) datetimes for named presets."""
    if not name:
        return None
    today = datetime.datetime.utcnow().date()
    name = name.lower()
    if name == "today":
        return daterange(today, today)
    if name == "yesterday":
        y = today - datetime.timedelta(days=1)
        return daterange(y, y)
    if name == "this_week":
        start = today - datetime.timedelta(days=today.weekday())
        return daterange(start, today)
    if name == "last_week":
        start = today - datetime.timedelta(days=today.weekday() + 7)
        end = start + datetime.timedelta(days=6)
        return daterange(start, end)
    if name == "this_month":
        start = today.replace(day=1)
        return daterange(start, today)
    if name == "last_month":
        this_month_start = today.replace(day=1)
        last_month_end = this_month_start - datetime.timedelta(days=1)
        start = last_month_end.replace(day=1)
        return daterange(start, last_month_end)
    if name == "this_year":
        start = datetime.date(today.year, 1, 1)
        return daterange(start, today)
    if name == "last_year":
        year = today.year - 1
        start = datetime.date(year, 1, 1)
        end = datetime.date(year, 12, 31)
        return daterange(start, end)
    return None


def parse_iso8601(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except Exception:
        return None


def fetch_access_logs(limit=100, offset=0, ref=None, token=None, since=None, until=None, order="desc"):
    """Retrieve access logs with optional filters."""
    clauses = []
    params = []
    if ref:
        clauses.append("referrer = ?")
        params.append(ref)
    if token:
        clauses.append("token = ?")
        params.append(token)
    if since:
        clauses.append("accessed_at >= ?")
        params.append(since.isoformat())
    if until:
        clauses.append("accessed_at <= ?")
        params.append(until.isoformat())
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    direction = "ASC" if order.lower() == "asc" else "DESC"
    limit = max(1, min(int(limit or 100), 1000))
    offset = max(0, int(offset or 0))
    query = f"""
        SELECT id, token, referrer, referer_domain, ip_address, user_agent, accessed_at
        FROM access_logs
        {where_sql}
        ORDER BY accessed_at {direction}, id {direction}
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": row[0],
            "token": row[1],
            "referrer": row[2],
            "referer_domain": row[3],
            "ip_address": row[4],
            "user_agent": row[5],
            "accessed_at": row[6]
        }
        for row in rows
    ]


# --- Routes ---

@app.route("/generate/<slug>")
@limiter.limit(GENERATE_RATE_LIMIT)
def generate(slug):
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    ref = request.args.get("ref")
    
    if not ref:
        return jsonify({"error": "ref parameter is required"}), 400

    if not is_referrer_allowed(ref):
        return jsonify({"error": "Referrer not allowed"}), 403
    
    if ref and not is_post_allowed_for_ref(ref, slug):
        return jsonify({"error": "Slug not allowed for this referrer"}), 403
    
    token = str(uuid.uuid4())
    created = datetime.datetime.utcnow()
    
    # Check for per-link expiration parameters
    expires_days_param = request.args.get("expires_days")
    expires_at_param = request.args.get("expires_at")
    
    if expires_at_param:
        # Absolute date format: YYYY-MM-DD
        try:
            expires = datetime.datetime.fromisoformat(expires_at_param)
            expires_iso = expires.isoformat()
        except:
            return jsonify({"error": "Invalid expires_at format. Use YYYY-MM-DD"}), 400
    elif expires_days_param:
        # Relative days
        try:
            days = int(expires_days_param)
            if days == 0:
                expires = None
                expires_iso = None
            else:
                expires = created + datetime.timedelta(days=days)
                expires_iso = expires.isoformat()
        except:
            return jsonify({"error": "Invalid expires_days format. Must be a number"}), 400
    elif TOKEN_EXPIRY_DAYS == 0:
        # Use default: no expiration
        expires = None
        expires_iso = None
    else:
        # Use default TOKEN_EXPIRY_DAYS
        expires = created + datetime.timedelta(days=TOKEN_EXPIRY_DAYS)
        expires_iso = expires.isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO tokens (token, slug, referrer, created_at, expires_at, valid) VALUES (?, ?, ?, ?, ?, 1)",
            (token, slug, ref, created.isoformat(), expires_iso)
        )
        conn.commit()

    return jsonify({
        "slug": slug,
        "ref": ref,
        "token_url": f"{APP_BASE_URL}/read/{token}",
        "expires_at": expires_iso or "Never"
    })


@app.route("/revoke/<token>", methods=["POST"])
def revoke(token):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE tokens SET valid=0 WHERE token=?", (token,))
        conn.commit()
    return jsonify({"status": "revoked", "token": token})


@app.route("/read/<token>")
def read(token):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT slug, referrer, valid, expires_at FROM tokens WHERE token=?", (token,)).fetchone()

    # Check token existence & validity
    if not row or row[2] != 1:
        return redirect(DEFAULT_REDIRECT)

    slug, ref, _, expires_at = row
    # Check expiration only if expires_at is not None (0 means no expiration)
    if expires_at and datetime.datetime.utcnow() > datetime.datetime.fromisoformat(expires_at):
        return redirect(DEFAULT_REDIRECT)
    
    if not ref or not is_referrer_allowed(ref):
        return redirect(DEFAULT_REDIRECT)
    
    if ref and not is_post_allowed_for_ref(ref, slug):
        return redirect(DEFAULT_REDIRECT)
    
    # Log access (unless logging disabled)
    if ACCESS_LOG_RETENTION_DAYS != 0:
        ip_address = request.remote_addr
        user_agent = request.headers.get("User-Agent", "")
        referer_domain = extract_referer_domain(request.headers.get("Referer"))
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO access_logs (token, referrer, ip_address, user_agent, accessed_at, referer_domain) VALUES (?, ?, ?, ?, ?, ?)",
                (token, ref, ip_address, user_agent, datetime.datetime.utcnow().isoformat(), referer_domain)
            )
            conn.commit()
            if ACCESS_LOG_RETENTION_DAYS > 0:
                enforce_access_log_retention(conn)

    # Build signed JWT header
    jwt_token = make_ghost_admin_jwt()
    headers = {"Authorization": f"Ghost {jwt_token}"}

    # Fetch post HTML
    r = requests.get(ghost_api_url(slug), headers=headers)
    if r.status_code != 200:
        print("Ghost API error:", r.status_code, r.text[:300])
        return redirect(f"{GHOST_URL}/{slug}/")

    post_data = r.json()["posts"][0]
    
    # Get site settings
    site = get_ghost_site_settings()
    
    # CSS: custom CSS if provided, otherwise use default
    custom_css = CUSTOM_CSS_URL if CUSTOM_CSS_URL else None
    
    return render_template('post.html',
                         post=post_data,
                         site=site,
                         ghost_url=GHOST_URL,
                         custom_css_url=custom_css,
                         ref=ref)


# --- Admin API Endpoints ---

@app.route("/admin/referrers", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def list_referrers():
    """List all allowed referrers."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT referrer, created_at, active FROM allowed_referrers ORDER BY created_at DESC"
        ).fetchall()
    
    referrers = [
        {
            "referrer": row[0],
            "created_at": row[1],
            "active": bool(row[2])
        }
        for row in rows
    ]
    return jsonify({"referrers": referrers})


@app.route("/admin/referrers", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def add_referrer():
    """Add an allowed referrer."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    if not data or "referrer" not in data:
        return jsonify({"error": "referrer field is required"}), 400
    
    ref = data["referrer"].strip()
    if not ref:
        return jsonify({"error": "referrer cannot be empty"}), 400
    
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO allowed_referrers (referrer, created_at, active) VALUES (?, ?, 1)",
                (ref, datetime.datetime.utcnow().isoformat())
            )
            conn.commit()
        return jsonify({"status": "added", "referrer": ref}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/referrers/<referrer>", methods=["DELETE"])
@limiter.limit(ADMIN_RATE_LIMIT)
def delete_referrer(referrer):
    """Revoke (deactivate) a referrer."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE allowed_referrers SET active = 0 WHERE referrer = ?",
            (referrer,)
        )
        conn.commit()
    
    return jsonify({"status": "revoked", "referrer": referrer})


@app.route("/admin/referrers/slugs", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def list_referrer_posts():
    """List allowed posts (by slug) for a referrer."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    ref = request.args.get("ref")
    if not ref:
        return jsonify({"error": "ref parameter is required"}), 400
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT slug, active, created_at FROM referrer_posts WHERE referrer = ? ORDER BY slug",
            (ref,)
        ).fetchall()
    return jsonify({
        "referrer": ref,
        "slugs": [
            {"slug": row[0], "active": bool(row[1]), "created_at": row[2]}
            for row in rows
        ]
    })


@app.route("/admin/referrers/slugs", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def add_referrer_post():
    """Allow a referrer to access a specific post slug."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    ref = (data.get("referrer") or "").strip()
    slug = (data.get("slug") or "").strip()
    if not ref or not slug:
        return jsonify({"error": "referrer and slug are required"}), 400
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT active FROM allowed_referrers WHERE referrer = ?",
            (ref,)
        ).fetchone()
        if row is None:
            return jsonify({"error": "Referrer not found"}), 404
        if row[0] != 1:
            return jsonify({"error": "Referrer inactive"}), 400
        conn.execute(
            "INSERT OR REPLACE INTO referrer_posts (referrer, slug, active, created_at) VALUES (?, ?, 1, ?)",
            (ref, slug, datetime.datetime.utcnow().isoformat())
        )
        conn.commit()
    return jsonify({"status": "added", "referrer": ref, "slug": slug}), 201


@app.route("/admin/referrers/slugs/<referrer>/<slug>", methods=["DELETE"])
@limiter.limit(ADMIN_RATE_LIMIT)
def delete_referrer_post(referrer, slug):
    """Deactivate a referrer/post pairing."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE referrer_posts SET active = 0 WHERE referrer = ? AND slug = ?",
            (referrer, slug)
        )
        conn.commit()
    return jsonify({"status": "revoked", "referrer": referrer, "slug": slug})


@app.route("/admin/stats", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def get_referrer_stats():
    """Get access statistics for a referrer."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    ref = request.args.get("ref")
    if not ref:
        return jsonify({"error": "ref parameter is required"}), 400
    
    with sqlite3.connect(DB_PATH) as conn:
        # Get total access count
        total_count = conn.execute(
            "SELECT COUNT(*) FROM access_logs WHERE referrer = ?",
            (ref,)
        ).fetchone()[0]
        
        # Get unique IP count
        unique_ips = conn.execute(
            "SELECT COUNT(DISTINCT ip_address) FROM access_logs WHERE referrer = ?",
            (ref,)
        ).fetchone()[0]
        
        # Get recent accesses (last 10)
        recent = conn.execute(
            "SELECT token, ip_address, user_agent, accessed_at, referer_domain FROM access_logs WHERE referrer = ? ORDER BY accessed_at DESC LIMIT 10",
            (ref,)
        ).fetchall()
        
        # Get associated tokens
        tokens = conn.execute(
            "SELECT token, slug, created_at, expires_at, valid FROM tokens WHERE referrer = ? ORDER BY created_at DESC",
            (ref,)
        ).fetchall()
    
    return jsonify({
        "referrer": ref,
        "total_accesses": total_count,
        "unique_ips": unique_ips,
        "recent_accesses": [
            {
                "token": row[0],
                "ip_address": row[1],
                "user_agent": row[2],
                "accessed_at": row[3],
                "referer_domain": row[4]
            }
            for row in recent
        ],
        "tokens": [
            {
                "token": row[0],
                "slug": row[1],
                "created_at": row[2],
                "expires_at": row[3],
                "valid": bool(row[4])
            }
            for row in tokens
        ]
    })


@app.route("/admin/access-logs", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def list_access_logs_api():
    """List raw access log entries for automation tools."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    ref = request.args.get("ref")
    token = request.args.get("token")
    order = request.args.get("order", "desc")
    limit = request.args.get("limit", 100)
    offset = request.args.get("offset", 0)
    
    preset_name = request.args.get("preset")
    since_str = request.args.get("since")
    until_str = request.args.get("until")
    since = parse_iso8601(since_str)
    until = parse_iso8601(until_str)
    if since_str and not since:
        return jsonify({"error": "Invalid since timestamp. Use ISO 8601 (e.g., 2025-01-30T12:00:00)"}), 400
    if until_str and not until:
        return jsonify({"error": "Invalid until timestamp. Use ISO 8601 (e.g., 2025-01-30T12:00:00)"}), 400
    if preset_name:
        preset_range = get_preset_range(preset_name)
        if not preset_range:
            return jsonify({"error": "Unknown preset. Supported values: today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year"}), 400
        preset_since, preset_until = preset_range
        if not since:
            since = preset_since
        if not until:
            until = preset_until
    
    logs = fetch_access_logs(limit=limit, offset=offset, ref=ref, token=token, since=since, until=until, order=order)
    return jsonify({
        "count": len(logs),
        "logs": logs
    })


@app.route("/admin/access-logs.csv", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def export_access_logs_csv():
    """Download access logs as CSV."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    ref = request.args.get("ref")
    token = request.args.get("token")
    order = request.args.get("order", "desc")
    limit = request.args.get("limit", 1000)  # higher default for exports
    offset = request.args.get("offset", 0)
    preset_name = request.args.get("preset")
    since_str = request.args.get("since")
    until_str = request.args.get("until")
    since = parse_iso8601(since_str)
    until = parse_iso8601(until_str)
    if since_str and not since:
        return jsonify({"error": "Invalid since timestamp. Use ISO 8601 (e.g., 2025-01-30T12:00:00)"}), 400
    if until_str and not until:
        return jsonify({"error": "Invalid until timestamp. Use ISO 8601 (e.g., 2025-01-30T12:00:00)"}), 400
    if preset_name:
        preset_range = get_preset_range(preset_name)
        if not preset_range:
            return jsonify({"error": "Unknown preset. Supported values: today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year"}), 400
        preset_since, preset_until = preset_range
        if not since:
            since = preset_since
        if not until:
            until = preset_until
    
    logs = fetch_access_logs(limit=limit, offset=offset, ref=ref, token=token, since=since, until=until, order=order)
    
    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "token", "referrer", "referer_domain", "ip_address", "user_agent", "accessed_at"])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for entry in logs:
            writer.writerow([
                entry["id"],
                entry["token"],
                entry["referrer"],
                entry.get("referer_domain") or "",
                entry["ip_address"],
                entry["user_agent"],
                entry["accessed_at"]
            ])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    
    filename = f"access-logs-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return Response(generate(), mimetype="text/csv", headers=headers)


@app.route("/admin/access-logs/cleanup", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def cleanup_access_logs():
    """Trigger access log cleanup (manual flush or custom retention)."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    payload = request.get_json(silent=True) or {}
    delete_all = bool(payload.get("delete_all"))
    older_than_days = payload.get("older_than_days")
    
    with sqlite3.connect(DB_PATH) as conn:
        if delete_all:
            cursor = conn.execute("DELETE FROM access_logs")
            conn.commit()
            deleted = cursor.rowcount if cursor.rowcount != -1 else conn.total_changes
            conn.execute("VACUUM")
            conn.commit()
            return jsonify({"status": "deleted_all", "deleted_rows": deleted})
        
        if older_than_days is not None:
            try:
                custom_days = int(older_than_days)
            except ValueError:
                return jsonify({"error": "older_than_days must be a number"}), 400
            if custom_days <= 0:
                return jsonify({"error": "older_than_days must be greater than 0"}), 400
            deleted = enforce_access_log_retention(conn, days=custom_days)
            return jsonify({"status": "custom_cleanup", "deleted_rows": deleted, "days": custom_days})
        
        deleted = enforce_access_log_retention(conn)
        return jsonify({"status": "retention_cleanup", "deleted_rows": deleted, "days": max(ACCESS_LOG_RETENTION_DAYS, 0)})


@app.route("/admin/dashboard", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def admin_dashboard():
    """Simple HTML dashboard showing referrers and recent tokens."""
    basic_auth_response = enforce_basic_auth()
    if basic_auth_response:
        return basic_auth_response
    
    with sqlite3.connect(DB_PATH) as conn:
        ref_rows = conn.execute(
            "SELECT referrer, created_at, active FROM allowed_referrers ORDER BY created_at DESC"
        ).fetchall()
        post_rows = conn.execute(
            "SELECT slug, referrer, created_at FROM referrer_posts WHERE active = 1 ORDER BY created_at DESC"
        ).fetchall()
        token_rows = conn.execute(
            "SELECT token, slug, referrer, created_at, expires_at, valid FROM tokens ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    
    post_map = {}
    for slug, ref, created_at in post_rows:
        entry = post_map.setdefault(slug, {
            "slug": slug,
            "referrers": [],
            "last_assigned": created_at
        })
        entry["referrers"].append({
            "referrer": ref,
            "created_at": created_at
        })
        if created_at and (entry["last_assigned"] is None or created_at > entry["last_assigned"]):
            entry["last_assigned"] = created_at
    
    posts = sorted(
        post_map.values(),
        key=lambda item: item["last_assigned"] or "",
        reverse=True
    )
    
    site = get_ghost_site_settings()
    return render_template(
        "app_ui/dashboard.html",
        site=site,
        posts=posts,
        referrers=[
            {
                "referrer": row[0],
                "created_at": row[1],
                "active": bool(row[2])
            }
            for row in ref_rows
        ],
        tokens=[
            {
                "token": row[0],
                "slug": row[1],
                "referrer": row[2],
                "created_at": row[3],
                "expires_at": row[4],
                "valid": bool(row[5])
            }
            for row in token_rows
        ],
        ghost_url=GHOST_URL,
    )


@app.route("/admin/stats/token/<token>", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def get_token_stats(token):
    """Get access statistics for a specific token."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    with sqlite3.connect(DB_PATH) as conn:
        # Get token info
        token_row = conn.execute(
            "SELECT slug, referrer, created_at, expires_at, valid FROM tokens WHERE token = ?",
            (token,)
        ).fetchone()
        
        if not token_row:
            return jsonify({"error": "Token not found"}), 404
        
        # Get access logs
        logs = conn.execute(
            "SELECT ip_address, user_agent, accessed_at, referer_domain FROM access_logs WHERE token = ? ORDER BY accessed_at DESC",
            (token,)
        ).fetchall()
    
    return jsonify({
        "token": token,
        "slug": token_row[0],
        "referrer": token_row[1],
        "created_at": token_row[2],
        "expires_at": token_row[3],
        "valid": bool(token_row[4]),
        "access_count": len(logs),
        "accesses": [
            {
                "ip_address": row[0],
                "user_agent": row[1],
                "accessed_at": row[2],
                "referer_domain": row[3]
            }
            for row in logs
        ]
    })


@app.route("/admin/tokens", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def list_tokens():
    """List all tokens for a referrer."""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    ref = request.args.get("ref")
    if not ref:
        return jsonify({"error": "ref parameter is required"}), 400
    
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT token, slug, created_at, expires_at, valid FROM tokens WHERE referrer = ? ORDER BY created_at DESC",
            (ref,)
        ).fetchall()
    
    tokens = [
        {
            "token": row[0],
            "slug": row[1],
            "created_at": row[2],
            "expires_at": row[3],
            "valid": bool(row[4])
        }
        for row in rows
    ]
    return jsonify({"tokens": tokens})


@app.route("/")
def index():
    return render_template("app_ui/index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("APP_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
