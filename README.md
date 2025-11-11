# Ghost FriendLink Gateway

A lightweight Flask-based gateway for sharing private or paid Ghost posts via unique access tokens.

Each token is unique, can be generated per platform ( Ko-fi, Patreon, Gumroad, your mum, etc.), and can be revoked anytime.
Designed to run seamlessly on **Coolify** or any Docker-based host.
※ This repo is vibe coded with Chat GPT-5, Codex and Cursor.

## Features

- 🔗 Generate unique access links per post or platform  
- 🧱 Fully environment-variable driven (no hardcoded URLs)  
- 🪶 Invalid links redirect to your Ghost signup or paywall page  
- 🧹 Simple SQLite-based token storage  
- 🎨 Beautiful minimalistic default CSS (customizable via template or `CUSTOM_CSS_URL`)  
- 📝 Automatic site metadata fetching from Ghost (title, description)  
- 🔒 Referrer whitelist management via API (track and control link distribution)  
- 🎯 Per-post guest allowlists so each member only sees the rooms you assign  
- 📊 Access statistics and leak detection (monitor token usage per referrer)  
- ⏰ Per-link expiration settings (flexible token lifetime control)  
- 🌐 Referer-domain logging (only the domain, no query string) for spotting pirate embeds  
- 🗂️ CSV/JSON access-log exports + retention controls (automation-friendly)  
- 🖼️ Rich metadata passthrough (favicon + OG/Twitter tags pulled from Ghost)  
- 📋 Post-first dashboard: pick a Ghost slug, assign guests, mint links, revoke keys  
- 🔐 `/admin/login` form issues secure sessions + CSRF tokens (no browser pop-ups)  
- 👥 Bulk link minting: paste up to `MAX_BULK_REFS` comma/newline-separated guests and get copy-ready links in one click  
- 🛡️ HTTPS enforcement + rate-limited admin endpoints to stop brute-force sharing  
- ⚡ Compatible with Ghost v5+ and Python 3.11+

## Installation

### In Docker

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/ghost-friendlink-gateway.git
   cd ghost-friendlink-gateway
   ```

2. **Set up environment variables:**
   ```bash
   cp env.template .env
   ```
   Edit `.env` and replace the placeholder values with your actual values:
   - Replace `https://your-ghost-blog.com` with your Ghost blog URL
   - Replace `your-id:your-secret` with your Ghost Admin API key
   - **Set `ADMIN_API_KEY` to a strong, random value (used by `/generate` and admin APIs)**
   - **Set `ADMIN_LOGIN_USERNAME` / `ADMIN_LOGIN_PASSWORD` for the dashboard login**
   - (Optional) set `FLASK_SECRET` to a random string for session cookies (defaults to the admin key)
   - Replace `https://your-gateway-domain.com` with your gateway's public URL
   - Fill in optional values if needed
   - Run `openssl rand -hex 32` and paste the output into `ADMIN_API_KEY` (and optionally `FLASK_SECRET`). Use a separate random string for `ADMIN_LOGIN_PASSWORD` so the dashboard login differs from the API key.
   
   **Note:** The `.env` file contains sensitive information and is automatically ignored by git (see `.gitignore`). The `env.template` file is a safe template that you can copy.


3. **Build and run with Docker:**
   ```bash
   docker build -t ghost-friendlink-gateway .
   docker run -d \
     --name ghost-friendlink \
     --env-file .env \
     -p 5000:5000 \
     -v $(pwd)/data:/app/data \
     ghost-friendlink-gateway
   ```

   Or use `docker-compose.yml`:
   ```bash
   docker-compose up -d
   ```

4. **Access the app:**
   The app will be available at `http://localhost:5000`
5. **Sign into the dashboard:** Visit `http://localhost:5000/admin/login`, enter `ADMIN_LOGIN_USERNAME` / `ADMIN_LOGIN_PASSWORD`, and you’ll be redirected to `/admin/dashboard`.

### In Coolify

1. Create a new **Dockerfile App** in Coolify  
2. Point it to this repository  
3. Set up environment variables (choose one method below):

#### Quick Setup with Developer View (Recommended)

Coolify's Developer View allows you to copy and paste multiple environment variables at once!

1. Open the `env.template` file in this repository
2. Copy all the content
3. In Coolify, go to **Configuration** → **Environment Variables** → **Developer View**
4. Paste the content and replace the placeholder values with your actual values:
   - Replace `https://your-ghost-blog.com` with your Ghost blog URL
   - Replace `your-id:your-secret` with your Ghost Admin API key
   - **Set `ADMIN_API_KEY` (required) with a strong random string; the dashboard generator and `/generate` use this key**
   - **Set `ADMIN_LOGIN_USERNAME` / `ADMIN_LOGIN_PASSWORD` (required) for the dashboard login**
   - (Optional) set `FLASK_SECRET` to a random string for session cookies (defaults to the admin key)
   - Replace `https://your-gateway-domain.com` with your gateway's public URL
   - Fill in optional values if needed
5. Click **Save**

![Coolify Environment Variables Developer View](https://media.publit.io/file/hiyukoim/Github/CleanShot-2025-11-10-at-17.58.46.jpeg)

*Screenshot showing Coolify's Developer View where you can paste multiple environment variables at once*

After deployment, open `https://your-gateway-domain.com/admin/login`, authenticate with `ADMIN_LOGIN_USERNAME` / `ADMIN_LOGIN_PASSWORD`, and you’ll land on the dashboard.
#### Manual Setup (Alternative)

If you prefer to add variables one by one, go to **Configuration** → **Environment Variables** and add the following:

**Required Environment Variables:**

| Variable | Value | Where to get it |
|----------|-------|-----------------|
| `GHOST_URL` | Your Ghost blog URL | `https://your-ghost-blog.com` |
| `GHOST_ADMIN_KEY` | Admin API key | Ghost Admin → Settings → Integrations → Create Custom Integration → Copy Admin API key (format: `id:secret`) |
| `APP_BASE_URL` | Your gateway's public URL | `https://example.com` (the domain you set in Coolify) |
| `ADMIN_API_KEY` | Random admin token that locks `/generate` and admin APIs | `openssl rand -hex 32` |

**Optional Environment Variables:**

| Variable | Value | Description |
|----------|-------|-------------|
| `DEFAULT_REDIRECT` | `https://your-ghost-blog.com/#/portal/signup` | Where to redirect invalid/expired tokens |
| `CUSTOM_CSS_URL` | `https://your-ghost-blog.com/assets/custom.css` | Custom CSS URL to override default CSS |
| `SITE_TITLE` | `My Blog` | Site title (overrides Ghost API fetch) |
| `SITE_DESCRIPTION` | `My blog description` | Site description (overrides Ghost API fetch) |
| `SITE_ICON_URL` | (empty) | Override favicon shown on rendered pages |
| `SITE_LOGO_URL` | (empty) | Override logo used in metadata |
| `TOKEN_EXPIRY_DAYS` | `0` | Token expiration in days. `0` keeps links forever (default) |
| `ACCESS_LOG_RETENTION_DAYS` | `60` | How long to keep access logs. `0` disables logging. Negative keeps forever. |
| `ADMIN_LOGIN_USERNAME` | `admin` | Username for the `/admin/login` form |
| `ADMIN_LOGIN_PASSWORD` | (empty) | Password for `/admin/login` (defaults to `ADMIN_API_KEY` if left empty) |
| `FLASK_SECRET` | (empty) | Secret key for session cookies (defaults to `ADMIN_API_KEY` or fallback) |
| `ADMIN_SESSION_HOURS` | `12` | How long admin sessions stay valid before requiring a new login |
| `DEFAULT_RATE_LIMIT` | `240/hour` | Baseline rate limit for anonymous/read endpoints |
| `ADMIN_RATE_LIMIT` | `60/minute` | Rate limit applied to admin APIs and dashboard actions |
| `GENERATE_RATE_LIMIT` | `20/minute` | Rate limit for `/generate/<slug>` |
| `ENFORCE_HTTPS` | `true` | Reject plain HTTP unless you disable it for local dev |
| `PROXY_FORWARDED_FOR` | `1` | Number of trusted proxy hops for `X-Forwarded-For` |
| `PROXY_FORWARDED_PROTO` | `1` | Number of trusted proxy hops for `X-Forwarded-Proto` |
| `PORT` | `5000` | Internal port (usually don't need to change) |
| `MAX_BULK_REFS` | `25` | Upper bound for comma/newline-separated guests per bulk generation |

4. (Optional) Map a persistent volume to `/app/data` for token storage  
5. Deploy 🚀

## Environment Variables

| Variable | Description | Example |
|-----------|--------------|----------|
| `GHOST_URL` | Your Ghost blog base URL | `https://yourblog.com` |
| `GHOST_ADMIN_KEY` | Admin API key from Ghost Integrations | `abc123:verylongsecret` |
| `APP_BASE_URL` | Public base URL of this app | `https://gateway.yourdomain.com` |
| `DEFAULT_REDIRECT` | (Optional) Fallback URL for invalid tokens | `https://yourblog.com/#/portal/signup` |
| `CUSTOM_CSS_URL` | (Optional) Custom CSS URL to override default CSS | `https://yourblog.com/assets/custom.css` |
| `SITE_TITLE` | (Optional) Site title (overrides Ghost API fetch) | `My Blog` |
| `SITE_DESCRIPTION` | (Optional) Site description (overrides Ghost API fetch) | `My blog description` |
| `SITE_ICON_URL` | (Optional) Custom favicon URL for rendered pages | `https://yourblog.com/favicon.ico` |
| `SITE_LOGO_URL` | (Optional) Custom logo URL fallback for metadata | `https://yourblog.com/content/images/logo.png` |
| `TOKEN_EXPIRY_DAYS` | (Optional) Token expiration in days. Set to `0` for no expiration | `0` (default: never expires). Set to `30` to enforce 30-day lifetime |
| `ADMIN_API_KEY` | **Required.** API key for admin APIs and `/generate/<slug>` | Output of `openssl rand -hex 32` (64 hex chars) |
| `ACCESS_LOG_RETENTION_DAYS` | (Optional) How long to keep access logs. `60` default, `0` disables logging, negative keeps forever | `60` |
| `ADMIN_LOGIN_USERNAME` | (Optional) Username for `/admin/login` | `admin` |
| `ADMIN_LOGIN_PASSWORD` | (Optional) Password for `/admin/login`. Defaults to `ADMIN_API_KEY` when unset | Separate random string |
| `FLASK_SECRET` | (Optional) Secret used for session cookies | Another `openssl rand -hex 32` |
| `ADMIN_SESSION_HOURS` | (Optional) Validity window for admin sessions | `12` |
| `DEFAULT_RATE_LIMIT` | Default rate limit applied globally (`240/hour` by default) | `240/hour` |
| `ADMIN_RATE_LIMIT` | Rate limit for admin endpoints | `60/minute` |
| `GENERATE_RATE_LIMIT` | Rate limit for `/generate/<slug>` | `20/minute` |
| `ENFORCE_HTTPS` | Require HTTPS requests (`true` by default) | `true` |
| `MAX_BULK_REFS` | Maximum guests allowed per bulk generation (comma/newline-separated) | `25` |
| `PROXY_FORWARDED_FOR` | Trusted proxy hops for `X-Forwarded-For` | `1` |
| `PROXY_FORWARDED_PROTO` | Trusted proxy hops for `X-Forwarded-Proto` | `1` |
| `PORT` | Internal server port | `5000` |

## Example Usage

### Generate a token

```
GET /generate/my-paid-post?ref=patreon_01_01
```

> **Authentication:** This endpoint requires admin credentials (Bearer token or an active session from `/admin/login`). The dashboard keeps your session cookie, so you just fill slug/ref and click “Generate” to get a copy-ready link.

**Query Parameters:**
- `ref` (required unless `refs` provided): Referrer identifier (e.g., `patreon_01_01`, `user@example.com`). You can pass a comma- or newline-separated list (`ref=user1,user2,user3`) to mint multiple links at once, up to `MAX_BULK_REFS`.
- `refs` (optional): Repeatable query parameter (`?refs=user1&refs=user2`) if you prefer to send multiple values explicitly.
- `expires_days` (optional): Override default expiration with relative days (e.g., `7` for 7 days). Leave empty for “never expires”.
- `expires_at` (optional): Override default expiration with an absolute date (`YYYY-MM-DD`, e.g., `2025-12-31`). Mutually exclusive with `expires_days`.

> When using the dashboard, the guest and slug are auto-added to the allowlist before the link is generated. If you call this endpoint directly, make sure the referrer has the slug assigned first—otherwise you’ll get `403 Slug not allowed for this referrer`.
> Treat `ref` as “who or where this link belongs to” (e.g., subscriber email, platform handle, campaign code). Pick a stable identifier so you can trace leaks easily.

**Examples:**
```
GET /generate/my-paid-post?ref=patreon_01_01
GET /generate/my-paid-post?ref=user@example.com&expires_days=7
GET /generate/my-paid-post?ref=patreon_01_01&expires_at=2025-12-31
GET /generate/my-paid-post?ref=alice@example.com,bob@example.com,charlie@example.com
GET /generate/my-paid-post?refs=patreon_tier1&refs=patreon_tier2
```

Response (single ref):

```json
{
  "slug": "my-paid-post",
  "ref": "patreon_01_01",
  "token_url": "https://gateway.yourdomain.com/read/07ec6b8f-...",
  "expires_at": "2025-12-10T12:00:00"
}
```

Response (bulk refs):

```json
{
  "slug": "my-paid-post",
  "count": 3,
  "tokens": [
    {"ref": "alice@example.com", "token_url": "https://.../read/uuid-1", "token": "uuid-1", "expires_at": "Never"},
    {"ref": "bob@example.com", "token_url": "https://.../read/uuid-2", "token": "uuid-2", "expires_at": "Never"},
    {"ref": "charlie@example.com", "token_url": "https://.../read/uuid-3", "token": "uuid-3", "expires_at": "Never"}
  ]
}
```

### Revoke a token

```
POST /revoke/<token>
```

> Tip: The dashboard lists the latest tokens with a “Revoke” button (it reuses your session from `/admin/login`). Click revoke → confirm and it issues the `POST /revoke/<token>` call for you.

### Access content

```
GET /read/<token>
```

If valid → returns the Ghost post HTML wrapped in a minimal template  
If invalid → redirects to your configured signup/paywall page

### Referrer Management & Access Tracking

The app includes powerful referrer management and access tracking features to help you monitor and control link distribution.

Every access log now stores the normalized referer domain (scheme stripped, `www.` removed, query fragments dropped). This gives you a quick view of which public site embedded a leaked link without capturing the entire URL.

#### Exporting Access Logs

- `GET /admin/access-logs` — JSON feed for scripts and cron jobs. Filter by `ref`, `token`, `since`, `until`, choose `order`, and set `limit` (default 100, max 1000).
- `GET /admin/access-logs.csv` — Download the same data as CSV so you can keep monthly/quarterly archives. Supports the exact same filters plus a higher default `limit=1000`.

Both endpoints require `Authorization: Bearer <ADMIN_API_KEY>`.  
To avoid typing timestamps, pass `preset=<name>`; the server expands it to a ready-made date window (you can still override `since`/`until` manually):

| Preset | Range |
|--------|-------|
| `today` | Start/end of the current UTC day |
| `yesterday` | Previous UTC day |
| `this_week` | Monday → now (UTC) |
| `last_week` | Previous Monday → Sunday |
| `this_month` | First of this month → now |
| `last_month` | Entire previous calendar month |
| `this_year` | Jan 1 of this year → now |
| `last_year` | Entire previous calendar year |

#### Privacy Tips

- IP address, user agent, and referer domain are stored for leak detection. Keep `ACCESS_LOG_RETENTION_DAYS` short if you want minimum retention, and document this behavior in your own privacy policy.
- Need lighter data? Hash or truncate IPs before storage, or disable logging entirely by setting `ACCESS_LOG_RETENTION_DAYS=0`.
- Always deploy behind HTTPS (e.g., via Cloudflare, Caddy, Nginx) and consider extra protections such as WAF/rate limits if the admin endpoints are exposed to the public internet.
- Rate limiting is enabled by default (see `DEFAULT_RATE_LIMIT`, `ADMIN_RATE_LIMIT`, `GENERATE_RATE_LIMIT`). Tune these values to match your traffic profile. `ENFORCE_HTTPS=true` rejects plaintext requests so only HTTPS/forwarded HTTPS traffic is served.
- If you deploy behind Cloudflare/Nginx/etc., set `PROXY_FORWARDED_FOR` / `PROXY_FORWARDED_PROTO` to the number of trusted proxy hops so the app can read `X-Forwarded-*` headers safely (implemented via Werkzeug’s `ProxyFix`).

#### Automatic Retention & Manual Cleanup

- Configure `ACCESS_LOG_RETENTION_DAYS` to control how long entries live (default `60` days).  
  - Set to `0` to disable access logging entirely.  
  - Set to a negative number (e.g., `-1`) to keep logs forever.
- The server trims old rows automatically every time it logs a visit (when retention is positive).
- Trigger cleanup manually with:
  ```
  POST /admin/access-logs/cleanup
  Authorization: Bearer <ADMIN_API_KEY>
  Content-Type: application/json

  {}                     # apply current retention window
  {"older_than_days":30} # one-off purge threshold
  {"delete_all":true}    # flush everything
  ```
#### Referrer Whitelist Management

**List all allowed referrers:**
```
GET /admin/referrers
Authorization: Bearer <ADMIN_API_KEY>
```

**Add a new allowed referrer:**
```
POST /admin/referrers
Authorization: Bearer <ADMIN_API_KEY>
Content-Type: application/json

{
  "referrer": "patreon_01_01"
}
```

**Revoke a referrer (deactivate):**
```
DELETE /admin/referrers/patreon_01_01
Authorization: Bearer <ADMIN_API_KEY>
```

#### Post Access (Ghost slug allowlist)

Treat each Ghost slug as a room; you decide which guests (referrers) can enter. The dashboard auto-grants the slug when you mint a link, but you can also use these APIs to pre-provision or script access. If you rename the slug in Ghost, reassign that slug (and mint new links) because existing tokens will point to the old URL.

**List slugs for a referrer**
```
GET /admin/referrers/slugs?ref=patreon_01_01
Authorization: Bearer <ADMIN_API_KEY>
```

**Grant a referrer access to a slug**
```
POST /admin/referrers/slugs
Authorization: Bearer <ADMIN_API_KEY>
Content-Type: application/json

{
  "referrer": "patreon_01_01",
  "slug": "my-paid-post"
}
```

**Revoke access**
```
DELETE /admin/referrers/slugs/patreon_01_01/my-paid-post
Authorization: Bearer <ADMIN_API_KEY>
```

#### Dashboard Snapshot

- `GET /admin/dashboard` — Minimal HTML dashboard protected by the `/admin/login` form (username/password come from `ADMIN_LOGIN_USERNAME` / `ADMIN_LOGIN_PASSWORD`; the password defaults to `ADMIN_API_KEY`). The “Posts & Guests” card comes first: pick a Ghost slug, see its guests, add/remove guests, then mint or revoke share links. The generator automatically creates guests/slugs as needed so you can copy a link instantly; additional cards show recent tokens plus housekeeping tips.

#### Access Statistics

**Get statistics for a referrer:**
```
GET /admin/stats?ref=patreon_01_01
Authorization: Bearer <ADMIN_API_KEY>
```

Returns:
- Total access count
- Unique IP addresses
- Recent accesses (last 10)
- All associated tokens

**Get statistics for a specific token:**
```
GET /admin/stats/token/<token>
Authorization: Bearer <ADMIN_API_KEY>
```

**List all tokens for a referrer:**
```
GET /admin/tokens?ref=patreon_01_01
Authorization: Bearer <ADMIN_API_KEY>
```

#### Use Cases

1. **Leak Detection**: Monitor access statistics to detect if a link has been shared publicly. If a referrer shows unusual access patterns (many unique IPs, high access count), you can quickly revoke it.

2. **Per-User Tracking**: Use email addresses or user IDs as referrers (e.g., `user@example.com`) to track which users are accessing content.

3. **Platform Tracking**: Use platform identifiers (e.g., `patreon_01_01`, `patreon_user123`) to track which platform generated the link.

**Note:** All admin endpoints require the `Authorization: Bearer <ADMIN_API_KEY>` header if `ADMIN_API_KEY` is set. If not set, endpoints are publicly accessible (not recommended for production).

### Styling & Customization

The app includes minimalistic default CSS in `static/style.css`. You have three options for styling:

1. **Use or modify default CSS** : No configuration needed. The default CSS provides a clean, readable design.

2. **Use external custom CSS URL**: Set `CUSTOM_CSS_URL` environment variable to point to your own stylesheet (e.g., your Ghost theme's CSS).

3. **Customize the template**: Edit `templates/post.html` and `templates/assets/style.css` directly to match your brand. The template is intentionally minimal and easy to modify. Keep the `templates/assets/` folder (and `.keep_this_file`) in place so Docker can copy your assets into `/static`.
   - Admin-only UI (landing page + dashboard) lives in `/app_ui/`. These files power the control panel and generally shouldn’t be edited when theming the public page.

**Site Metadata**: The app automatically fetches site title and description from Ghost's Content API. You can override these by setting `SITE_TITLE` and `SITE_DESCRIPTION` environment variables.

## Credits

This project was inspired by [ghost-iota-pay](https://github.com/F-Node-Karlsruhe/ghost-iota-pay) by F-Node-Karlsruhe,  
which implements a pay-per-content system for Ghost using IOTA payments.  
This project only takes inspiration from its private sharing mechanism, which allows trusted access to paywalled posts without the payment layer.

---

AGPL-3.0 License  
© 2025 Yuko F.
