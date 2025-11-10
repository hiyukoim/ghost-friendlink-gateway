from flask import Flask, request, redirect, jsonify, Response
import sqlite3, uuid, datetime, requests, os, jwt

app = Flask(__name__)

DB_PATH = "data/tokens.db"
GHOST_URL = os.getenv("GHOST_URL", "https://example.com")
GHOST_ADMIN_KEY = os.getenv("GHOST_ADMIN_KEY", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000")
DEFAULT_REDIRECT = os.getenv("DEFAULT_REDIRECT", f"{GHOST_URL}/#/portal/signup")

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
    conn.commit()


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


# --- Routes ---

@app.route("/generate/<slug>")
def generate(slug):
    ref = request.args.get("ref", "generic")
    token = str(uuid.uuid4())
    created = datetime.datetime.utcnow()
    expires = created + datetime.timedelta(days=30)  # friend link valid for 30 days

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO tokens (token, slug, referrer, created_at, expires_at, valid) VALUES (?, ?, ?, ?, ?, 1)",
            (token, slug, ref, created.isoformat(), expires.isoformat())
        )
        conn.commit()

    return jsonify({
        "slug": slug,
        "ref": ref,
        "token_url": f"{APP_BASE_URL}/read/{token}",
        "expires_at": expires.isoformat()
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
        row = conn.execute("SELECT slug, valid, expires_at FROM tokens WHERE token=?", (token,)).fetchone()

    # Check token existence & validity
    if not row or row[1] != 1:
        return redirect(DEFAULT_REDIRECT)

    slug, _, expires_at = row
    if datetime.datetime.utcnow() > datetime.datetime.fromisoformat(expires_at):
        return redirect(DEFAULT_REDIRECT)

    # Build signed JWT header
    jwt_token = make_ghost_admin_jwt()
    headers = {"Authorization": f"Ghost {jwt_token}"}

    # Fetch post HTML
    r = requests.get(ghost_api_url(slug), headers=headers)
    if r.status_code != 200:
        print("Ghost API error:", r.status_code, r.text[:300])
        return redirect(f"{GHOST_URL}/{slug}/")

    post_data = r.json()["posts"][0]
    html = post_data["html"]

    return Response(html, mimetype="text/html")


@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "usage": f"{APP_BASE_URL}/generate/<slug>?ref=fanbox",
        "ghost_url": GHOST_URL
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("APP_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
