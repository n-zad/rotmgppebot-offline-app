"""Local loot operations for manual entry (adapter over shared models)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable

from app.config.settings import AppConfig
from app.core_adapter.loot_catalog import (
    calc_item_points,
    is_equipment,
    required_rarity,
    supports_rarity_tiers,
    validate_loot_input,
)
from app.storage.models import LocalLootEntry, LocalPPE, LocalPlayerData

logger = logging.getLogger(__name__)

RARITY_CHOICES = ("common", "uncommon", "rare", "legendary", "divine")
SHINY_MINIMUM_RARITY = "rare"


@dataclass(frozen=True)
class LootChangeResult:
    item_name: str
    shiny: bool
    rarity: str
    quantity: int
    points_delta: float
    ppe_points: float
    removed_count: int = 0


def _find_loot(ppe: LocalPPE, item_name: str, shiny: bool, rarity: str) -> LocalLootEntry | None:
    for entry in ppe.loot:
        if entry.item_name == item_name and entry.shiny == shiny and entry.rarity == rarity:
            return entry
    return None


def _recompute_points(ppe: LocalPPE, config: AppConfig) -> None:
    total = 0.0
    for entry in ppe.loot:
        per_item = calc_item_points(
            entry.item_name,
            shiny=entry.shiny,
            rarity=entry.rarity,
            rarity_multipliers=config.rarity_multipliers,
        )
        total += per_item * entry.quantity
    ppe.points = round(total, 2)


def add_loot(
    player: LocalPlayerData,
    *,
    ppe_id: int,
    item_name: str,
    shiny: bool,
    rarity: str,
    config: AppConfig,
) -> LootChangeResult:
    validate_loot_input(item_name, shiny=shiny)
    rarity = rarity.lower().strip()
    if rarity not in RARITY_CHOICES:
        raise ValueError(f"Invalid rarity '{rarity}'. Choose one of: {', '.join(RARITY_CHOICES)}.")

    fixed_rarity = required_rarity(item_name, shiny=shiny)
    if fixed_rarity:
        if rarity != fixed_rarity:
            raise ValueError(f"'{item_name}' must be logged as {fixed_rarity.title()} rarity.")
        rarity = fixed_rarity
    elif not supports_rarity_tiers(item_name) and rarity != "common":
        raise ValueError("Only equipment (weapon, ability, armor, ring) supports rarity tiers.")

    if (
        shiny
        and is_equipment(item_name)
        and fixed_rarity is None
        and RARITY_CHOICES.index(rarity) < RARITY_CHOICES.index(SHINY_MINIMUM_RARITY)
    ):
        raise ValueError(f"Shiny equipment must be at least {SHINY_MINIMUM_RARITY.title()} rarity.")

    ppe = player.get_ppe(ppe_id)
    if ppe is None:
        raise ValueError(f"PPE #{ppe_id} was not found.")

    old_points = ppe.points
    match = _find_loot(ppe, item_name, shiny, rarity)
    timestamp = int(time.time())
    if match:
        match.quantity += 1
        match.logged_times.append(timestamp)
    else:
        ppe.loot.append(
            LocalLootEntry(
                item_name=item_name,
                quantity=1,
                shiny=shiny,
                rarity=rarity,
                logged_times=[timestamp],
            )
        )

    _recompute_points(ppe, config)
    match = _find_loot(ppe, item_name, shiny, rarity)
    assert match is not None
    return LootChangeResult(
        item_name=item_name,
        shiny=shiny,
        rarity=rarity,
        quantity=match.quantity,
        points_delta=round(ppe.points - old_points, 2),
        ppe_points=ppe.points,
    )


def remove_loot(
    player: LocalPlayerData,
    *,
    ppe_id: int,
    item_name: str,
    shiny: bool,
    rarity: str,
    config: AppConfig,
) -> LootChangeResult:
    ppe = player.get_ppe(ppe_id)
    if ppe is None:
        raise ValueError(f"PPE #{ppe_id} was not found.")

    old_points = ppe.points
    match = _find_loot(ppe, item_name, shiny, rarity)
    if match is None or match.quantity <= 0:
        raise ValueError("That loot entry is not on this PPE.")

    match.quantity -= 1
    if match.quantity <= 0:
        ppe.loot = [entry for entry in ppe.loot if entry is not match]

    _recompute_points(ppe, config)
    remaining = 0
    refreshed = _find_loot(ppe, item_name, shiny, rarity)
    if refreshed:
        remaining = refreshed.quantity

    return LootChangeResult(
        item_name=item_name,
        shiny=shiny,
        rarity=rarity,
        quantity=remaining,
        points_delta=round(ppe.points - old_points, 2),
        ppe_points=ppe.points,
        removed_count=1,
    )


def remove_all_loot(
    player: LocalPlayerData,
    *,
    ppe_id: int,
    item_name: str,
    shiny: bool,
    rarity: str,
    config: AppConfig,
) -> LootChangeResult:
    ppe = player.get_ppe(ppe_id)
    if ppe is None:
        raise ValueError(f"PPE #{ppe_id} was not found.")

    old_points = ppe.points
    match = _find_loot(ppe, item_name, shiny, rarity)
    if match is None or match.quantity <= 0:
        raise ValueError("That loot entry is not on this PPE.")

    removed_count = match.quantity
    ppe.loot = [entry for entry in ppe.loot if entry is not match]

    _recompute_points(ppe, config)
    return LootChangeResult(
        item_name=item_name,
        shiny=shiny,
        rarity=rarity,
        quantity=0,
        points_delta=round(ppe.points - old_points, 2),
        ppe_points=ppe.points,
        removed_count=removed_count,
    )


def create_ppe(player: LocalPlayerData, *, class_name: str) -> LocalPPE:
    next_id = max((ppe.id for ppe in player.ppes), default=0) + 1
    ppe = LocalPPE(id=next_id, class_name=class_name)
    player.ppes.append(ppe)
    player.active_ppe_id = ppe.id
    return ppe


def delete_ppe(player: LocalPlayerData, *, ppe_id: int) -> LocalPPE | None:
    deleted: LocalPPE | None = None
    for index, ppe in enumerate(player.ppes):
        if ppe.id == ppe_id:
            deleted = player.ppes.pop(index)
            break
    if deleted is None:
        return None

    if player.active_ppe_id == ppe_id:
        player.active_ppe_id = player.ppes[0].id if player.ppes else None
    return deleted


def flatten_loot_for_render(ppe: LocalPPE) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    for entry in ppe.loot:
        for _ in range(entry.quantity):
            rows.append((entry.item_name, entry.shiny, entry.rarity))
    return rows


@dataclass(frozen=True)
class LootLabelDisplay:
    prefix: str
    item_first: str
    item_rest: str


def loot_label_display(entry: LocalLootEntry, *, include_quantity: bool = True) -> LootLabelDisplay:
    prefix_parts: list[str] = []
    if entry.rarity != "common":
        prefix_parts.append(entry.rarity.title())
    if entry.shiny:
        prefix_parts.append("Shiny")
    prefix = (" ".join(prefix_parts) + " ") if prefix_parts else ""

    item_name = entry.item_name
    if item_name:
        item_first = item_name[0]
        item_rest = item_name[1:]
    else:
        item_first = ""
        item_rest = ""

    if include_quantity and entry.quantity > 1:
        item_rest = f"{item_rest} x{entry.quantity}"

    return LootLabelDisplay(prefix=prefix, item_first=item_first, item_rest=item_rest)


def format_loot_label(entry: LocalLootEntry, *, include_quantity: bool = True) -> str:
    parts = loot_label_display(entry, include_quantity=include_quantity)
    return f"{parts.prefix}{parts.item_first}{parts.item_rest}"
