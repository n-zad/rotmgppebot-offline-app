"""Loot catalog and validation without Discord dependencies."""

from __future__ import annotations

import csv
import logging
import re
from functools import lru_cache
from typing import Iterable

from app.core_adapter.repo_paths import ensure_repo_imports, loot_csv_path

logger = logging.getLogger(__name__)

NON_EQUIPMENT_LOOT_TYPES = frozenset(
    {
        "skin",
        "limited",
        "item",
    }
)

_APOSTROPHE_VARIANTS = "\u2018\u2019\u02bc\u2032\u00b4`"
_DASH_VARIANTS = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

EXCEPTIONS = {"of", "the", "in", "and", "for", "to", "a", "an"}


def normalize_item_name(name: str) -> str:
    if not name:
        return ""
    normalized = name
    for apostrophe in _APOSTROPHE_VARIANTS:
        normalized = normalized.replace(apostrophe, "'")
    for dash in _DASH_VARIANTS:
        normalized = normalized.replace(dash, "-")
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    return " ".join(normalized.split()).strip()


def _pretty_item_name(internal_name: str) -> str:
    words = internal_name.split(" ")
    return " ".join(
        word.lower() if word.lower() in EXCEPTIONS and index != 0 else word
        for index, word in enumerate(words)
    )


@lru_cache(maxsize=1)
def _load_catalog_rows() -> tuple[dict[str, dict[str, str | float]], list[str]]:
    path = loot_csv_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Loot catalog not found at {path.name}. Run the app from the repository checkout."
        )

    entries: dict[str, dict[str, str | float]] = {}
    display_names: list[str] = []

    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_name = (row.get("Item Name") or "").strip()
            raw_points = (row.get("Points") or "").strip()
            loot_type = (row.get("Loot Type") or "").strip()
            if not raw_name or not raw_points:
                continue
            normalized = normalize_item_name(raw_name)
            try:
                points = float(raw_points)
            except ValueError:
                continue
            entries[normalized] = {
                "display_name": _pretty_item_name(normalized),
                "loot_type": loot_type.lower(),
                "points": points,
            }
            if "(shiny)" not in normalized.lower():
                display_names.append(_pretty_item_name(normalized))

    display_names.sort(key=str.casefold)
    logger.info("Loaded %d loot items from catalog", len(display_names))
    return entries, display_names


def get_item_names() -> list[str]:
    return list(_load_catalog_rows()[1])


def get_known_items_set() -> set[str]:
    return set(get_item_names())


def lookup_item(item_name: str) -> dict[str, str | float] | None:
    normalized = normalize_item_name(item_name)
    return _load_catalog_rows()[0].get(normalized)


def is_equipment(item_name: str) -> bool:
    entry = lookup_item(item_name)
    if not entry:
        return False
    return str(entry["loot_type"]) not in NON_EQUIPMENT_LOOT_TYPES


def has_shiny_variant(item_name: str) -> bool:
    normalized = normalize_item_name(item_name)
    shiny_key = normalize_item_name(f"{normalized} (shiny)")
    return shiny_key in _load_catalog_rows()[0]


def validate_loot_input(item_name: str, *, shiny: bool) -> None:
    known = get_known_items_set()
    if item_name not in known:
        raise ValueError(
            f"'{item_name}' is not a recognized item name. "
            "Choose an item from the catalog list."
        )
    if shiny and not has_shiny_variant(item_name):
        raise ValueError(f"Shiny variant of '{item_name}' is not in the catalog.")


def filter_item_names(query: str, limit: int = 50) -> list[str]:
    query_cf = query.casefold().strip()
    names = get_item_names()
    if not query_cf:
        return names[:limit]
    return [name for name in names if query_cf in name.casefold()][:limit]


def calc_item_points(
    item_name: str,
    *,
    shiny: bool,
    rarity: str,
    rarity_multipliers: dict[str, float],
) -> float:
    ensure_repo_imports()
    from utils.loot_constants import normalize_rarity

    entry = lookup_item(item_name)
    if not entry:
        return 0.0

    base_key = normalize_item_name(item_name)
    if shiny:
        shiny_entry = _load_catalog_rows()[0].get(normalize_item_name(f"{base_key} (shiny)"))
        base_points = float(shiny_entry["points"]) if shiny_entry else 0.0
    else:
        base_points = float(entry["points"])

    if base_points <= 0:
        return 0.0

    effective_rarity = normalize_rarity(rarity)
    rarity_multiplier = float(rarity_multipliers.get(effective_rarity, 1.0))
    shiny_multiplier = float(rarity_multipliers.get("shiny", 1.0)) if shiny else 1.0
    final_points = base_points * rarity_multiplier * shiny_multiplier
    import math

    return math.floor(final_points * 2) / 2


def loot_entries_for_renderer(items: Iterable[tuple[str, bool, str]]) -> list[tuple[str, bool, str]]:
    return [(name, shiny, rarity) for name, shiny, rarity in items]
