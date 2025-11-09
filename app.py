from flask import Flask, request, redirect, jsonify, Response
import sqlite3, uuid, datetime, requests, os

app = Flask(__name__)

DB_PATH = "data/tokens.db"
GHOST_URL = os.getenv("GHOST_URL", "https://example.com")
GHOST_ADMIN_KEY = os.getenv("GHOST_ADMIN_KEY", "")
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
            valid INTEGER
        )
    """)
    conn.commit()

def ghost_api_url(slug):
    return f"{GHOST_URL}/ghost/api/admin/posts/slug/{slug}/?formats=html"

@app.route("/generate/<slug>")
def generate(slug):
    ref = request.args.get("ref", "generic")
    token = str(uuid.uuid4())
    created = datetime.datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO tokens (token, slug, referrer, created_at, valid) VALUES (?, ?, ?, ?, 1)",
            (token, slug, ref, created)
        )
        conn.commit()
    return jsonify({
        "slug": slug,
        "ref": ref,
        "token_url": f"{APP_BASE_URL}/read/{token}"
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
        row = conn.execute("SELECT slug, valid FROM tokens WHERE token=?", (token,)).fetchone()
    if not row or row[1] != 1:
        return redirect(DEFAULT_REDIRECT)

    slug = row[0]
    headers = {"Authorization": f"Ghost {GHOST_ADMIN_KEY}"}
    r = requests.get(ghost_api_url(slug), headers=headers)

    if r.status_code != 200:
        return redirect(f"{GHOST_URL}/{slug}/")

    post = r.json()["posts"][0]
    html = post["html"]
    return Response(html, mimetype="text/html")

@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "usage": f"{APP_BASE_URL}/generate/<slug>?ref=fanbox",
        "ghost_url": GHOST_URL
    })

if __name__ == "__main__":
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "5000"))
    debug = os.getenv("APP_DEBUG", "false").lower() == "true"

    app.run(host=host, port=port, debug=debug)
