"""Maintenance commands.

    docker compose exec app python -m app.cli reset-pin

``reset-pin`` removes a PIN that was changed in the operator dashboard, so
OPERATOR_PIN from .env (default 1113) applies again.
"""

from __future__ import annotations

import sys

from .config import get_settings
from .db import Database
from .services.settings_store import SettingsStore


def reset_pin() -> int:
    env = get_settings()
    db = Database(env.database_url)
    db.migrate()
    store = SettingsStore(db, env)
    store.load()
    store.update({"operator_pin_hash": None})
    print("Operator PIN reset: the OPERATOR_PIN from .env (default 1113) applies again.")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:2] == ["reset-pin"]:
        return reset_pin()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
