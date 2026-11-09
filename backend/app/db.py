"""Database engine, session factory and migration runner."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def _sqlite_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
    cur = dbapi_connection.cursor()
    # WAL keeps the database consistent if the container is stopped abruptly
    # and lets the UI read history while a test is being written.
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url[len("sqlite:///") :])
        if str(db_path) not in ("", ":memory:"):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 10},
            pool_pre_ping=True,
        )
        event.listen(engine, "connect", _sqlite_pragmas)
        return engine
    return create_engine(database_url, pool_pre_ping=True)


def run_migrations(database_url: str) -> None:
    """Upgrade the database schema to the latest Alembic revision."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["configure_logger"] = False
    log.info("Applying database migrations")
    command.upgrade(cfg, "head")


class Database:
    def __init__(self, database_url: str) -> None:
        self.url = database_url
        self.engine = make_engine(database_url)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def migrate(self) -> None:
        run_migrations(self.url)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def dispose(self) -> None:
        self.engine.dispose()
