"""Render loot table images using shared repo assets (no Discord)."""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

from PIL import Image

from app.core_adapter.loot_catalog import normalize_item_name
from app.core_adapter.repo_paths import (
    dungeon_pics_dir,
    ensure_repo_imports,
    loot_csv_path,
    lootsummary_dir,
)
from app.paths import repo_root, working_directory

logger = logging.getLogger(__name__)

LootSourceItems = Sequence[tuple[str, bool] | tuple[str, bool, str]]

REQUIRED_VARIANTS = ("normal", "normal_skins", "normal_limited", "all")


@dataclass(frozen=True)
class RenderResult:
    image: Image.Image
    variant: str
    items_placed: int
    items_not_found: list[str]
    items_excluded: list[str]
    warnings: list[str]


def variant_from_flags(include_skins: bool, include_limited: bool) -> str:
    if include_skins and include_limited:
        return "all"
    if include_skins:
        return "normal_skins"
    if include_limited:
        return "normal_limited"
    return "normal"


def _variant_asset_paths(variant: str) -> tuple[str, str]:
    base = lootsummary_dir()
    sprite_csv = str(base / f"sprite_positions_{variant}.csv")
    background_file = str(base / f"loot_background_{variant}.png")
    return sprite_csv, background_file


def assets_present() -> bool:
    for variant in REQUIRED_VARIANTS:
        sprite_csv, background_file = _variant_asset_paths(variant)
        if not os.path.exists(sprite_csv) or not os.path.exists(background_file):
            return False
    return True


def ensure_assets() -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if assets_present():
        return True, warnings

    if not dungeon_pics_dir().exists():
        warnings.append(
            "Dungeon item sprites are missing (helper_pics/dungeon_pics/). "
            "Download them from the project README/Google Drive link, then restart."
        )
        return False, warnings

    if not loot_csv_path().exists():
        warnings.append("rotmg_loot_drops_updated.csv was not found in the repository root.")
        return False, warnings

    logger.info("Generating loot summary assets from dungeon sprites...")
    try:
        with working_directory(repo_root()):
            from create_loot_table import create_loot_background_and_mapping

            create_loot_background_and_mapping()
    except Exception as exc:
        logger.exception("Failed to generate loot summary assets")
        warnings.append(f"Could not build loot table backgrounds: {exc}")
        return False, warnings

    ready = assets_present()
    if not ready:
        warnings.append(
            "Loot table backgrounds are still missing after generation. "
            "Ensure dungeon sprites exist for catalog items."
        )
    return ready, warnings


def _lookup_key(name: str) -> str:
    return normalize_item_name(name).casefold()


@lru_cache(maxsize=16)
def _load_sprite_positions(sprite_csv: str) -> dict[str, dict[str, int]]:
    positions: dict[str, dict[str, int]] = {}
    with open(sprite_csv, encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = _lookup_key(row["item_name"])
            positions[key] = {
                "pixel_x": int(row["pixel_x"]),
                "pixel_y": int(row["pixel_y"]),
            }
    return positions


@lru_cache(maxsize=1)
def _load_item_type_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    with open(loot_csv_path(), encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            lookup[_lookup_key(row["Item Name"])] = row["Loot Type"].strip().lower()
    return lookup


def _is_in_variant(item_type: str, variant: str) -> bool:
    if variant == "all":
        return True
    if variant == "normal":
        return item_type not in {"skin", "limited"}
    if variant == "normal_skins":
        return item_type != "limited"
    if variant == "normal_limited":
        return item_type != "skin"
    return True


def _collapse_to_highest_rarity(source_items: LootSourceItems) -> list[tuple[str, str, bool, str]]:
    ensure_repo_imports()
    from utils.loot_constants import rarity_rank

    collapsed: dict[tuple[str, bool], tuple[str, str, bool, str]] = {}
    for entry in source_items:
        raw_name = str(entry[0]).strip()
        shiny = bool(entry[1])
        rarity = str(entry[2]).strip().lower() if len(entry) > 2 else "common"
        normalized_name = _lookup_key(raw_name)
        if not normalized_name:
            continue
        key = (normalized_name, shiny)
        existing = collapsed.get(key)
        if existing is None:
            collapsed[key] = (raw_name, normalized_name, shiny, rarity)
        elif rarity_rank(rarity) > rarity_rank(existing[3]):
            collapsed[key] = (existing[0], normalized_name, shiny, rarity)
    return list(collapsed.values())


def render_loot_table(
    source_items: LootSourceItems,
    *,
    include_skins: bool = False,
    include_limited: bool = False,
) -> RenderResult:
    ensure_repo_imports()
    from utils.image_utils import overlay_rarity_badge_on_image, resolve_item_image_path

    warnings: list[str] = []
    ready, asset_warnings = ensure_assets()
    warnings.extend(asset_warnings)
    if not ready:
        raise RuntimeError("\n".join(warnings) or "Loot table assets are unavailable.")

    variant = variant_from_flags(include_skins, include_limited)
    sprite_csv, background_file = _variant_asset_paths(variant)
    sprite_positions = _load_sprite_positions(sprite_csv)
    item_type_lookup = _load_item_type_lookup()

    collapsed_items = _collapse_to_highest_rarity(source_items)
    normalized_items: list[tuple[str, str, bool, str, str]] = []
    items_excluded: list[str] = []

    for raw_name, normalized_name, shiny, rarity in collapsed_items:
        display_name = f"{raw_name} (shiny)" if shiny else raw_name
        item_type = item_type_lookup.get(normalized_name, "")
        normalized_items.append((raw_name, normalized_name, shiny, item_type, rarity))
        if not _is_in_variant(item_type, variant):
            items_excluded.append(display_name)

    with Image.open(background_file) as base:
        background = base.copy()

    items_placed = 0
    items_not_found: list[str] = []
    render_candidates: dict[str, tuple[str, str, bool, str]] = {}

    for raw_name, normalized_name, shiny, item_type, rarity in normalized_items:
        if not _is_in_variant(item_type, variant):
            continue
        sprite_key = f"{normalized_name} (shiny)" if shiny else normalized_name
        existing = render_candidates.get(sprite_key)
        if existing is None or _rarity_rank(rarity) > _rarity_rank(existing[3]):
            render_candidates[sprite_key] = (raw_name, normalized_name, shiny, rarity)

    for sprite_key, (raw_name, normalized_name, shiny, rarity) in render_candidates.items():
        display_name = f"{raw_name} (shiny)" if shiny else raw_name
        if sprite_key not in sprite_positions:
            items_not_found.append(display_name)
            continue

        sprite_path = resolve_item_image_path(raw_name, shiny)
        if not sprite_path:
            items_not_found.append(display_name)
            continue

        try:
            with Image.open(sprite_path) as img:
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                if img.size != (40, 40):
                    img = img.resize((40, 40), Image.Resampling.LANCZOS)
                sprite = img.copy()
            sprite = overlay_rarity_badge_on_image(sprite, rarity) or sprite
            pos = sprite_positions[sprite_key]
            background.paste(sprite, (pos["pixel_x"], pos["pixel_y"]), sprite)
            items_placed += 1
        except Exception as exc:
            logger.warning("Failed to render sprite for %s: %s", sprite_key, exc)
            items_not_found.append(display_name)

    return RenderResult(
        image=background,
        variant=variant,
        items_placed=items_placed,
        items_not_found=items_not_found,
        items_excluded=items_excluded,
        warnings=warnings,
    )


def _rarity_rank(value: str) -> int:
    ensure_repo_imports()
    from utils.loot_constants import rarity_rank

    return rarity_rank(value)
