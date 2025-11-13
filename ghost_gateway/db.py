from __future__ import annotations

import datetime
import json
import os
import sqlite3
import uuid
from typing import Iterable, List, Optional, Tuple

from .config import settings


def get_connection():
    return sqlite3.connect(settings.db_path)


def enforce_access_log_retention(conn: sqlite3.Connection, days: Optional[int] = None) -> int:
    retention_days = settings.access_log_retention_days if days is None else days
    if retention_days is None or retention_days <= 0:
        return 0
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)).isoformat()
    cursor = conn.execute(
        "DELETE FROM access_logs WHERE accessed_at < ?",
        (cutoff,)
    )
    conn.commit()
    return cursor.rowcount


def ensure_core_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            extras TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            article_id INTEGER NOT NULL,
            guest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT,
            valid INTEGER NOT NULL DEFAULT 1,
            extras TEXT,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            guest TEXT,
            provider TEXT,
            provider_tx_id TEXT,
            created_at TEXT NOT NULL,
            extras TEXT,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        )
    """)
    conn.commit()


def get_or_create_article(slug: str, conn: Optional[sqlite3.Connection] = None, extras: Optional[dict] = None):
    if not slug:
        raise ValueError("slug is required")
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        row = conn.execute("SELECT id FROM articles WHERE slug = ?", (slug,)).fetchone()
        if row:
            return row[0]
        now = datetime.datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO articles (slug, created_at, extras) VALUES (?, ?, ?)",
            (slug, now, json.dumps(extras or {}))
        )
        conn.commit()
        return conn.execute("SELECT id FROM articles WHERE slug = ?", (slug,)).fetchone()[0]
    finally:
        if close_conn:
            conn.close()




def bootstrap_database():
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    with get_connection() as conn:
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
                FOREIGN KEY (token) REFERENCES access_tokens(token)
            )
        """)
        conn.commit()

        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(access_logs)").fetchall()
        }
        if "referer_domain" not in columns:
            conn.execute("ALTER TABLE access_logs ADD COLUMN referer_domain TEXT")
            conn.commit()

        ensure_core_tables(conn)

        if settings.access_log_retention_days > 0:
            enforce_access_log_retention(conn)


def is_referrer_allowed(ref: str) -> bool:
    if not ref:
        return False
    with get_connection() as conn:
        row = conn.execute(
            "SELECT active FROM allowed_referrers WHERE referrer = ?",
            (ref,)
        ).fetchone()
        return row is not None and row[0] == 1


def ensure_referrer(ref: str) -> bool:
    if not ref:
        return False
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO allowed_referrers (referrer, created_at, active) VALUES (?, ?, 1)",
            (ref, now)
        )
        conn.execute(
            "UPDATE allowed_referrers SET active = 1 WHERE referrer = ?",
            (ref,)
        )
        conn.commit()
    return True


def is_post_allowed_for_ref(ref: str, slug: str) -> bool:
    if not ref or not slug:
        return False
    with get_connection() as conn:
        row = conn.execute(
            "SELECT active FROM referrer_posts WHERE referrer = ? AND slug = ?",
            (ref, slug)
        ).fetchone()
        return row is not None and row[0] == 1


def ensure_post_access(ref: str, slug: str) -> bool:
    if not ref or not slug:
        return False
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO referrer_posts (referrer, slug, active, created_at) VALUES (?, ?, 1, ?)",
            (ref, slug, now)
        )
        conn.commit()
    return True


def normalize_ref_list(single_value=None, plural_value: Optional[Iterable[str]] = None) -> List[str]:
    refs: List[str] = []

    def ingest(raw):
        if raw is None:
            return
        if isinstance(raw, (list, tuple)):
            for item in raw:
                ingest(item)
            return
        if not isinstance(raw, str):
            return
        tokenized = raw.replace("\n", ",").split(",")
        for token in tokenized:
            cleaned = token.strip()
            if cleaned:
                refs.append(cleaned)

    ingest(plural_value)
    ingest(single_value)
    deduped = []
    seen = set()
    for value in refs:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def create_token(slug: str, ref: str, expires_days_param=None, expires_at_param=None):
    if not slug or not ref:
        raise ValueError("slug and ref are required")

    ensure_referrer(ref)
    ensure_post_access(ref, slug)

    if not is_referrer_allowed(ref):
        raise PermissionError("Referrer not allowed")
    if not is_post_allowed_for_ref(ref, slug):
        raise PermissionError("Slug not allowed for this referrer")

    created = datetime.datetime.utcnow()
    if expires_at_param:
        try:
            expires = datetime.datetime.fromisoformat(expires_at_param)
            expires_iso = expires.isoformat()
        except Exception:
            raise ValueError("Invalid expires_at format. Use YYYY-MM-DD")
    elif expires_days_param:
        try:
            days = int(expires_days_param)
            if days == 0:
                expires_iso = None
            else:
                expires = created + datetime.timedelta(days=days)
                expires_iso = expires.isoformat()
        except Exception:
            raise ValueError("Invalid expires_days format. Must be a number")
    elif settings.token_expiry_days == 0:
        expires_iso = None
    else:
        expires = created + datetime.timedelta(days=settings.token_expiry_days)
        expires_iso = expires.isoformat()

    article_id = get_or_create_article(slug)
    token = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO access_tokens (token, article_id, guest, created_at, expires_at, extras)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (token, article_id, ref, created.isoformat(), expires_iso, json.dumps({}))
        )
        conn.commit()

    return {
        "slug": slug,
        "ref": ref,
        "token": token,
        "token_url": f"{settings.app_base_url}/read/{token}",
        "expires_at": expires_iso or "Never"
    }


def create_tokens_for_refs(slug: str, refs: Iterable[str], expires_days=None, expires_at=None):
    return [create_token(slug, ref, expires_days, expires_at) for ref in refs]


def extract_referer_domain(raw_referer: Optional[str]) -> Optional[str]:
    if not raw_referer:
        return None
    from urllib.parse import urlparse

    try:
        parsed = urlparse(raw_referer)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def daterange(start_date: datetime.date, end_date: datetime.date):
    start_dt = datetime.datetime.combine(start_date, datetime.time.min)
    end_dt = datetime.datetime.combine(end_date, datetime.time.max)
    return start_dt, end_dt


def get_preset_range(name: Optional[str]):
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


def parse_iso8601(value: Optional[str]):
    if not value:
        return None
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(cleaned)
    except Exception:
        return None


def fetch_access_logs(limit=100, offset=0, ref=None, token=None, since=None, until=None, order="desc"):
    clauses = []
    params: List = []
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
    with get_connection() as conn:
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
