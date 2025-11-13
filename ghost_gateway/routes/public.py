from __future__ import annotations

import datetime

import requests
from flask import Blueprint, current_app, redirect, render_template, request

from ghost_gateway import db as db_utils
from ghost_gateway import ghost as ghost_utils
from ghost_gateway.config import settings

public_bp = Blueprint("public", __name__)

DEFAULT_REDIRECT = settings.default_redirect
CUSTOM_CSS_URL = settings.custom_css_url
ACCESS_LOG_RETENTION_DAYS = settings.access_log_retention_days


@public_bp.route("/")
def index():
    redirect_target = settings.home_redirect_url
    if redirect_target:
        return redirect(redirect_target)
    return render_template("index.html")


@public_bp.route("/read/<token>")
def read_post(token):
    with db_utils.get_connection() as conn:
        row = conn.execute(
            """
            SELECT a.slug, at.guest, at.valid, at.expires_at
            FROM access_tokens at
            JOIN articles a ON a.id = at.article_id
            WHERE at.token = ?
            """,
            (token,),
        ).fetchone()

    if not row or row[2] != 1:
        return redirect(DEFAULT_REDIRECT)

    slug, ref, valid, expires_at = row
    if not valid:
        return redirect(DEFAULT_REDIRECT)
    if expires_at and datetime.datetime.utcnow() > datetime.datetime.fromisoformat(expires_at):
        return redirect(DEFAULT_REDIRECT)
    if not ref or not db_utils.is_referrer_allowed(ref):
        return redirect(DEFAULT_REDIRECT)
    if not db_utils.is_post_allowed_for_ref(ref, slug):
        return redirect(DEFAULT_REDIRECT)

    if ACCESS_LOG_RETENTION_DAYS != 0:
        ip_address = request.remote_addr
        user_agent = request.headers.get("User-Agent", "")
        referer_domain = db_utils.extract_referer_domain(request.headers.get("Referer"))
        with db_utils.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO access_logs (token, referrer, ip_address, user_agent, accessed_at, referer_domain)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    ref,
                    ip_address,
                    user_agent,
                    datetime.datetime.utcnow().isoformat(),
                    referer_domain,
                ),
            )
            conn.commit()
            if ACCESS_LOG_RETENTION_DAYS > 0:
                db_utils.enforce_access_log_retention(conn)

    try:
        jwt_token = ghost_utils.make_ghost_admin_jwt()
    except Exception:  # pragma: no cover - misconfigured key
        current_app.logger.exception("Failed to build Ghost admin JWT for slug %s", slug)
        return redirect(f"{settings.ghost_url}/{slug}/")
    headers = {"Authorization": f"Ghost {jwt_token}"}
    try:
        response = requests.get(
            ghost_utils.ghost_api_url(slug), headers=headers, timeout=10
        )
    except Exception:  # pragma: no cover - network failure
        current_app.logger.exception("Ghost API request failed for slug %s", slug)
        return redirect(f"{settings.ghost_url}/{slug}/")
    if response.status_code != 200:
        current_app.logger.error(
            "Ghost API error %s when fetching slug %s: %s",
            response.status_code,
            slug,
            response.text[:200],
        )
        return redirect(f"{settings.ghost_url}/{slug}/")

    post_data = response.json()["posts"][0]
    site = ghost_utils.get_ghost_site_settings()
    custom_css = CUSTOM_CSS_URL or None
    return render_template(
        "post.html",
        post=post_data,
        site=site,
        ghost_url=settings.ghost_url,
        custom_css_url=custom_css,
        ref=ref,
    )
