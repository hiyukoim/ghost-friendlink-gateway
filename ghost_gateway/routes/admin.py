from __future__ import annotations

import csv
import datetime
import hmac
import io
import math
import secrets

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ghost_gateway import auth as auth_utils
from ghost_gateway import db as db_utils
from ghost_gateway import ghost as ghost_utils
from ghost_gateway.config import limiter, settings

admin_bp = Blueprint("admin", __name__)

ADMIN_RATE_LIMIT = settings.admin_rate_limit or "60/minute"
GENERATE_RATE_LIMIT = settings.generate_rate_limit or "20/minute"
MAX_BULK_REFS = settings.max_bulk_refs
ACCESS_LOG_RETENTION_DAYS = settings.access_log_retention_days
ADMIN_API_KEY = settings.admin_api_key


def _parse_positive_int(value, default):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _format_short_date(value: str, default: str = "—") -> str:
    dt = db_utils.parse_iso8601(value) if value else None
    if not dt:
        return default
    return dt.strftime("%Y-%m-%d")


@admin_bp.route("/admin/login", methods=["GET", "POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def admin_login():
    if session.get("is_admin"):
        next_url = request.args.get("next") or url_for("admin.admin_dashboard")
        return redirect(next_url)
    site = ghost_utils.get_ghost_site_settings()
    error = None
    username_value = ""
    next_param = request.args.get("next")
    if request.method == "POST":
        username_value = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        next_url = request.form.get("next") or next_param
        configured_user = settings.admin_login_username
        configured_pass = settings.admin_login_password
        if not configured_user or not configured_pass:
            error = "Server admin credentials are not configured."
        elif (
            hmac.compare_digest(username_value, configured_user)
            and hmac.compare_digest(password, configured_pass)
        ):
            session.clear()
            session["is_admin"] = True
            session["admin_username"] = username_value
            session["login_at"] = datetime.datetime.utcnow().isoformat()
            session["csrf_token"] = secrets.token_hex(32)
            session.permanent = True
            target = next_url or url_for("admin.admin_dashboard")
            if not target.startswith("/"):
                target = url_for("admin.admin_dashboard")
            return redirect(target)
        else:
            error = "Invalid username or password."
    return render_template(
        "login.html",
        site=site,
        error=error,
        next_url=next_param,
        username=username_value,
        ADMIN_SESSION_HOURS=settings.admin_session_hours,
        app_version=settings.app_version,
    )


@admin_bp.route("/admin/logout", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def admin_logout():
    csrf_error = auth_utils.require_session_csrf(json_response=False)
    if csrf_error:
        return csrf_error
    session.clear()
    return redirect(url_for("admin.admin_login"))


@admin_bp.route("/generate/<slug>")
@limiter.limit(GENERATE_RATE_LIMIT)
def api_generate(slug):
    if not ADMIN_API_KEY:
        current_app.logger.warning(
            "Rejected /generate call because ADMIN_API_KEY is not configured"
        )
        return jsonify({"error": "Admin API key is not configured on the server"}), 503
    if not auth_utils.has_valid_admin_bearer():
        return jsonify({"error": "Admin API key required"}), 401
    refs = db_utils.normalize_ref_list(
        request.args.get("ref"), request.args.getlist("refs")
    )
    if not refs:
        return jsonify({"error": "ref parameter is required"}), 400
    if len(refs) > MAX_BULK_REFS:
        return (
            jsonify(
                {
                    "error": f"Too many referrers supplied. Max {MAX_BULK_REFS} per request."
                }
            ),
            400,
        )
    expires_days_param = request.args.get("expires_days")
    expires_at_param = request.args.get("expires_at")
    try:
        if len(refs) == 1:
            return jsonify(
                db_utils.create_token(slug, refs[0], expires_days_param, expires_at_param)
            )
        tokens = db_utils.create_tokens_for_refs(
            slug, refs, expires_days_param, expires_at_param
        )
        return jsonify({"slug": slug, "count": len(tokens), "tokens": tokens})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception:  # pragma: no cover - unexpected error path
        current_app.logger.exception("Unexpected error while creating token via /generate")
        return jsonify({"error": "Internal server error"}), 500


@admin_bp.route("/revoke/<token>", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def revoke_token(token):
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    csrf_error = auth_utils.require_session_csrf()
    if csrf_error:
        return csrf_error
    with db_utils.get_connection() as conn:
        conn.execute(
            """
            UPDATE access_tokens
            SET valid = 0, revoked_at = ?
            WHERE token = ?
            """,
            (datetime.datetime.utcnow().isoformat(), token),
        )
        conn.commit()
    return jsonify({"status": "revoked", "token": token})


@admin_bp.route("/admin/referrers", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def list_referrers():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    with db_utils.get_connection() as conn:
        rows = conn.execute(
            "SELECT referrer, created_at, active FROM allowed_referrers ORDER BY created_at DESC"
        ).fetchall()
    return jsonify(
        {
            "referrers": [
                {"referrer": row[0], "created_at": row[1], "active": bool(row[2])}
                for row in rows
            ]
        }
    )


@admin_bp.route("/admin/referrers", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def add_referrer():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    csrf_error = auth_utils.require_session_csrf()
    if csrf_error:
        return csrf_error
    data = request.get_json() or {}
    ref = (data.get("referrer") or "").strip()
    if not ref:
        return jsonify({"error": "referrer field is required"}), 400
    with db_utils.get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO allowed_referrers (referrer, created_at, active)
            VALUES (?, ?, 1)
            """,
            (ref, datetime.datetime.utcnow().isoformat()),
        )
        conn.commit()
    return jsonify({"status": "added", "referrer": ref}), 201


@admin_bp.route("/admin/referrers/<referrer>", methods=["DELETE"])
@limiter.limit(ADMIN_RATE_LIMIT)
def deactivate_referrer(referrer):
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    csrf_error = auth_utils.require_session_csrf()
    if csrf_error:
        return csrf_error
    with db_utils.get_connection() as conn:
        conn.execute(
            "UPDATE allowed_referrers SET active = 0 WHERE referrer = ?",
            (referrer,),
        )
        conn.commit()
    return jsonify({"status": "revoked", "referrer": referrer})


@admin_bp.route("/admin/referrers/slugs", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def list_referrer_posts():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    ref = request.args.get("ref")
    if not ref:
        return jsonify({"error": "ref parameter is required"}), 400
    with db_utils.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT slug, active, created_at
            FROM referrer_posts
            WHERE referrer = ?
            ORDER BY slug
            """,
            (ref,),
        ).fetchall()
    return jsonify(
        {
            "referrer": ref,
            "slugs": [
                {"slug": row[0], "active": bool(row[1]), "created_at": row[2]}
                for row in rows
            ],
        }
    )


@admin_bp.route("/admin/referrers/slugs", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def add_referrer_post():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    csrf_error = auth_utils.require_session_csrf()
    if csrf_error:
        return csrf_error
    data = request.get_json() or {}
    ref = (data.get("referrer") or "").strip()
    slug = (data.get("slug") or "").strip()
    if not ref or not slug:
        return jsonify({"error": "referrer and slug are required"}), 400
    with db_utils.get_connection() as conn:
        row = conn.execute(
            "SELECT active FROM allowed_referrers WHERE referrer = ?", (ref,)
        ).fetchone()
        if row is None:
            return jsonify({"error": "Referrer not found"}), 404
        if row[0] != 1:
            return jsonify({"error": "Referrer inactive"}), 400
        conn.execute(
            """
            INSERT OR REPLACE INTO referrer_posts (referrer, slug, active, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (ref, slug, datetime.datetime.utcnow().isoformat()),
        )
        conn.commit()
    return jsonify({"status": "added", "referrer": ref, "slug": slug}), 201


@admin_bp.route("/admin/referrers/slugs/<referrer>/<slug>", methods=["DELETE"])
@limiter.limit(ADMIN_RATE_LIMIT)
def delete_referrer_post(referrer, slug):
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    csrf_error = auth_utils.require_session_csrf()
    if csrf_error:
        return csrf_error
    with db_utils.get_connection() as conn:
        conn.execute(
            "UPDATE referrer_posts SET active = 0 WHERE referrer = ? AND slug = ?",
            (referrer, slug),
        )
        conn.commit()
    return jsonify({"status": "revoked", "referrer": referrer, "slug": slug})


@admin_bp.route("/admin/stats", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def get_referrer_stats():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    ref = request.args.get("ref")
    if not ref:
        return jsonify({"error": "ref parameter is required"}), 400
    with db_utils.get_connection() as conn:
        total_count = conn.execute(
            "SELECT COUNT(*) FROM access_logs WHERE referrer = ?", (ref,)
        ).fetchone()[0]
        unique_ips = conn.execute(
            "SELECT COUNT(DISTINCT ip_address) FROM access_logs WHERE referrer = ?",
            (ref,),
        ).fetchone()[0]
        recent = conn.execute(
            """
            SELECT token, ip_address, user_agent, accessed_at, referer_domain
            FROM access_logs
            WHERE referrer = ?
            ORDER BY accessed_at DESC
            LIMIT 10
            """,
            (ref,),
        ).fetchall()
        tokens = conn.execute(
            """
            SELECT at.token, a.slug, at.created_at, at.expires_at, at.valid
            FROM access_tokens at
            JOIN articles a ON a.id = at.article_id
            WHERE at.guest = ?
            ORDER BY at.created_at DESC
            """,
            (ref,),
        ).fetchall()
    return jsonify(
        {
            "referrer": ref,
            "total_accesses": total_count,
            "unique_ips": unique_ips,
            "recent_accesses": [
                {
                    "token": row[0],
                    "ip_address": row[1],
                    "user_agent": row[2],
                    "accessed_at": row[3],
                    "referer_domain": row[4],
                }
                for row in recent
            ],
            "tokens": [
                {
                    "token": row[0],
                    "slug": row[1],
                    "created_at": row[2],
                    "expires_at": row[3],
                    "valid": bool(row[4]),
                }
                for row in tokens
            ],
        }
    )


@admin_bp.route("/admin/access-logs", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def list_access_logs_api():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    ref = request.args.get("ref")
    token = request.args.get("token")
    order = request.args.get("order", "desc")
    limit = request.args.get("limit", 100)
    offset = request.args.get("offset", 0)
    preset_name = request.args.get("preset")
    since_str = request.args.get("since")
    until_str = request.args.get("until")
    since = db_utils.parse_iso8601(since_str)
    until = db_utils.parse_iso8601(until_str)
    if since_str and not since:
        return (
            jsonify(
                {
                    "error": "Invalid since timestamp. Use ISO 8601 (e.g., 2025-01-30T12:00:00)"
                }
            ),
            400,
        )
    if until_str and not until:
        return (
            jsonify(
                {
                    "error": "Invalid until timestamp. Use ISO 8601 (e.g., 2025-01-30T12:00:00)"
                }
            ),
            400,
        )
    if preset_name:
        preset_range = db_utils.get_preset_range(preset_name)
        if not preset_range:
            return (
                jsonify(
                    {
                        "error": "Unknown preset. Supported values: today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year"
                    }
                ),
                400,
            )
        preset_since, preset_until = preset_range
        if not since:
            since = preset_since
        if not until:
            until = preset_until
    logs = db_utils.fetch_access_logs(
        limit=limit,
        offset=offset,
        ref=ref,
        token=token,
        since=since,
        until=until,
        order=order,
    )
    return jsonify({"count": len(logs), "logs": logs})


@admin_bp.route("/admin/access-logs.csv", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def export_access_logs_csv():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    ref = request.args.get("ref")
    token = request.args.get("token")
    order = request.args.get("order", "desc")
    limit = request.args.get("limit", 1000)
    offset = request.args.get("offset", 0)
    preset_name = request.args.get("preset")
    since_str = request.args.get("since")
    until_str = request.args.get("until")
    since = db_utils.parse_iso8601(since_str)
    until = db_utils.parse_iso8601(until_str)
    if since_str and not since:
        return (
            jsonify(
                {
                    "error": "Invalid since timestamp. Use ISO 8601 (e.g., 2025-01-30T12:00:00)"
                }
            ),
            400,
        )
    if until_str and not until:
        return (
            jsonify(
                {
                    "error": "Invalid until timestamp. Use ISO 8601 (e.g., 2025-01-30T12:00:00)"
                }
            ),
            400,
        )
    if preset_name:
        preset_range = db_utils.get_preset_range(preset_name)
        if not preset_range:
            return (
                jsonify(
                    {
                        "error": "Unknown preset. Supported values: today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year"
                    }
                ),
                400,
            )
        preset_since, preset_until = preset_range
        if not since:
            since = preset_since
        if not until:
            until = preset_until
    logs = db_utils.fetch_access_logs(
        limit=limit,
        offset=offset,
        ref=ref,
        token=token,
        since=since,
        until=until,
        order=order,
    )

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "token",
                "referrer",
                "referer_domain",
                "ip_address",
                "user_agent",
                "accessed_at",
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for entry in logs:
            writer.writerow(
                [
                    entry["id"],
                    entry["token"],
                    entry["referrer"],
                    entry.get("referer_domain") or "",
                    entry["ip_address"],
                    entry["user_agent"],
                    entry["accessed_at"],
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"access-logs-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(generate(), mimetype="text/csv", headers=headers)


@admin_bp.route("/admin/access-logs/cleanup", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def cleanup_access_logs():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    csrf_error = auth_utils.require_session_csrf()
    if csrf_error:
        return csrf_error

    payload = request.get_json(silent=True) or {}
    delete_all = bool(payload.get("delete_all"))
    older_than_days = payload.get("older_than_days")

    with db_utils.get_connection() as conn:
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
            deleted = db_utils.enforce_access_log_retention(conn, days=custom_days)
            return jsonify(
                {"status": "custom_cleanup", "deleted_rows": deleted, "days": custom_days}
            )

        deleted = db_utils.enforce_access_log_retention(conn)
        return jsonify(
            {
                "status": "retention_cleanup",
                "deleted_rows": deleted,
                "days": max(ACCESS_LOG_RETENTION_DAYS, 0),
            }
        )


@admin_bp.route("/admin/tokens/cleanup", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def cleanup_expired_tokens():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    csrf_error = auth_utils.require_session_csrf()
    if csrf_error:
        return csrf_error

    now = datetime.datetime.utcnow().isoformat()
    with db_utils.get_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM access_tokens
            WHERE valid = 0
               OR (
                   expires_at IS NOT NULL AND expires_at != ''
                   AND expires_at < ?
               )
            """,
            (now,),
        )
        conn.commit()
        deleted = cursor.rowcount if cursor.rowcount != -1 else conn.total_changes
    return jsonify({"status": "token_cleanup", "deleted": deleted})


@admin_bp.route("/admin/generate", methods=["POST"])
@limiter.limit(ADMIN_RATE_LIMIT)
def admin_generate():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    csrf_error = auth_utils.require_session_csrf()
    if csrf_error:
        return csrf_error
    data = request.get_json() or {}
    slug = (data.get("slug") or "").strip()
    refs = db_utils.normalize_ref_list(data.get("ref"), data.get("refs"))
    if not slug:
        return jsonify({"error": "slug is required"}), 400
    if not refs:
        return jsonify({"error": "ref (or refs) is required"}), 400
    if len(refs) > MAX_BULK_REFS:
        return (
            jsonify(
                {
                    "error": f"Too many referrers supplied. Max {MAX_BULK_REFS} per request."
                }
            ),
            400,
        )
    expires_days = data.get("expires_days")
    expires_at = data.get("expires_at")
    try:
        if len(refs) == 1:
            return jsonify(db_utils.create_token(slug, refs[0], expires_days, expires_at))
        tokens = db_utils.create_tokens_for_refs(slug, refs, expires_days, expires_at)
        return jsonify({"slug": slug, "count": len(tokens), "tokens": tokens})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception:  # pragma: no cover - unexpected error path
        current_app.logger.exception("Unexpected error while creating token via /admin/generate")
        return jsonify({"error": "Internal server error"}), 500


@admin_bp.route("/admin/dashboard", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def admin_dashboard():
    redirect_response = auth_utils.redirect_to_login()
    if redirect_response:
        return redirect_response

    pairs_per_page = 25
    tokens_per_page = 25
    requested_pairs_page = _parse_positive_int(request.args.get("pairs_page", 1), 1)
    requested_tokens_page = _parse_positive_int(request.args.get("tokens_page", 1), 1)

    with db_utils.get_connection() as conn:
        pair_total = conn.execute(
            "SELECT COUNT(*) FROM referrer_posts WHERE active = 1"
        ).fetchone()[0]
        pair_pages = max(1, math.ceil(pair_total / pairs_per_page)) if pair_total else 1
        pairs_page = min(requested_pairs_page, pair_pages)
        pairs_offset = (pairs_page - 1) * pairs_per_page
        pair_rows = conn.execute(
            """
            SELECT slug, referrer, created_at
            FROM referrer_posts
            WHERE active = 1
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (pairs_per_page, pairs_offset),
        ).fetchall()

        token_total = conn.execute("SELECT COUNT(*) FROM access_tokens").fetchone()[0]
        token_pages = max(1, math.ceil(token_total / tokens_per_page)) if token_total else 1
        tokens_page = min(requested_tokens_page, token_pages)
        tokens_offset = (tokens_page - 1) * tokens_per_page
        token_rows = conn.execute(
            """
            SELECT at.token, a.slug, at.guest, at.created_at, at.expires_at, at.valid
            FROM access_tokens at
            JOIN articles a ON a.id = at.article_id
            ORDER BY at.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (tokens_per_page, tokens_offset),
        ).fetchall()

        latest_token_map = {}
        pair_keys = {(ref, slug) for slug, ref, _ in pair_rows}
        if pair_keys:
            cursor = conn.cursor()
            for ref, slug in pair_keys:
                latest_row = cursor.execute(
                    """
                    SELECT at.token, at.created_at, at.expires_at, at.valid
                    FROM access_tokens at
                    JOIN articles a ON a.id = at.article_id
                    WHERE at.guest = ? AND a.slug = ?
                    ORDER BY at.created_at DESC
                    LIMIT 1
                    """,
                    (ref, slug),
                ).fetchone()
                if latest_row:
                    latest_token_map[(ref, slug)] = {
                        "token": latest_row[0],
                        "created_at": latest_row[1],
                        "expires_at": latest_row[2],
                        "valid": bool(latest_row[3]),
                    }

    now = datetime.datetime.utcnow()
    pairs = []
    for slug, ref, created_at in pair_rows:
        token_info = latest_token_map.get((ref, slug))
        expires_at = token_info["expires_at"] if token_info else None
        expires_display = "—"
        expired = False
        if token_info:
            expires_display = _format_short_date(expires_at, "Never")
            expires_dt = db_utils.parse_iso8601(expires_at)
            if expires_dt and expires_dt < now:
                expired = True
            if not token_info["valid"]:
                expired = True
        pairs.append(
            {
                "slug": slug,
                "referrer": ref,
                "token": token_info,
                "created_display": _format_short_date(created_at),
                "expires_display": expires_display,
                "expired": expired,
            }
        )
    tokens = [
        {
            "token": row[0],
            "slug": row[1],
            "referrer": row[2],
            "created_at": row[3],
            "expires_at": row[4],
            "valid": bool(row[5]),
        }
        for row in token_rows
    ]
    site = ghost_utils.get_ghost_site_settings()
    return render_template(
        "dashboard.html",
        site=site,
        pairs=pairs,
        tokens=tokens,
        app_base_url=settings.app_base_url,
        ghost_url=settings.ghost_url,
        csrf_token=auth_utils.get_or_create_csrf_token(),
        admin_username=session.get("admin_username", settings.admin_login_username),
        max_bulk_refs=MAX_BULK_REFS,
        pairs_page=pairs_page,
        pair_pages=pair_pages,
        pair_total=pair_total,
        pairs_per_page=pairs_per_page,
        tokens_page=tokens_page,
        token_pages=token_pages,
        token_total=token_total,
        tokens_per_page=tokens_per_page,
        app_version=settings.app_version,
        current_year=datetime.datetime.utcnow().year,
    )


@admin_bp.route("/admin/stats/token/<token>", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def get_token_stats(token):
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    with db_utils.get_connection() as conn:
        token_row = conn.execute(
            """
            SELECT a.slug, at.guest, at.created_at, at.expires_at, at.valid
            FROM access_tokens at
            JOIN articles a ON a.id = at.article_id
            WHERE at.token = ?
            """,
            (token,),
        ).fetchone()
        if not token_row:
            return jsonify({"error": "Token not found"}), 404
        logs = conn.execute(
            """
            SELECT ip_address, user_agent, accessed_at, referer_domain
            FROM access_logs
            WHERE token = ?
            ORDER BY accessed_at DESC
            """,
            (token,),
        ).fetchall()
    return jsonify(
        {
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
                    "referer_domain": row[3],
                }
                for row in logs
            ],
        }
    )


@admin_bp.route("/admin/tokens", methods=["GET"])
@limiter.limit(ADMIN_RATE_LIMIT)
def list_tokens():
    if not auth_utils.check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    ref = request.args.get("ref")
    if not ref:
        return jsonify({"error": "ref parameter is required"}), 400
    with db_utils.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT at.token, a.slug, at.created_at, at.expires_at, at.valid
            FROM access_tokens at
            JOIN articles a ON a.id = at.article_id
            WHERE at.guest = ?
            ORDER BY at.created_at DESC
            """,
            (ref,),
        ).fetchall()
    tokens = [
        {
            "token": row[0],
            "slug": row[1],
            "created_at": row[2],
            "expires_at": row[3],
            "valid": bool(row[4]),
        }
        for row in rows
    ]
    return jsonify({"tokens": tokens})
