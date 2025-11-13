from __future__ import annotations

from flask import Flask, jsonify, request

from ghost_gateway import db as db_utils
from ghost_gateway.config import configure_app, settings
from ghost_gateway.routes import register_blueprints


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder="templates/assets",
        static_url_path="/assets",
    )
    configure_app(app, settings)
    db_utils.bootstrap_database()
    register_blueprints(app)

    @app.before_request
    def enforce_https_requirement():
        if not settings.enforce_https:
            return None
        proto = request.headers.get("X-Forwarded-Proto")
        if request.is_secure or proto == "https":
            return None
        if request.path.startswith("/health"):
            return None
        return jsonify({"error": "HTTPS is required"}), 400

    return app


__all__ = ["create_app"]
