"""Application path helpers (relative to offline_app/, no hardcoded absolute paths)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory containing offline_app/ (this package's parent)."""
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    """Parent repository root (sibling of offline_app/)."""
    return app_dir().parent


def data_dir() -> Path:
    return app_dir() / "data"


def logs_dir() -> Path:
    return app_dir() / "logs"


def config_path() -> Path:
    return app_dir() / "config.json"


def default_player_path() -> Path:
    return data_dir() / "player.json"


def ensure_app_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)


def add_repo_to_path() -> Path:
    """Expose the parent repo on sys.path for safe shared imports."""
    root = repo_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def working_directory(path: Path | None = None):
    """Context manager: temporarily chdir (used when upstream code expects repo cwd)."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        previous = os.getcwd()
        target = path or repo_root()
        os.chdir(target)
        try:
            yield target
        finally:
            os.chdir(previous)

    return _ctx()
