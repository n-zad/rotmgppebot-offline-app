"""Bridge local offline models to upstream points_service helpers."""

from __future__ import annotations

from app.config.settings import AppConfig
from app.core_adapter.repo_paths import ensure_repo_imports
from app.paths import working_directory
from app.storage.models import LocalLootEntry, LocalPPE


def local_ppe_to_ppe_data(local: LocalPPE):
    ensure_repo_imports()
    from dataclass import Loot, PPEData, ROTMGClass

    try:
        class_enum = ROTMGClass(local.class_name)
    except ValueError:
        class_enum = ROTMGClass.WIZARD

    loot = [
        Loot(
            item_name=entry.item_name,
            quantity=entry.quantity,
            shiny=entry.shiny,
            rarity=entry.rarity,
            logged_times=list(entry.logged_times),
        )
        for entry in local.loot
    ]
    return PPEData(
        id=local.id,
        name=class_enum,
        points=local.points,
        loot=loot,
    )


def _recompute_upstream_total(ppe_data, guild_config: dict) -> float:
    from utils.points_service import recompute_ppe_points

    with working_directory():
        breakdown = recompute_ppe_points(ppe_data, guild_config)
    return float(breakdown["total"])


def recompute_local_ppe_points(ppe: LocalPPE, config: AppConfig) -> float:
    ensure_repo_imports()
    ppe_data = local_ppe_to_ppe_data(ppe)
    return _recompute_upstream_total(ppe_data, config.guild_config_stub())


def _ordered_drop_events(ppe: LocalPPE) -> list[tuple[int, int]]:
    """Mirror upstream drop ordering so per-drop deltas match recompute_ppe_points."""
    drop_events: list[tuple[int, int, int]] = []
    fallback_sequence = 0

    for entry_index, entry in enumerate(ppe.loot):
        quantity = max(0, int(entry.quantity))
        if quantity <= 0:
            continue

        parsed_times = sorted(int(ts) for ts in entry.logged_times if int(ts) > 0)
        for event_index in range(quantity):
            if event_index < len(parsed_times):
                timestamp = parsed_times[event_index]
                sort_group = 0
            else:
                fallback_sequence += 1
                timestamp = fallback_sequence
                sort_group = 1
            drop_events.append((sort_group, timestamp, entry_index, event_index))

    drop_events.sort(key=lambda row: (row[0], row[1], row[2]))
    return [(entry_index, event_index) for _sort_group, _timestamp, entry_index, event_index in drop_events]


def _local_ppe_with_drop_events(
    ppe: LocalPPE,
    included: dict[int, set[int]],
) -> LocalPPE:
    loot: list[LocalLootEntry] = []
    for entry_index, entry in enumerate(ppe.loot):
        event_indices = included.get(entry_index)
        if not event_indices:
            continue

        parsed_times = sorted(int(ts) for ts in entry.logged_times if int(ts) > 0)
        logged_times: list[int] = []
        for event_index in sorted(event_indices):
            if event_index < len(parsed_times):
                logged_times.append(parsed_times[event_index])

        loot.append(
            LocalLootEntry(
                item_name=entry.item_name,
                quantity=len(event_indices),
                shiny=entry.shiny,
                rarity=entry.rarity,
                logged_times=sorted(logged_times),
            )
        )

    return LocalPPE(
        id=ppe.id,
        class_name=ppe.class_name,
        points=ppe.points,
        loot=loot,
    )


def loot_drop_points_by_entry_index(ppe: LocalPPE, config: AppConfig) -> dict[int, list[float]]:
    """Per-drop loot points derived only from upstream recompute_ppe_points deltas."""
    ordered = _ordered_drop_events(ppe)
    if not ordered:
        return {}

    included: dict[int, set[int]] = {}
    by_entry: dict[int, list[float]] = {}
    previous_total = 0.0

    for entry_index, event_index in ordered:
        included.setdefault(entry_index, set()).add(event_index)
        partial = _local_ppe_with_drop_events(ppe, included)
        current_total = recompute_local_ppe_points(partial, config)
        awarded = round(current_total - previous_total, 2)
        by_entry.setdefault(entry_index, []).append(awarded)
        previous_total = current_total

    return by_entry


def entry_index_for_loot_entry(ppe: LocalPPE, entry: LocalLootEntry) -> int | None:
    for index, candidate in enumerate(ppe.loot):
        if candidate is entry:
            return index
    for index, candidate in enumerate(ppe.loot):
        if (
            candidate.item_name == entry.item_name
            and candidate.shiny == entry.shiny
            and candidate.rarity == entry.rarity
        ):
            return index
    return None
