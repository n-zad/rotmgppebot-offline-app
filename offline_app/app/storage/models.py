"""Local player data models (compatible shape with upstream bot records)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ROTMG_CLASSES = [
    "Wizard",
    "Priest",
    "Archer",
    "Rogue",
    "Warrior",
    "Knight",
    "Paladin",
    "Assassin",
    "Necromancer",
    "Huntress",
    "Mystic",
    "Trickster",
    "Sorcerer",
    "Ninja",
    "Samurai",
    "Bard",
    "Summoner",
    "Kensei",
    "Druid",
]

SCHEMA_VERSION = 1


@dataclass
class LocalLootEntry:
    item_name: str
    quantity: int = 1
    shiny: bool = False
    rarity: str = "common"
    logged_times: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_name": self.item_name,
            "quantity": self.quantity,
            "shiny": self.shiny,
            "rarity": self.rarity,
            "logged_times": list(self.logged_times),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LocalLootEntry":
        times: list[int] = []
        for value in raw.get("logged_times") or []:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                times.append(parsed)
        rarity = str(raw.get("rarity") or "common").strip().lower()
        if bool(raw.get("divine")) and rarity == "common":
            rarity = "divine"
        return cls(
            item_name=str(raw.get("item_name") or "Unknown Item"),
            quantity=max(0, int(raw.get("quantity") or 0)),
            shiny=bool(raw.get("shiny", False)),
            rarity=rarity,
            logged_times=sorted(times),
        )


@dataclass
class LocalPPE:
    id: int
    class_name: str
    points: float = 0.0
    loot: list[LocalLootEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.class_name,
            "points": self.points,
            "loot": [entry.to_dict() for entry in self.loot],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LocalPPE":
        loot = [LocalLootEntry.from_dict(item) for item in raw.get("loot") or []]
        loot = [entry for entry in loot if entry.quantity > 0]
        return cls(
            id=int(raw.get("id") or 0),
            class_name=str(raw.get("name") or raw.get("class_name") or "Wizard"),
            points=float(raw.get("points") or 0.0),
            loot=loot,
        )


@dataclass
class LocalPlayerData:
    player_name: str = "Player"
    active_ppe_id: int | None = None
    ppes: list[LocalPPE] = field(default_factory=list)

    def get_ppe(self, ppe_id: int) -> LocalPPE | None:
        for ppe in self.ppes:
            if ppe.id == ppe_id:
                return ppe
        return None

    def active_ppe(self) -> LocalPPE | None:
        if self.active_ppe_id is None:
            return self.ppes[0] if self.ppes else None
        return self.get_ppe(self.active_ppe_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "player_name": self.player_name,
            "active_ppe": self.active_ppe_id,
            "ppes": [ppe.to_dict() for ppe in self.ppes],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LocalPlayerData":
        ppes = [LocalPPE.from_dict(item) for item in raw.get("ppes") or []]
        active = raw.get("active_ppe")
        active_id = int(active) if active is not None else None
        if active_id is None and ppes:
            active_id = ppes[0].id
        return cls(
            player_name=str(raw.get("player_name") or "Player"),
            active_ppe_id=active_id,
            ppes=ppes,
        )

    @classmethod
    def empty(cls, player_name: str = "Player") -> "LocalPlayerData":
        return cls(player_name=player_name, active_ppe_id=None, ppes=[])
