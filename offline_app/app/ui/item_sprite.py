"""Load catalog item sprites for UI display."""

from __future__ import annotations

import logging

from PIL import Image

from app.core_adapter.loot_catalog import required_rarity, supports_rarity_tiers
from app.core_adapter.repo_paths import ensure_repo_imports

logger = logging.getLogger(__name__)

_DEFAULT_SPRITE_SIZE = 40


def load_item_sprite_image(
    item_name: str,
    *,
    shiny: bool,
    rarity: str | None = None,
    size: int = _DEFAULT_SPRITE_SIZE,
) -> Image.Image | None:
    """Return a catalog sprite, optionally with a rarity badge overlay."""
    ensure_repo_imports()
    from utils.image_utils import overlay_rarity_badge_on_image, resolve_item_image_path

    base_name = item_name.strip()
    if not base_name:
        return None
    if base_name.endswith(" (shiny)"):
        base_name = base_name[: -len(" (shiny)")]

    sprite_path = resolve_item_image_path(base_name, shiny)
    if not sprite_path:
        return None
    try:
        with Image.open(sprite_path) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            if img.size != (size, size):
                img = img.resize((size, size), Image.Resampling.LANCZOS)
            sprite = img.copy()
    except OSError as exc:
        logger.debug("Could not load sprite for %s: %s", item_name, exc)
        return None

    if rarity:
        show_badge = supports_rarity_tiers(base_name) or bool(required_rarity(base_name, shiny=shiny))
        if show_badge:
            sprite = overlay_rarity_badge_on_image(sprite, rarity) or sprite
    return sprite
