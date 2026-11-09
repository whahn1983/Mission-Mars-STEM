"""Alembic environment.

Migrations run automatically at application start (see app/db.py). To run
them by hand inside the container:

    docker compose exec app alembic -c /app/alembic.ini upgrade head
"""

from __future__ import annotations

import logging

from alembic import context
from sqlalchemy import create_engine, pool

from app.models import Base

config = context.config
target_metadata = Base.metadata

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    from logging.config import fileConfig

    fileConfig(config.config_file_name, disable_existing_loggers=False)

log = logging.getLogger("alembic.env")


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        from app.config import get_settings

        url = get_settings().database_url
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
