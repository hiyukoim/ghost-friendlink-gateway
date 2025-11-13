from __future__ import annotations

from flask import Flask

from .admin import admin_bp
from .public import public_bp


def register_blueprints(app: Flask) -> None:
    """Attach all application blueprints to the Flask app."""
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
