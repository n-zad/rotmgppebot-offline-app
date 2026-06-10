"""Hover tooltips for the loot table canvas."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

import tkinter as tk

from PIL import Image, ImageTk

from app.config.settings import AppConfig
from app.core_adapter.loot_catalog import calc_item_points
from app.core_adapter.loot_renderer import SpriteCell, SpriteHitIndex, entry_sprite_lookup_key
from app.core_adapter.loot_service import format_loot_label
from app.core_adapter.repo_paths import ensure_repo_imports
from app.storage.models import LocalLootEntry, LocalPPE

if TYPE_CHECKING:
    from tkinter import Canvas

logger = logging.getLogger(__name__)

_TOOLTIP_BG = "#1e1e1e"
_TOOLTIP_FG = "#f0f0f0"
_TOOLTIP_BORDER = "#555555"
_TOOLTIP_PAD = 8
_SPRITE_DISPLAY_SIZE = 40
_CURSOR_OFFSET = 16
_EDGE_MARGIN = 8


def _clamp(value: int, low: int, high: int) -> int:
    if low > high:
        return low
    return max(low, min(value, high))


def compute_tooltip_position(
    *,
    x_root: int,
    y_root: int,
    width: int,
    height: int,
    bounds: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Place a tooltip near the cursor, flipping and clamping to stay on-screen."""
    left, top, right, bottom = bounds
    margin = _EDGE_MARGIN

    min_x = left + margin
    min_y = top + margin
    max_x = right - width - margin
    max_y = bottom - height - margin

    x = x_root + _CURSOR_OFFSET
    y = y_root + _CURSOR_OFFSET

    if x > max_x:
        x = x_root - width - _CURSOR_OFFSET
    if y > max_y:
        y = y_root - height - _CURSOR_OFFSET

    return _clamp(x, min_x, max_x), _clamp(y, min_y, max_y)


def _format_points(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _format_timestamp(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%b %d, %Y %I:%M %p")
    except (OSError, OverflowError, ValueError):
        return "unknown time"


def _loot_entries_for_cell(ppe: LocalPPE | None, cell: SpriteCell) -> list[LocalLootEntry]:
    if ppe is None:
        return []
    return [
        entry
        for entry in ppe.loot
        if entry_sprite_lookup_key(entry.item_name, shiny=entry.shiny) == cell.lookup_key
    ]


def build_tooltip_text(
    cell: SpriteCell,
    entries: list[LocalLootEntry],
    *,
    config: AppConfig,
    condensed: bool = False,
) -> tuple[str, list[str]]:
    """Return a title line and body lines for the hover tooltip."""
    title = cell.item_name
    body: list[str] = []

    if not entries:
        body.append("Not logged on this PPE.")
        return title, body

    grand_total = 0.0
    for entry in sorted(entries, key=lambda item: (item.rarity, item.quantity)):
        per_copy = calc_item_points(
            entry.item_name,
            shiny=entry.shiny,
            rarity=entry.rarity,
            rarity_multipliers=config.rarity_multipliers,
        )
        entry_total = per_copy * entry.quantity
        grand_total += entry_total
        label = format_loot_label(entry, include_quantity=True)
        if condensed:
            body.append(f"{label} (+{_format_points(entry_total)} pts)")
            continue

        body.append(label)

        timestamps = list(entry.logged_times)
        if timestamps:
            for index, ts in enumerate(timestamps, start=1):
                body.append(f"  #{index}: +{_format_points(per_copy)} pts — {_format_timestamp(ts)}")
            if entry.quantity > len(timestamps):
                extra = entry.quantity - len(timestamps)
                body.append(f"  (+{extra} more without timestamps)")
        else:
            if entry.quantity == 1:
                body.append(f"  +{_format_points(per_copy)} pts")
            else:
                body.append(f"  {entry.quantity}× +{_format_points(per_copy)} pts each")

        body.append(f"  Subtotal: {_format_points(entry_total)} pts")

    if len(entries) > 1:
        body.append(f"Total: {_format_points(grand_total)} pts")
    return title, body


def _load_item_sprite(item_name: str, *, shiny: bool) -> Image.Image | None:
    ensure_repo_imports()
    from utils.image_utils import resolve_item_image_path

    base_name = item_name
    if base_name.endswith(" (shiny)"):
        base_name = base_name[: -len(" (shiny)")]

    sprite_path = resolve_item_image_path(base_name, shiny)
    if not sprite_path:
        return None
    try:
        with Image.open(sprite_path) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            if img.size != (_SPRITE_DISPLAY_SIZE, _SPRITE_DISPLAY_SIZE):
                img = img.resize((_SPRITE_DISPLAY_SIZE, _SPRITE_DISPLAY_SIZE), Image.Resampling.LANCZOS)
            return img.copy()
    except OSError as exc:
        logger.debug("Could not load sprite for %s: %s", item_name, exc)
        return None


class LootTableTooltip:
    """Undecorated floating tooltip for loot table hover."""

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._window: tk.Toplevel | None = None
        self._title_var = tk.StringVar(value="")
        self._body: tk.Text | None = None
        self._sprite_label: tk.Label | None = None
        self._photo: ImageTk.PhotoImage | None = None

    def hide(self) -> None:
        if self._window is not None:
            self._window.withdraw()

    def is_visible(self) -> bool:
        return self._window is not None and bool(self._window.winfo_viewable())

    def _screen_bounds(self) -> tuple[int, int, int, int]:
        left = int(self._root.winfo_vrootx())
        top = int(self._root.winfo_vrooty())
        right = left + int(self._root.winfo_vrootwidth())
        bottom = top + int(self._root.winfo_vrootheight())
        try:
            top_level = self._root.winfo_toplevel()
            top_level.update_idletasks()
            win_bottom = int(top_level.winfo_rooty()) + int(top_level.winfo_height())
            bottom = min(bottom, win_bottom)
        except tk.TclError:
            pass
        return left, top, right, bottom

    def _place_at_cursor(self, *, x_root: int, y_root: int) -> None:
        assert self._window is not None
        self._window.update_idletasks()
        width = self._window.winfo_reqwidth()
        height = self._window.winfo_reqheight()
        x, y = compute_tooltip_position(
            x_root=x_root,
            y_root=y_root,
            width=width,
            height=height,
            bounds=self._screen_bounds(),
        )
        self._window.geometry(f"+{x}+{y}")

    def move(self, *, x_root: int, y_root: int) -> None:
        if not self.is_visible():
            return
        self._place_at_cursor(x_root=x_root, y_root=y_root)

    def destroy(self) -> None:
        self.hide()
        if self._window is not None:
            self._window.destroy()
            self._window = None

    def show(
        self,
        *,
        x_root: int,
        y_root: int,
        title: str,
        body_lines: list[str],
        sprite: Image.Image | None = None,
    ) -> None:
        self._ensure_window()
        assert self._window is not None
        assert self._body is not None

        self._title_var.set(title)
        self._body.configure(state=tk.NORMAL)
        self._body.delete("1.0", tk.END)
        if body_lines:
            self._body.insert(tk.END, "\n".join(body_lines))
        line_count = max(1, len(body_lines))
        self._body.configure(height=line_count, state=tk.DISABLED)

        if sprite is not None and self._sprite_label is not None:
            self._photo = ImageTk.PhotoImage(sprite, master=self._sprite_label)
            self._sprite_label.configure(image=self._photo)
            if not self._sprite_label.winfo_ismapped():
                self._sprite_label.pack(side=tk.LEFT, padx=(0, 8))
        elif self._sprite_label is not None:
            self._sprite_label.pack_forget()

        self._window.deiconify()
        self._place_at_cursor(x_root=x_root, y_root=y_root)
        self._window.lift()

    def _ensure_window(self) -> None:
        if self._window is not None:
            return

        window = tk.Toplevel(self._root)
        window.withdraw()
        window.overrideredirect(True)
        window.configure(bg=_TOOLTIP_BORDER)

        frame = tk.Frame(window, bg=_TOOLTIP_BG, padx=_TOOLTIP_PAD, pady=_TOOLTIP_PAD)
        frame.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(frame, bg=_TOOLTIP_BG)
        header.pack(fill=tk.X)

        self._sprite_label = tk.Label(header, bg=_TOOLTIP_BG, borderwidth=0)

        title_label = tk.Label(
            header,
            textvariable=self._title_var,
            bg=_TOOLTIP_BG,
            fg=_TOOLTIP_FG,
            font=("Segoe UI", 10, "bold"),
            justify=tk.LEFT,
            anchor="w",
            wraplength=280,
        )
        title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._body = tk.Text(
            frame,
            bg=_TOOLTIP_BG,
            fg=_TOOLTIP_FG,
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            wrap=tk.WORD,
            width=42,
            height=1,
        )
        self._body.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self._body.configure(state=tk.DISABLED, cursor="arrow")

        self._window = window


class LootTableHoverController:
    """Maps canvas pointer position to catalog items and shows a tooltip."""

    def __init__(
        self,
        canvas: Canvas,
        *,
        config: AppConfig,
        active_ppe: Callable[[], LocalPPE | None],
        display_scale: Callable[[], float],
        source_size: Callable[[], tuple[int, int]],
        hover_enabled: Callable[[], bool],
        hover_condensed: Callable[[], bool],
    ) -> None:
        self._canvas = canvas
        self._config = config
        self._active_ppe = active_ppe
        self._display_scale = display_scale
        self._source_size = source_size
        self._hover_enabled = hover_enabled
        self._hover_condensed = hover_condensed
        self._tooltip = LootTableTooltip(canvas.winfo_toplevel())
        self._hit_index: SpriteHitIndex | None = None
        self._crop_offset: tuple[int, int] = (0, 0)
        self._active_cell: tuple[int, int] | None = None

        canvas.bind("<Motion>", self._on_motion, add="+")
        canvas.bind("<Leave>", self._on_leave, add="+")

    def set_hit_index(self, hit_index: SpriteHitIndex | None, *, crop_offset: tuple[int, int]) -> None:
        self._hit_index = hit_index
        self._crop_offset = crop_offset
        self.invalidate()

    def invalidate(self) -> None:
        """Clear cached hover state so the next pointer move rebuilds tooltip content."""
        self._active_cell = None
        self._tooltip.hide()

    def destroy(self) -> None:
        self._tooltip.destroy()

    def _on_leave(self, _event: tk.Event) -> None:
        self._active_cell = None
        self._tooltip.hide()

    def _on_motion(self, event: tk.Event) -> None:
        if not self._hover_enabled():
            self._active_cell = None
            self._tooltip.hide()
            return

        if self._hit_index is None:
            self._tooltip.hide()
            return

        source_w, source_h = self._source_size()
        if source_w <= 0 or source_h <= 0:
            self._tooltip.hide()
            return

        display_w, display_h = self._scaled_display_size(source_w, source_h)
        canvas_x = self._canvas.canvasx(event.x)
        canvas_y = self._canvas.canvasy(event.y)
        if canvas_x < 0 or canvas_y < 0 or canvas_x >= display_w or canvas_y >= display_h:
            self._active_cell = None
            self._tooltip.hide()
            return

        source_x = canvas_x * source_w / display_w
        source_y = canvas_y * source_h / display_h
        cell = self._hit_index.lookup(source_x, source_y, crop_offset=self._crop_offset)
        if cell is None:
            self._active_cell = None
            self._tooltip.hide()
            return

        cell_key = (cell.pixel_x, cell.pixel_y)
        if cell_key == self._active_cell:
            self._tooltip.move(x_root=event.x_root, y_root=event.y_root)
            return
        self._active_cell = cell_key

        ppe = self._active_ppe()
        entries = _loot_entries_for_cell(ppe, cell)
        title, body_lines = build_tooltip_text(
            cell,
            entries,
            config=self._config,
            condensed=self._hover_condensed(),
        )

        shiny = cell.lookup_key.endswith(" (shiny)")
        sprite = _load_item_sprite(cell.item_name, shiny=shiny)
        self._tooltip.show(
            x_root=event.x_root,
            y_root=event.y_root,
            title=title,
            body_lines=body_lines,
            sprite=sprite,
        )

    def _scaled_display_size(self, width: int, height: int) -> tuple[int, int]:
        factor = self._display_scale()
        return (
            max(1, int(width * factor)),
            max(1, int(height * factor)),
        )
