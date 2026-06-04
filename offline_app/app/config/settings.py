"""Local configuration loaded from offline_app/config.json."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.paths import config_path, ensure_app_dirs

logger = logging.getLogger(__name__)

DEFAULT_LOOT_TABLE_DISPLAY_SCALE = 0.75
MIN_LOOT_TABLE_DISPLAY_SCALE = 0.05
MAX_LOOT_TABLE_DISPLAY_SCALE = 1.0

DEFAULT_RARITY_MULTIPLIERS: dict[str, float] = {
    "common": 1.0,
    "uncommon": 1.0,
    "rare": 1.0,
    "legendary": 1.0,
    "divine": 2.0,
    "shiny": 1.0,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "player_name": "Player",
    "player_data_file": "data/player.json",
    "loot_table_variant": "normal",
    "include_skins": False,
    "include_limited": False,
    "loot_table_display_scale": DEFAULT_LOOT_TABLE_DISPLAY_SCALE,
    "points_settings": {
        "rarity_multipliers": deepcopy(DEFAULT_RARITY_MULTIPLIERS),
    },
    "logging": {
        "level": "INFO",
        "log_to_file": True,
    },
}


@dataclass
class AppConfig:
    player_name: str = "Player"
    player_data_file: str = "data/player.json"
    loot_table_variant: str = "normal"
    include_skins: bool = False
    include_limited: bool = False
    loot_table_display_scale: float = DEFAULT_LOOT_TABLE_DISPLAY_SCALE
    rarity_multipliers: dict[str, float] = field(default_factory=lambda: deepcopy(DEFAULT_RARITY_MULTIPLIERS))
    log_level: str = "INFO"
    log_to_file: bool = True

    def guild_config_stub(self) -> dict[str, Any]:
        """Shape compatible with upstream calc_points / points helpers."""
        return {
            "points_settings": {
                "rarity_multipliers": dict(self.rarity_multipliers),
            }
        }

    def resolved_player_path(self, app_root: Path) -> Path:
        path = Path(self.player_data_file)
        if path.is_absolute():
            return path
        return app_root / path


def normalize_loot_table_display_scale(value: float) -> float:
    return max(
        MIN_LOOT_TABLE_DISPLAY_SCALE,
        min(MAX_LOOT_TABLE_DISPLAY_SCALE, float(value)),
    )


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> AppConfig:
    ensure_app_dirs()
    path = config_path()
    raw = deepcopy(DEFAULT_CONFIG)

    if path.exists():
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError("config root must be a JSON object")
            raw = _merge_dict(raw, loaded)
        except json.JSONDecodeError as exc:
            logger.error("Config file is corrupt (%s): %s", path, exc)
            raise ValueError(f"Could not parse {path.name}: {exc}") from exc
    else:
        save_config(_config_from_raw(raw))
        logger.info("Created default config at %s", path)

    return _config_from_raw(raw)


def _config_from_raw(raw: dict[str, Any]) -> AppConfig:
    points = raw.get("points_settings") or {}
    multipliers = points.get("rarity_multipliers") or DEFAULT_RARITY_MULTIPLIERS
    logging_cfg = raw.get("logging") or {}
    return AppConfig(
        player_name=str(raw.get("player_name", "Player")),
        player_data_file=str(raw.get("player_data_file", "data/player.json")),
        loot_table_variant=str(raw.get("loot_table_variant", "normal")),
        include_skins=bool(raw.get("include_skins", False)),
        include_limited=bool(raw.get("include_limited", False)),
        loot_table_display_scale=normalize_loot_table_display_scale(
            float(raw.get("loot_table_display_scale", DEFAULT_LOOT_TABLE_DISPLAY_SCALE))
        ),
        rarity_multipliers={str(k): float(v) for k, v in multipliers.items()},
        log_level=str(logging_cfg.get("level", "INFO")),
        log_to_file=bool(logging_cfg.get("log_to_file", True)),
    )


def save_config(config: AppConfig) -> None:
    ensure_app_dirs()
    payload = {
        "player_name": config.player_name,
        "player_data_file": config.player_data_file,
        "loot_table_variant": config.loot_table_variant,
        "include_skins": config.include_skins,
        "include_limited": config.include_limited,
        "loot_table_display_scale": config.loot_table_display_scale,
        "points_settings": {"rarity_multipliers": config.rarity_multipliers},
        "logging": {"level": config.log_level, "log_to_file": config.log_to_file},
    }
    with open(config_path(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
