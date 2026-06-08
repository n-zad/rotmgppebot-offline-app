"""Rarity picker using pip icons (equipment loot only)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageEnhance, ImageTk

from app.core_adapter.loot_service import RARITY_CHOICES, SHINY_MINIMUM_RARITY
from app.core_adapter.repo_paths import rarity_pics_dir

_REF_DISPLAY_HEIGHT = 28
_CELL_PAD = 4
_SELECTED_BORDER = "#4a90d9"
_UNSELECTED_BORDER = "#6a6a6a"
_UNAVAILABLE_BORDER = "#b8b8b8"
_ENABLED_BG = "#f5f5f5"
_UNAVAILABLE_BG = "#e4e4e4"
_SELECTED_BG = "#d8e8f8"


def _make_common_diamond_image(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    inset = max(2, size // 8)
    cx, cy = size // 2, size // 2
    radius = size // 2 - inset
    points = [(cx, cy - radius), (cx + radius, cy), (cx, cy + radius), (cx - radius, cy)]
    draw.polygon(points, outline=(190, 190, 190, 255), fill=(0, 0, 0, 0), width=2)
    return img


def _divine_reference_size() -> tuple[int, int]:
    path = rarity_pics_dir() / "divine.png"
    with Image.open(path) as src:
        img = src.convert("RGBA")
    scale = _REF_DISPLAY_HEIGHT / img.height
    ref_w = max(1, int(img.width * scale))
    ref_h = _REF_DISPLAY_HEIGHT
    return ref_w, ref_h


def _center_in_slot(pip: Image.Image, slot_w: int, slot_h: int) -> Image.Image:
    slot = Image.new("RGBA", (slot_w, slot_h), (0, 0, 0, 0))
    x = (slot_w - pip.width) // 2
    y = (slot_h - pip.height) // 2
    slot.paste(pip, (x, y), pip)
    return slot


def _load_pip_image(rarity: str, ref_w: int, ref_h: int) -> Image.Image:
    if rarity == "common":
        size = min(ref_w, ref_h)
        return _center_in_slot(_make_common_diamond_image(size), ref_w, ref_h)

    path = rarity_pics_dir() / f"{rarity}.png"
    if not path.is_file():
        size = min(ref_w, ref_h)
        return _center_in_slot(_make_common_diamond_image(size), ref_w, ref_h)

    with Image.open(path) as src:
        img = src.convert("RGBA")

    if rarity == "divine":
        pip = img.resize((ref_w, ref_h), Image.Resampling.LANCZOS)
    elif rarity == "legendary":
        target_h = max(1, int(ref_h * 0.75))
        scale = target_h / img.height
        target_w = max(1, int(img.width * scale))
        pip = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    elif rarity == "rare":
        target_h = max(1, int(ref_h * 0.50))
        scale = target_h / img.height
        target_w = max(1, int(img.width * scale))
        pip = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    elif rarity == "uncommon":
        target_w = max(1, int(ref_w * 0.50))
        target_h = max(1, int(ref_h * 0.50))
        pip = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    else:
        pip = img.resize((ref_w, ref_h), Image.Resampling.LANCZOS)

    return _center_in_slot(pip, ref_w, ref_h)


def _unavailable_slot_image(slot: Image.Image) -> Image.Image:
    faded = ImageEnhance.Brightness(slot).enhance(0.55)
    faded = ImageEnhance.Color(faded).enhance(0.35)
    draw = ImageDraw.Draw(faded)
    width, height = faded.size
    margin = 3
    draw.line(
        (margin, height - margin, width - margin, margin),
        fill=(150, 150, 150, 220),
        width=2,
    )
    return faded


class RaritySelector(ttk.Frame):
    """Single-select rarity row with pip icons; common uses a diamond outline."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        variable: tk.StringVar,
        **kwargs: object,
    ) -> None:
        super().__init__(master, **kwargs)
        self._variable = variable
        self._equipment_mode = False
        self._shiny_mode = False
        self._allowed_rarities: frozenset[str] | None = None
        self._photos: dict[str, ImageTk.PhotoImage] = {}
        self._unavailable_photos: dict[str, ImageTk.PhotoImage] = {}
        self._cells: dict[str, tk.Frame] = {}
        self._labels: dict[str, tk.Label] = {}

        ref_w, ref_h = _divine_reference_size()

        row = ttk.Frame(self)
        row.pack(fill=tk.X)

        for index, rarity in enumerate(RARITY_CHOICES):
            pip = _load_pip_image(rarity, ref_w, ref_h)
            self._photos[rarity] = ImageTk.PhotoImage(pip, master=self)
            unavailable = _unavailable_slot_image(pip)
            self._unavailable_photos[rarity] = ImageTk.PhotoImage(unavailable, master=self)

            cell = tk.Frame(
                row,
                padx=_CELL_PAD,
                pady=_CELL_PAD,
                highlightthickness=2,
                highlightbackground=_UNSELECTED_BORDER,
                bg=_ENABLED_BG,
                cursor="hand2" if rarity == "common" else "arrow",
            )
            cell.grid(row=0, column=index, padx=2)

            label = tk.Label(
                cell,
                image=self._photos[rarity],
                bg=_ENABLED_BG,
                borderwidth=0,
                cursor="hand2" if rarity == "common" else "arrow",
            )
            label.pack()

            for widget in (cell, label):
                widget.bind("<Button-1>", lambda _e, value=rarity: self._select(value))

            self._cells[rarity] = cell
            self._labels[rarity] = label

        self._variable.trace_add("write", self._on_variable_changed)
        self._refresh_selection()

    def _is_selectable(self, rarity: str) -> bool:
        if not self._equipment_mode:
            return rarity == "common"
        if self._allowed_rarities is not None:
            return rarity in self._allowed_rarities
        if self._shiny_mode and RARITY_CHOICES.index(rarity) < RARITY_CHOICES.index(SHINY_MINIMUM_RARITY):
            return False
        return True

    def _default_rarity(self) -> str:
        if not self._equipment_mode:
            return "common"
        if self._shiny_mode:
            return SHINY_MINIMUM_RARITY
        return "common"

    def _coerce_rarity(self) -> None:
        current = str(self._variable.get() or "common").strip().lower()
        if current not in RARITY_CHOICES or not self._is_selectable(current):
            target = self._default_rarity()
            if self._variable.get() != target:
                self._variable.set(target)

    def _select(self, rarity: str) -> None:
        if not self._is_selectable(rarity):
            return
        if rarity not in RARITY_CHOICES:
            return
        self._variable.set(rarity)

    def _on_variable_changed(self, *_args: object) -> None:
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        self._coerce_rarity()

        current = str(self._variable.get() or "common").strip().lower()
        if current not in RARITY_CHOICES:
            current = self._default_rarity()

        for rarity in RARITY_CHOICES:
            cell = self._cells[rarity]
            label = self._labels[rarity]
            selectable = self._is_selectable(rarity)
            selected = selectable and rarity == current

            if selectable:
                label.configure(image=self._photos[rarity])
                cell_bg = _SELECTED_BG if selected else _ENABLED_BG
                border = _SELECTED_BORDER if selected else _UNSELECTED_BORDER
                cursor = "hand2"
            else:
                label.configure(image=self._unavailable_photos[rarity])
                cell_bg = _UNAVAILABLE_BG
                border = _UNAVAILABLE_BORDER
                cursor = "arrow"

            cell.configure(bg=cell_bg, highlightbackground=border, cursor=cursor)
            label.configure(bg=cell_bg, cursor=cursor)

    def set_enabled(self, enabled: bool) -> None:
        """Enable equipment-only rarities when *enabled* is True."""
        self._equipment_mode = enabled
        self._coerce_rarity()
        self._refresh_selection()

    def set_allowed_rarities(self, allowed: frozenset[str] | None) -> None:
        """Restrict selectable rarities; *None* uses default equipment/shiny rules."""
        self._allowed_rarities = allowed
        self._coerce_rarity()
        self._refresh_selection()

    def set_shiny(self, shiny: bool) -> None:
        """Disable sub-rare rarities for shiny equipment; minimum is rare."""
        self._shiny_mode = shiny
        self._coerce_rarity()
        self._refresh_selection()
