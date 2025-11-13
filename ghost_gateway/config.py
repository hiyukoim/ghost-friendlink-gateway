from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix


@dataclass(frozen=True)
class Settings:
    db_path: str
    app_version: str
    ghost_url: str
    ghost_admin_key: str
    ghost_content_api_key: str
    app_base_url: str
    default_redirect: str
    custom_css_url: str
    home_redirect_url: str
    site_title: str
    site_description: str
    site_icon_url: str
    site_logo_url: str
    token_expiry_days: int
    admin_api_key: str
    access_log_retention_days: int
    admin_login_username: str
    admin_login_password: str
    admin_session_hours: int
    max_bulk_refs: int
    default_rate_limit: Optional[str]
    admin_rate_limit: Optional[str]
    generate_rate_limit: Optional[str]
    enforce_https: bool
    proxy_forwarded_for: int
    proxy_forwarded_proto: int
    host: str
    port: int
    debug: bool
    flask_secret: str
    app_ui_folder: Path

VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def _detect_version() -> str:
    file_version = _version_from_file()
    if file_version:
        return file_version
    return "dev"


def _version_from_file() -> Optional[str]:
    try:
        data = VERSION_FILE.read_text().strip()
        return data or None
    except FileNotFoundError:
        return None


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


def load_settings() -> Settings:
    ghost_url = os.getenv("GHOST_URL", "https://example.com")
    app_ui_folder = Path(__file__).resolve().parent.parent / "app_ui"
    return Settings(
        db_path=os.getenv("DB_PATH", "data/tokens.db"),
        app_version=_detect_version(),
        ghost_url=ghost_url,
        ghost_admin_key=os.getenv("GHOST_ADMIN_KEY", "").strip(),
        ghost_content_api_key=os.getenv("GHOST_CONTENT_API_KEY", "").strip(),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:5000"),
        default_redirect=os.getenv("DEFAULT_REDIRECT", f"{ghost_url}/#/portal/signup"),
        custom_css_url=os.getenv("CUSTOM_CSS_URL", "").strip(),
        home_redirect_url=os.getenv("HOME_REDIRECT_URL", "").strip(),
        site_title=os.getenv("SITE_TITLE", "").strip(),
        site_description=os.getenv("SITE_DESCRIPTION", "").strip(),
        site_icon_url=os.getenv("SITE_ICON_URL", "").strip(),
        site_logo_url=os.getenv("SITE_LOGO_URL", "").strip(),
        token_expiry_days=int(os.getenv("TOKEN_EXPIRY_DAYS", "0")),
        admin_api_key=os.getenv("ADMIN_API_KEY", "").strip(),
        access_log_retention_days=int(os.getenv("ACCESS_LOG_RETENTION_DAYS", "60")),
        admin_login_username=os.getenv("ADMIN_LOGIN_USERNAME", "admin").strip(),
        admin_login_password=os.getenv(
            "ADMIN_LOGIN_PASSWORD",
            os.getenv("ADMIN_API_KEY", "").strip() or "admin",
        ).strip(),
        admin_session_hours=int(os.getenv("ADMIN_SESSION_HOURS", "12")),
        max_bulk_refs=int(os.getenv("MAX_BULK_REFS", "25")),
        default_rate_limit=os.getenv("DEFAULT_RATE_LIMIT", "240/hour"),
        admin_rate_limit=os.getenv("ADMIN_RATE_LIMIT", "60/minute"),
        generate_rate_limit=os.getenv("GENERATE_RATE_LIMIT", "20/minute"),
        enforce_https=_env_bool("ENFORCE_HTTPS", "true"),
        proxy_forwarded_for=int(os.getenv("PROXY_FORWARDED_FOR", "1")),
        proxy_forwarded_proto=int(os.getenv("PROXY_FORWARDED_PROTO", "1")),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=_env_bool("APP_DEBUG"),
        flask_secret=os.getenv("FLASK_SECRET", os.getenv("ADMIN_API_KEY", "change-me")),
        app_ui_folder=app_ui_folder,
    )


limiter = Limiter(get_remote_address, default_limits=[])


def configure_app(app: Flask, settings: Settings) -> None:
    app.secret_key = settings.flask_secret
    if settings.app_ui_folder.exists():
        app.jinja_loader.searchpath.insert(0, str(settings.app_ui_folder))
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.enforce_https,
        PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=settings.admin_session_hours),
    )
    limiter.init_app(app)
    if settings.default_rate_limit:
        limiter.default_limits = [settings.default_rate_limit]
    if settings.proxy_forwarded_for or settings.proxy_forwarded_proto:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=settings.proxy_forwarded_for,
            x_proto=settings.proxy_forwarded_proto,
        )


settings = load_settings()
