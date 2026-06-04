"""Adapter to shared repository assets and safe imports."""

from __future__ import annotations

from pathlib import Path

from app.paths import add_repo_to_path, repo_root


def loot_csv_path() -> Path:
    return repo_root() / "rotmg_loot_drops_updated.csv"


def lootsummary_dir() -> Path:
    return repo_root() / "helper_pics" / "lootsummary_pics"


def dungeon_pics_dir() -> Path:
    return repo_root() / "helper_pics" / "dungeon_pics"


def app_icon_path() -> Path:
    return dungeon_pics_dir() / "_misc" / "Foreman's Hard Hat.png"


def rarity_pics_dir() -> Path:
    return repo_root() / "helper_pics" / "rarity_pics"


def ensure_repo_imports() -> None:
    add_repo_to_path()
