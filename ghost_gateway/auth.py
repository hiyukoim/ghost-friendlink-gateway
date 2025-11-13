from __future__ import annotations

import hmac
import secrets

from flask import Response, jsonify, redirect, request, session, url_for

from .config import settings


def check_admin_auth() -> bool:
    if session.get("is_admin"):
        return True
    auth_header = request.headers.get("Authorization", "")
    if settings.admin_api_key and auth_header.startswith("Bearer "):
        provided_key = auth_header[7:]
        if provided_key == settings.admin_api_key:
            return True
    return False


def has_valid_admin_bearer() -> bool:
    if not settings.admin_api_key:
        return False
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        provided_key = auth_header[7:]
        return provided_key == settings.admin_api_key
    return False


def get_or_create_csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def validate_csrf_token():
    if not session.get("is_admin"):
        return False
    token = session.get("csrf_token")
    if not token:
        return False
    provided = request.headers.get("X-Admin-CSRF") or request.form.get("csrf_token")
    if not provided:
        return False
    return hmac.compare_digest(token, provided)


def require_session_csrf(json_response=True):
    if not session.get("is_admin"):
        return None
    if has_valid_admin_bearer():
        return None
    if validate_csrf_token():
        return None
    if json_response:
        return jsonify({"error": "Missing or invalid CSRF token"}), 400
    return Response("Missing or invalid CSRF token", 400)


def redirect_to_login():
    if session.get("is_admin"):
        return None
    next_url = request.path
    return redirect(url_for("admin.admin_login", next=next_url))
