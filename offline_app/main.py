"""Offline RotMG PPE loot tracker entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def _ensure_import_path() -> None:
    app_root = Path(__file__).resolve().parent
    app_root_str = str(app_root)
    if app_root_str not in sys.path:
        sys.path.insert(0, app_root_str)


def main() -> int:
    _ensure_import_path()

    from app.config.logging_setup import setup_logging
    from app.config.settings import load_config
    from app.paths import app_dir, ensure_app_dirs
    from app.storage.player_store import PlayerStore
    from app.ui.main_window import run_app

    ensure_app_dirs()

    try:
        config = load_config()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    setup_logging(config)
    logger = logging.getLogger(__name__)

    store = PlayerStore(config.resolved_player_path(app_dir()))
    try:
        player = store.load(default_name=config.player_name)
    except ValueError as exc:
        logger.error("%s", exc)
        print(str(exc), file=sys.stderr)
        return 1

    if not player.player_name:
        player.player_name = config.player_name

    logger.info("Starting offline loot tracker (data: %s)", store.path)
    run_app(config, store, player)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
