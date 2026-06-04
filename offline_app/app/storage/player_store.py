"""Load and save local player data under offline_app/data/."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from app.storage.models import LocalPlayerData, SCHEMA_VERSION

logger = logging.getLogger(__name__)


class PlayerStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self, *, default_name: str = "Player") -> LocalPlayerData:
        if not self.path.exists():
            logger.info("No player file at %s; starting fresh.", self.path)
            return LocalPlayerData.empty(player_name=default_name)

        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Player data file is corrupt ({self.path.name}). "
                f"Fix or delete the file and restart. Details: {exc}"
            ) from exc
        except OSError as exc:
            raise ValueError(f"Could not read player data: {exc}") from exc

        if not isinstance(raw, dict):
            raise ValueError("Player data root must be a JSON object.")

        version = int(raw.get("schema_version") or 0)
        if version > SCHEMA_VERSION:
            logger.warning(
                "Player file schema version %s is newer than app version %s.",
                version,
                SCHEMA_VERSION,
            )

        player = LocalPlayerData.from_dict(raw)
        if not player.player_name:
            player.player_name = default_name
        return player

    def save(self, player: LocalPlayerData) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = player.to_dict()
        directory = self.path.parent
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=directory,
                delete=False,
                suffix=".tmp",
            ) as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                temp_name = handle.name
            os.replace(temp_name, self.path)
            logger.info("Saved player data to %s", self.path)
        except OSError as exc:
            raise ValueError(f"Could not save player data: {exc}") from exc
