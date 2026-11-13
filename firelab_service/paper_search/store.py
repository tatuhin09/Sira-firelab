"""Private, bounded SQLite cache for FireLab scholarly-paper references."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, Mapping

from .query import CACHE_SCHEMA_VERSION

DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_CACHE_ENTRIES = 250


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime | None = None) -> str:
    current = value or utc_now()
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("cache timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


class PaperCacheStore:
    def __init__(self, runtime_dir: Path, *, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("cache TTL must be a positive integer")
        self.runtime_dir = Path(runtime_dir).absolute()
        self.db_path = self.runtime_dir / "firelab.sqlite3"
        self.ttl_seconds = ttl_seconds
        self._prepare_paths()
        self._initialize()

    def _prepare_paths(self) -> None:
        parent = self.runtime_dir.parent
        for directory in (parent, self.runtime_dir):
            if os.path.lexists(directory) and directory.is_symlink():
                raise RuntimeError("FireLab runtime directories may not be symlinks")
            if os.path.lexists(directory) and not directory.is_dir():
                raise RuntimeError("FireLab runtime path is not a directory")
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.runtime_dir, 0o700)

        if os.path.lexists(self.db_path):
            info = os.lstat(self.db_path)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise RuntimeError("FireLab database must be a regular non-symlink file")
            os.chmod(self.db_path, 0o600)
        else:
            descriptor = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)

    def _connect(self, *, initialize_wal: bool = False) -> sqlite3.Connection:
        if self.db_path.is_symlink() or (self.db_path.exists() and not self.db_path.is_file()):
            raise RuntimeError("FireLab database path is unsafe")
        connection = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if initialize_wal:
            connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect(initialize_wal=True)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key='schema_version'"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                        (str(CACHE_SCHEMA_VERSION),),
                    )
                else:
                    try:
                        version = int(row["value"])
                    except (TypeError, ValueError):
                        raise RuntimeError("FireLab cache schema version is invalid") from None
                    if version > CACHE_SCHEMA_VERSION or version < CACHE_SCHEMA_VERSION:
                        raise RuntimeError("FireLab cache schema requires an explicit migration")

                connection.execute("""
                    CREATE TABLE IF NOT EXISTS search_cache (
                        cache_key TEXT PRIMARY KEY,
                        normalized_query TEXT NOT NULL CHECK(length(normalized_query) BETWEEN 3 AND 200),
                        retrieved_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        providers_json TEXT NOT NULL,
                        paper_count INTEGER NOT NULL CHECK(paper_count BETWEEN 1 AND 3),
                        partial INTEGER NOT NULL DEFAULT 0 CHECK(partial IN (0,1))
                    )
                """)
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS cached_paper (
                        cache_key TEXT NOT NULL REFERENCES search_cache(cache_key) ON DELETE CASCADE,
                        position INTEGER NOT NULL CHECK(position BETWEEN 0 AND 2),
                        dedupe_key TEXT NOT NULL,
                        paper_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        abstract TEXT,
                        authors_json TEXT NOT NULL,
                        year INTEGER,
                        doi TEXT,
                        url TEXT NOT NULL,
                        open_access_pdf_url TEXT,
                        retrieved_at TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        published_date TEXT,
                        providers_json TEXT NOT NULL,
                        PRIMARY KEY(cache_key, position),
                        UNIQUE(cache_key, dedupe_key)
                    )
                """)
                connection.execute("CREATE INDEX IF NOT EXISTS idx_search_cache_expiry ON search_cache(expires_at)")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        os.chmod(self.db_path, 0o600)

    def get(self, key: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        current = now or utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            try:
                header = connection.execute(
                    "SELECT * FROM search_cache WHERE cache_key=?", (key,)
                ).fetchone()
                if header is None:
                    connection.execute("COMMIT")
                    return None
                rows = connection.execute(
                    "SELECT * FROM cached_paper WHERE cache_key=? ORDER BY position", (key,)
                ).fetchall()
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        try:
            papers = []
            for row in rows:
                papers.append({
                    "paper_id": row["paper_id"],
                    "title": row["title"],
                    "abstract": row["abstract"],
                    "authors": json.loads(row["authors_json"]),
                    "year": row["year"],
                    "doi": row["doi"],
                    "url": row["url"],
                    "open_access_pdf_url": row["open_access_pdf_url"],
                    "retrieved_at": row["retrieved_at"],
                    "provider": row["provider"],
                    "published_date": row["published_date"],
                    "providers": json.loads(row["providers_json"]),
                })
            providers = json.loads(header["providers_json"])
            retrieved = parse_timestamp(header["retrieved_at"])
            expires = parse_timestamp(header["expires_at"])
            if len(papers) != header["paper_count"] or not isinstance(providers, list):
                raise ValueError("cache row shape is invalid")
        except (TypeError, ValueError, json.JSONDecodeError):
            self.delete(key)
            return None
        return {
            "query": header["normalized_query"],
            "retrieved_at": header["retrieved_at"],
            "expires_at": header["expires_at"],
            "fresh": current.astimezone(timezone.utc) < expires,
            "papers": papers,
            "providers": providers,
            "partial": bool(header["partial"]),
        }

    def put(
        self,
        key: str,
        query: str,
        papers: list[Mapping[str, Any]],
        providers: list[str],
        *,
        retrieved_at: datetime | None = None,
        partial: bool = False,
    ) -> dict[str, Any]:
        if not 1 <= len(papers) <= 3:
            raise ValueError("only one to three successful papers may be cached")
        if type(partial) is not bool:
            raise ValueError("partial flag must be boolean")
        now = retrieved_at or utc_now()
        retrieved_text = timestamp(now)
        expires_text = timestamp(now + timedelta(seconds=self.ttl_seconds))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM search_cache WHERE cache_key=?", (key,))
            connection.execute(
                "INSERT INTO search_cache(cache_key, normalized_query, retrieved_at, expires_at, providers_json, paper_count, partial) VALUES(?,?,?,?,?,?,?)",
                (key, query, retrieved_text, expires_text, json.dumps(providers), len(papers), int(partial)),
            )
            for position, paper in enumerate(papers):
                connection.execute("""
                    INSERT INTO cached_paper(
                        cache_key, position, dedupe_key, paper_id, title, abstract,
                        authors_json, year, doi, url, open_access_pdf_url,
                        retrieved_at, provider, published_date, providers_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    key, position, str(paper["dedupe_key"]), paper["paper_id"],
                    paper["title"], paper.get("abstract"),
                    json.dumps(paper.get("authors", []), ensure_ascii=False),
                    paper.get("year"), paper.get("doi"), paper["url"],
                    paper.get("open_access_pdf_url"), paper["retrieved_at"],
                    paper["provider"], paper.get("published_date"),
                    json.dumps(paper.get("providers", [])),
                ))
            # Keep persistent growth bounded; newest retrieved entries survive.
            connection.execute("""
                DELETE FROM search_cache WHERE cache_key IN (
                    SELECT cache_key FROM search_cache
                    ORDER BY retrieved_at DESC LIMIT -1 OFFSET ?
                )
            """, (MAX_CACHE_ENTRIES,))
            connection.execute("COMMIT")
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            connection.close()
        os.chmod(self.db_path, 0o600)
        result = self.get(key, now=now)
        if result is None:
            raise RuntimeError("stored cache entry could not be read back")
        return result

    def delete(self, key: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM search_cache WHERE cache_key=?", (key,))
