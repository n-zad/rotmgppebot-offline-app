"""Tkinter UI for manual RotMG loot entry."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from app.config.settings import (
    AppConfig,
    DEFAULT_LOOT_TABLE_DISPLAY_SCALE,
    normalize_loot_table_display_scale,
    save_config,
)
from app.core_adapter.loot_catalog import (
    has_shiny_variant,
    is_equipment,
    is_shiny_only_item,
    required_rarity,
    supports_rarity_tiers,
)
from app.core_adapter.repo_paths import app_icon_path
from app.paths import data_dir
from app.ui.item_autocomplete import ItemAutocomplete
from app.ui.loot_list_view import LootListView
from app.ui.rarity_selector import RaritySelector
from app.core_adapter.loot_renderer import render_loot_table
from app.core_adapter.loot_service import (
    add_loot,
    create_ppe,
    delete_ppe,
    flatten_loot_for_render,
    format_loot_label,
    remove_all_loot,
    remove_loot,
)
from app.storage.models import ROTMG_CLASSES, LocalLootEntry, LocalPlayerData, LocalPPE
from app.storage.player_store import PlayerStore

logger = logging.getLogger(__name__)

# Default display scale when maximized; scrollbars appear when the window is smaller.
# Overridable in Loot Table View and persisted in config.json.
_DEFAULT_IMAGE_DISPLAY_SCALE = DEFAULT_LOOT_TABLE_DISPLAY_SCALE
_DISPLAY_SCALE_PERCENT_MIN = 5
_DISPLAY_SCALE_PERCENT_MAX = 100
_LEFT_PANEL_MIN_WIDTH = 260
_LEFT_PANEL_FRAME_PADDING = 2
_LABEL_FRAME_PADDING = 6
_SCROLLBAR_THICKNESS = 18
_LOOT_TABLE_FRAME_PADDING = 2
# Small inset when fitting so scrollbars / rounding do not force overflow.
_FIT_VIEW_INSET = 4
# Pixels of transparent border kept around trimmed loot table art.
_TRIM_CONTENT_MARGIN = 2
# Remove half of the gray slack above/below (and beside) detected loot rows/columns.
_MARGIN_SHRINK_FRACTION = 0.5
_BG_COLOR_TOLERANCE = 20
_MIN_AXIS_CONTENT_FRACTION = 0.02
# Match canvas background; RGBA→RGB before PhotoImage avoids a ~20s Tk conversion on large images.
_CANVAS_BACKGROUND_RGB = (43, 43, 43)

_APP_USER_MODEL_ID = "rotmg.ppe.offline.loottracker"
_ICON_SIZES = ((16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def _set_paned_sash_x(paned: tk.PanedWindow, x: int) -> None:
    """Position the first vertical sash (tk.PanedWindow uses sash_place, not sashpos)."""
    try:
        paned.sash_place(0, x, 0)
    except tk.TclError as exc:
        logger.debug("Could not place paned sash: %s", exc)


def _maximize_window(root: tk.Tk) -> None:
    """Open the window maximized (platform-specific)."""
    try:
        if sys.platform == "win32":
            root.state("zoomed")
        elif sys.platform == "darwin":
            # Tk does not support zoomed on macOS; expand to the usable screen area.
            root.update_idletasks()
            width = root.winfo_screenwidth()
            height = root.winfo_screenheight() - 22
            root.geometry(f"{width}x{height}+0+0")
        else:
            root.attributes("-zoomed", True)
    except tk.TclError as exc:
        logger.debug("Could not maximize window: %s", exc)


def _trim_transparent_margins(image: Image.Image, *, margin: int = _TRIM_CONTENT_MARGIN) -> Image.Image:
    """Crop empty transparent borders from loot table PNGs (top/bottom/sides)."""
    rgba = image.convert("RGBA")
    bbox = rgba.getbbox()
    if bbox is None:
        return rgba
    left, top, right, bottom = bbox
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(rgba.width, right + margin)
    bottom = min(rgba.height, bottom + margin)
    if (left, top, right, bottom) == (0, 0, rgba.width, rgba.height):
        return rgba
    return rgba.crop((left, top, right, bottom))


def _is_canvas_background_pixel(r: int, g: int, b: int, a: int) -> bool:
    if a < 15:
        return True
    bg = _CANVAS_BACKGROUND_RGB
    tol = _BG_COLOR_TOLERANCE
    return abs(r - bg[0]) <= tol and abs(g - bg[1]) <= tol and abs(b - bg[2]) <= tol


def _is_loot_content_pixel(r: int, g: int, b: int, a: int) -> bool:
    """Filled loot sprites (not blank gray silhouette / canvas background)."""
    if _is_canvas_background_pixel(r, g, b, a):
        return False
    brightness = (r + g + b) / 3
    saturation = max(r, g, b) - min(r, g, b)
    if saturation > 22:
        return True
    if brightness > 88:
        return True
    return False


def _axis_content_bounds(rgba: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of rows/columns that contain filled loot (not empty silhouette bands)."""
    pixels = rgba.load()
    width, height = rgba.size
    min_pixels = max(1, int(min(width, height) * _MIN_AXIS_CONTENT_FRACTION))

    def column_has_content(x: int) -> bool:
        count = 0
        for y in range(height):
            if _is_loot_content_pixel(*pixels[x, y]):
                count += 1
        return count >= min_pixels

    def row_has_content(y: int) -> bool:
        count = 0
        for x in range(width):
            if _is_loot_content_pixel(*pixels[x, y]):
                count += 1
        return count >= min_pixels

    left = 0
    while left < width and not column_has_content(left):
        left += 1
    right = width
    while right > left and not column_has_content(right - 1):
        right -= 1

    top = 0
    while top < height and not row_has_content(top):
        top += 1
    bottom = height
    while bottom > top and not row_has_content(bottom - 1):
        bottom -= 1

    if left >= right or top >= bottom:
        return 0, 0, width, height
    return left, top, right, bottom


def _shrink_margin(start: int, end: int, total: int, *, fraction: float) -> tuple[int, int]:
    """Move crop edges inward by ``fraction`` of the slack on each side."""
    slack_before = start
    slack_after = total - end
    new_start = int(slack_before * (1.0 - fraction))
    new_end = total - int(slack_after * (1.0 - fraction))
    if new_end <= new_start:
        return start, end
    return new_start, new_end


def _prepare_loot_table_image(image: Image.Image) -> Image.Image:
    """Trim transparency, then tighten gray grid margins so fit-to-window centers better."""
    rgba = _trim_transparent_margins(image)
    left, top, right, bottom = _axis_content_bounds(rgba)
    top, bottom = _shrink_margin(top, bottom, rgba.height, fraction=_MARGIN_SHRINK_FRACTION)
    left, right = _shrink_margin(left, right, rgba.width, fraction=_MARGIN_SHRINK_FRACTION)
    left = max(0, left - _TRIM_CONTENT_MARGIN)
    top = max(0, top - _TRIM_CONTENT_MARGIN)
    right = min(rgba.width, right + _TRIM_CONTENT_MARGIN)
    bottom = min(rgba.height, bottom + _TRIM_CONTENT_MARGIN)
    if (left, top, right, bottom) == (0, 0, rgba.width, rgba.height):
        return rgba
    return rgba.crop((left, top, right, bottom))


def _tk_photoimage(image: Image.Image, *, master: tk.Misc) -> ImageTk.PhotoImage:
    """Build a PhotoImage quickly (Tk is very slow for large RGBA bitmaps)."""
    if image.mode == "RGBA":
        flat = Image.new("RGB", image.size, _CANVAS_BACKGROUND_RGB)
        flat.paste(image, mask=image.split()[3])
        image = flat
    elif image.mode != "RGB":
        image = image.convert("RGB")
    return ImageTk.PhotoImage(image, master=master)


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            _APP_USER_MODEL_ID
        )
    except OSError as exc:
        logger.debug("Could not set AppUserModelID: %s", exc)


def _cached_icon_ico(png_path: Path) -> Path:
    ico_path = data_dir() / "app_icon.ico"
    if ico_path.is_file() and ico_path.stat().st_mtime >= png_path.stat().st_mtime:
        return ico_path
    image = Image.open(png_path)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    if max(image.size) < 256:
        scale = 256 / max(image.size)
        new_size = (
            max(1, int(image.width * scale)),
            max(1, int(image.height * scale)),
        )
        image = image.resize(new_size, Image.Resampling.NEAREST)
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(ico_path, format="ICO", sizes=_ICON_SIZES)
    return ico_path


class MainWindow:
    def __init__(
        self,
        root: tk.Tk,
        *,
        config: AppConfig,
        store: PlayerStore,
        player: LocalPlayerData,
    ) -> None:
        self.root = root
        self.config = config
        self.store = store
        self.player = player
        self._photo: ImageTk.PhotoImage | None = None
        self._source_image: Image.Image | None = None
        self._display_image: Image.Image | None = None
        self._display_size: tuple[int, int] = (0, 0)
        self._left_panel: ttk.Frame | None = None
        self._right_panel: ttk.Frame | None = None
        self._canvas_frame: ttk.LabelFrame | None = None
        self._loot_list_frame: ttk.LabelFrame | None = None
        self._paned: tk.PanedWindow | None = None
        self._custom_display_scale: float | None = None

        self.root.title("RotMG PPE Loot Tracker (Offline)")
        self.root.minsize(480, 360)
        self._build_ui()
        self._refresh_ppe_selector()
        self._refresh_loot_list()
        self._set_status("Loading loot table…")
        self.root.update_idletasks()
        # Defer heavy render so controls appear immediately; PhotoImage is cheap after RGB flatten.
        self.root.after_idle(self._initial_show)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _initial_show(self) -> None:
        _maximize_window(self.root)
        _apply_window_icon(self.root)
        self._favor_loot_table_pane()
        self.root.update_idletasks()
        self._refresh_loot_table_image()

    def _favor_loot_table_pane(self) -> None:
        """Keep the control column narrow so the loot table gets more horizontal space."""
        if self._paned is None or self._left_panel is None:
            return
        self.root.update_idletasks()
        try:
            self._paned.paneconfig(self._left_panel, minsize=_LEFT_PANEL_MIN_WIDTH)
            _set_paned_sash_x(self._paned, _LEFT_PANEL_MIN_WIDTH + 4)
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        paned = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            sashwidth=5,
            sashrelief=tk.RAISED,
            showhandle=False,
        )
        paned.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        left = ttk.Frame(paned, padding=_LEFT_PANEL_FRAME_PADDING)
        right = ttk.Frame(paned, padding=_LOOT_TABLE_FRAME_PADDING)
        paned.add(left, minsize=_LEFT_PANEL_MIN_WIDTH, stretch="never")
        paned.add(right, minsize=200, stretch="always")
        self._left_panel = left
        self._right_panel = right
        self._paned = paned

        self._build_controls(left)
        self._build_image_panel(right)
        self._bind_clear_loot_selection_on_outside_click()

        self.status_var = tk.StringVar(value="Ready.")
        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w")
        status.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

    def _build_controls(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.grid_propagate(True)

        ppe_frame = ttk.LabelFrame(parent, text="PPE Character", padding=_LABEL_FRAME_PADDING)
        ppe_frame.grid(row=0, column=0, sticky="ew")
        ppe_frame.columnconfigure(0, weight=1)
        ppe_frame.columnconfigure(1, weight=1)

        self.ppe_var = tk.StringVar()
        self.ppe_combo = ttk.Combobox(ppe_frame, textvariable=self.ppe_var, state="readonly")
        self.ppe_combo.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.ppe_combo.bind("<<ComboboxSelected>>", self._on_ppe_selected)

        ppe_btn_row = ttk.Frame(ppe_frame)
        ppe_btn_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ppe_btn_row.columnconfigure(0, weight=1)
        ppe_btn_row.columnconfigure(1, weight=1)
        ttk.Button(ppe_btn_row, text="New PPE…", command=self._create_ppe_dialog).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(ppe_btn_row, text="Delete PPE", command=self._delete_ppe).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        self.points_var = tk.StringVar(value="Points: 0.0")
        ttk.Label(ppe_frame, textvariable=self.points_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        entry_frame = ttk.LabelFrame(parent, text="Add Loot", padding=_LABEL_FRAME_PADDING)
        entry_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        entry_frame.columnconfigure(0, weight=1)

        ttk.Label(entry_frame, text="Item").grid(row=0, column=0, sticky="w")
        self.item_var = tk.StringVar()
        self.item_entry = ItemAutocomplete(
            entry_frame,
            variable=self.item_var,
            on_change=self._update_item_entry_state,
        )
        self.item_entry.grid(row=1, column=0, sticky="ew")

        self.shiny_var = tk.BooleanVar(value=False)
        self.shiny_check = ttk.Checkbutton(
            entry_frame,
            text="Shiny",
            variable=self.shiny_var,
            command=self._on_shiny_toggled,
        )
        self.shiny_check.grid(row=2, column=0, sticky="w", pady=(6, 0))

        ttk.Label(entry_frame, text="Rarity (equipment only)").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.rarity_var = tk.StringVar(value="common")
        self.rarity_selector = RaritySelector(entry_frame, variable=self.rarity_var)
        self.rarity_selector.grid(row=4, column=0, sticky="w", pady=(4, 0))
        self._update_item_entry_state()

        ttk.Button(entry_frame, text="Add Item", command=self._add_item).grid(row=5, column=0, sticky="ew", pady=(8, 0))

        variant_frame = ttk.LabelFrame(parent, text="Loot Table View", padding=_LABEL_FRAME_PADDING)
        variant_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        self.include_skins_var = tk.BooleanVar(value=self.config.include_skins)
        self.include_limited_var = tk.BooleanVar(value=self.config.include_limited)
        ttk.Checkbutton(
            variant_frame,
            text="Include skins & treasures",
            variable=self.include_skins_var,
            command=self._on_variant_changed,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            variant_frame,
            text="Include limited",
            variable=self.include_limited_var,
            command=self._on_variant_changed,
        ).grid(row=1, column=0, sticky="w")
        scale_row = ttk.Frame(variant_frame)
        scale_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(scale_row, text="Display scale").grid(row=0, column=0, sticky="w")
        self.display_scale_var = tk.StringVar(
            value=str(int(round(self.config.loot_table_display_scale * 100))),
        )
        self.display_scale_spin = ttk.Spinbox(
            scale_row,
            from_=_DISPLAY_SCALE_PERCENT_MIN,
            to=_DISPLAY_SCALE_PERCENT_MAX,
            increment=5,
            width=5,
            textvariable=self.display_scale_var,
            command=self._on_display_scale_changed,
        )
        self.display_scale_spin.grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(scale_row, text="%").grid(row=0, column=2, sticky="w")
        self.display_scale_spin.bind("<FocusOut>", self._on_display_scale_focus_out)
        self.display_scale_spin.bind("<Return>", self._on_display_scale_focus_out)
        view_btn_row = ttk.Frame(variant_frame)
        view_btn_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        view_btn_row.columnconfigure(0, weight=1)
        view_btn_row.columnconfigure(1, weight=1)
        ttk.Button(view_btn_row, text="Refresh Image", command=self._refresh_loot_table_image).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(view_btn_row, text="Fit to Window", command=self._fit_loot_table_to_window).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        loot_frame = ttk.LabelFrame(parent, text="Current Loot", padding=_LABEL_FRAME_PADDING)
        self._loot_list_frame = loot_frame
        loot_frame.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        parent.rowconfigure(3, weight=1)
        loot_frame.rowconfigure(0, weight=1)
        loot_frame.columnconfigure(0, weight=1)

        self.loot_list = LootListView(loot_frame, height=10)
        self.loot_list.grid(row=0, column=0, sticky="nsew")

        remove_row = ttk.Frame(loot_frame)
        remove_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        remove_row.columnconfigure(0, weight=1)
        remove_row.columnconfigure(1, weight=1)
        ttk.Button(remove_row, text="Remove 1 Selected", command=self._remove_selected).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(remove_row, text="Remove All Selected", command=self._remove_all_selected).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        action_frame = ttk.Frame(parent, padding=(0, 8, 0, 0))
        action_frame.grid(row=4, column=0, sticky="ew")
        action_frame.columnconfigure(0, weight=1)
        ttk.Button(action_frame, text="Export", command=self._export_loot_table).grid(
            row=0, column=0, sticky="ew"
        )

    def _build_image_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        canvas_frame = ttk.LabelFrame(parent, text="Loot Table", padding=_LOOT_TABLE_FRAME_PADDING)
        canvas_frame.grid(row=0, column=0, sticky="nsew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self._canvas_frame = canvas_frame

        self.canvas = tk.Canvas(canvas_frame, background="#2b2b2b", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        y_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        self.canvas.bind("<Enter>", self._bind_loot_table_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_loot_table_mousewheel)

    @staticmethod
    def _widget_is_descendant(widget: tk.Misc, ancestor: tk.Misc) -> bool:
        current: tk.Misc | None = widget
        while current is not None:
            if current == ancestor:
                return True
            current = current.master  # type: ignore[assignment]
        return False

    def _bind_clear_loot_selection_on_outside_click(self) -> None:
        """Clear loot list highlight when the user clicks outside Current Loot."""
        for target in (self.root, self._paned, self._left_panel, self._right_panel):
            if target is not None:
                target.bind("<Button-1>", self._on_pointer_down_clear_loot_selection, add="+")

    def _on_pointer_down_clear_loot_selection(self, event: tk.Event) -> None:
        clicked = event.widget

        def clear_if_outside() -> None:
            if self._loot_list_frame is not None and self._widget_is_descendant(
                clicked, self._loot_list_frame
            ):
                return
            self.loot_list.selection_clear(0, tk.END)

        self.root.after_idle(clear_if_outside)

    def _active_ppe(self) -> LocalPPE | None:
        return self.player.active_ppe()

    def _ppe_label(self, ppe: LocalPPE) -> str:
        return f"#{ppe.id} {ppe.class_name} ({ppe.points:.1f} pts)"

    def _refresh_ppe_selector(self) -> None:
        labels = [self._ppe_label(ppe) for ppe in self.player.ppes]
        self.ppe_combo["values"] = labels
        active = self._active_ppe()
        if active:
            self.ppe_var.set(self._ppe_label(active))
            self.points_var.set(f"Points: {active.points:.1f}")
        else:
            self.ppe_var.set("")
            self.points_var.set("Points: —")

    def _refresh_loot_list(self) -> None:
        ppe = self._active_ppe()
        if not ppe:
            self.loot_list.set_entries([])
            return
        entries = sorted(ppe.loot, key=lambda item: item.item_name.casefold())
        self.loot_list.set_entries(entries)

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)
        logger.info(message)

    def _autosave_player(self) -> None:
        try:
            self.store.save(self.player)
        except ValueError as exc:
            messagebox.showerror("Save failed", str(exc))
            self._set_status(f"Could not save player data: {exc}")

    def _on_ppe_selected(self, _event=None) -> None:
        label = self.ppe_var.get()
        for ppe in self.player.ppes:
            if self._ppe_label(ppe) == label:
                self.player.active_ppe_id = ppe.id
                break
        self._refresh_ppe_selector()
        self._refresh_loot_list()
        self._refresh_loot_table_image()

    def _create_ppe_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("New PPE")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Class").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        class_var = tk.StringVar(value=ROTMG_CLASSES[0])
        class_combo = ttk.Combobox(dialog, textvariable=class_var, values=ROTMG_CLASSES, state="readonly")
        class_combo.grid(row=0, column=1, padx=8, pady=8, sticky="ew")

        def confirm() -> None:
            ppe = create_ppe(self.player, class_name=class_var.get())
            self._autosave_player()
            self._refresh_ppe_selector()
            self._refresh_loot_list()
            self._refresh_loot_table_image()
            self._set_status(f"Created {self._ppe_label(ppe)}.")
            dialog.destroy()

        ttk.Button(dialog, text="Create", command=confirm).grid(row=1, column=0, columnspan=2, pady=8)
        dialog.columnconfigure(1, weight=1)

    def _delete_ppe(self) -> None:
        ppe = self._active_ppe()
        if not ppe:
            messagebox.showwarning("No PPE", "There is no PPE character to delete.")
            return

        loot_count = sum(entry.quantity for entry in ppe.loot)
        loot_note = f" and all {loot_count} loot item(s)" if loot_count else ""
        if not messagebox.askyesno(
            "Delete PPE?",
            f"Delete {ppe.class_name} (#{ppe.id}){loot_note}? This cannot be undone.",
        ):
            return

        deleted = delete_ppe(self.player, ppe_id=ppe.id)
        if deleted is None:
            messagebox.showerror("Delete failed", "Could not find that PPE character.")
            return

        self._autosave_player()
        self._refresh_ppe_selector()
        self._refresh_loot_list()
        self._refresh_loot_table_image()
        self._set_status(f"Deleted {deleted.class_name} (#{deleted.id}).")

    def _on_shiny_toggled(self) -> None:
        self._update_item_entry_state()

    def _update_item_entry_state(self) -> None:
        item = self.item_var.get().strip()
        shiny_only = bool(item and is_shiny_only_item(item))
        if shiny_only:
            self.shiny_var.set(True)
            self.shiny_check.configure(state="disabled")
        elif item and has_shiny_variant(item):
            self.shiny_check.configure(state="normal")
        else:
            self.shiny_var.set(False)
            self.shiny_check.configure(state="disabled")

        shiny = self.shiny_var.get()
        self.rarity_selector.set_shiny(shiny)

        fixed_rarity = required_rarity(item, shiny=shiny) if item else None
        if item and (supports_rarity_tiers(item) or fixed_rarity):
            self.rarity_selector.set_enabled(True)
            if fixed_rarity:
                self.rarity_var.set(fixed_rarity)
                self.rarity_selector.set_allowed_rarities(frozenset({fixed_rarity}))
            else:
                self.rarity_selector.set_allowed_rarities(None)
        else:
            self.rarity_var.set("common")
            self.rarity_selector.set_allowed_rarities(None)
            self.rarity_selector.set_enabled(False)

    def _selected_loot_entry(self) -> LocalLootEntry | None:
        ppe = self._active_ppe()
        if not ppe:
            return None
        selection = self.loot_list.curselection()
        if not selection:
            return None
        return self.loot_list.entry_at(selection[0])

    def _add_item(self) -> None:
        ppe = self._active_ppe()
        if not ppe:
            messagebox.showwarning("No PPE", "Create a PPE character before adding loot.")
            return
        item_name = self.item_var.get().strip()
        if not item_name:
            messagebox.showwarning("Missing item", "Choose an item from the catalog.")
            return
        try:
            result = add_loot(
                self.player,
                ppe_id=ppe.id,
                item_name=item_name,
                shiny=self.shiny_var.get(),
                rarity=self.rarity_var.get(),
                config=self.config,
            )
        except ValueError as exc:
            messagebox.showerror("Could not add loot", str(exc))
            return

        self._autosave_player()
        self._refresh_ppe_selector()
        self._refresh_loot_list()
        self._refresh_loot_table_image()
        self._set_status(
            f"Added {result.item_name} (+{result.points_delta:.1f} pts). "
            f"PPE total: {result.ppe_points:.1f}."
        )

    def _remove_selected(self) -> None:
        ppe = self._active_ppe()
        entry = self._selected_loot_entry()
        if not ppe or not entry:
            messagebox.showwarning("Nothing selected", "Select a loot entry to remove one copy.")
            return
        try:
            result = remove_loot(
                self.player,
                ppe_id=ppe.id,
                item_name=entry.item_name,
                shiny=entry.shiny,
                rarity=entry.rarity,
                config=self.config,
            )
        except ValueError as exc:
            messagebox.showerror("Could not remove loot", str(exc))
            return

        self._autosave_player()
        self._refresh_ppe_selector()
        self._refresh_loot_list()
        self._refresh_loot_table_image()
        self._set_status(
            f"Removed one {entry.item_name} ({result.points_delta:.1f} pts). "
            f"PPE total: {result.ppe_points:.1f}."
        )

    def _remove_all_selected(self) -> None:
        ppe = self._active_ppe()
        entry = self._selected_loot_entry()
        if not ppe or not entry:
            messagebox.showwarning("Nothing selected", "Select a loot entry to remove all copies.")
            return
        if entry.quantity <= 1:
            self._remove_selected()
            return

        item_label = format_loot_label(entry, include_quantity=False)
        if not messagebox.askyesno(
            "Remove all copies?",
            f"Remove all {entry.quantity}× {item_label} from this PPE?",
        ):
            return

        try:
            result = remove_all_loot(
                self.player,
                ppe_id=ppe.id,
                item_name=entry.item_name,
                shiny=entry.shiny,
                rarity=entry.rarity,
                config=self.config,
            )
        except ValueError as exc:
            messagebox.showerror("Could not remove loot", str(exc))
            return

        self._autosave_player()
        self._refresh_ppe_selector()
        self._refresh_loot_list()
        self._refresh_loot_table_image()
        self._set_status(
            f"Removed all {result.removed_count}× {entry.item_name} ({result.points_delta:.1f} pts). "
            f"PPE total: {result.ppe_points:.1f}."
        )

    def _on_variant_changed(self) -> None:
        self.config.include_skins = self.include_skins_var.get()
        self.config.include_limited = self.include_limited_var.get()
        save_config(self.config)
        self._refresh_loot_table_image()

    def _parse_display_scale_percent(self, text: str) -> int:
        cleaned = text.strip().rstrip("%")
        try:
            percent = int(float(cleaned))
        except ValueError:
            percent = int(round(self.config.loot_table_display_scale * 100))
        return max(_DISPLAY_SCALE_PERCENT_MIN, min(_DISPLAY_SCALE_PERCENT_MAX, percent))

    def _on_display_scale_focus_out(self, _event: tk.Event | None = None) -> None:
        self._apply_display_scale_from_ui()

    def _on_display_scale_changed(self) -> None:
        self._apply_display_scale_from_ui()

    def _apply_display_scale_from_ui(self) -> None:
        percent = self._parse_display_scale_percent(self.display_scale_var.get())
        scale = normalize_loot_table_display_scale(percent / 100.0)
        self.display_scale_var.set(str(percent))

        if abs(scale - self.config.loot_table_display_scale) < 1e-9:
            return

        self.config.loot_table_display_scale = scale
        save_config(self.config)
        self._custom_display_scale = None
        if self._source_image is not None:
            self._update_canvas_image()
        self._set_status(f"Loot table display scale set to {percent}%.")

    def _clear_loot_table_image(self) -> None:
        self.canvas.delete("all")
        self._photo = None
        self._display_size = (0, 0)
        if self._display_image is not None and self._display_image is not self._source_image:
            self._display_image.close()
        self._display_image = None
        if self._source_image is not None:
            self._source_image.close()
            self._source_image = None

    def _active_display_scale(self) -> float:
        if self._custom_display_scale is not None:
            return self._custom_display_scale
        return self.config.loot_table_display_scale or _DEFAULT_IMAGE_DISPLAY_SCALE

    def _scaled_display_size(
        self,
        width: int,
        height: int,
        *,
        scale: float | None = None,
    ) -> tuple[int, int]:
        factor = scale if scale is not None else self._active_display_scale()
        return (
            max(1, int(width * factor)),
            max(1, int(height * factor)),
        )

    def _canvas_viewport_size(self, *, for_fit: bool = False) -> tuple[int, int]:
        """Return the drawable canvas area (excludes scrollbar grid cells)."""
        self.root.update_idletasks()
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        if width <= 1 or height <= 1:
            if self._canvas_frame is not None:
                width = max(1, self._canvas_frame.winfo_width() - _SCROLLBAR_THICKNESS)
                height = max(1, self._canvas_frame.winfo_height() - _SCROLLBAR_THICKNESS)
        if for_fit:
            width = max(1, width - _FIT_VIEW_INSET)
            height = max(1, height - _FIT_VIEW_INSET)
        return width, height

    def _compute_fit_to_window_scale(self, src_w: int, src_h: int) -> float:
        view_w, view_h = self._canvas_viewport_size(for_fit=True)
        scale = min(view_w / src_w, view_h / src_h)
        scale = max(0.05, min(scale, 1.0))

        # Nudge down if rounding would still leave scrollbars visible.
        live_w, live_h = self._canvas_viewport_size(for_fit=False)
        for _ in range(6):
            disp_w = max(1, int(src_w * scale))
            disp_h = max(1, int(src_h * scale))
            if disp_w <= live_w and disp_h <= live_h:
                break
            scale *= min(live_w / disp_w, live_h / disp_h, 0.99)

        return scale

    def _fit_loot_table_to_window(self) -> None:
        if self._source_image is None:
            messagebox.showinfo(
                "No loot table",
                "Refresh the loot table image first, then use Fit to Window.",
            )
            return

        src_w, src_h = self._source_image.size
        if src_w <= 0 or src_h <= 0:
            return

        scale = self._compute_fit_to_window_scale(src_w, src_h)
        self._custom_display_scale = scale
        self._update_canvas_image()
        self.root.update_idletasks()
        self._set_status(f"Loot table scaled to {scale * 100:.0f}% to fit the current view.")

    def _update_canvas_image(self) -> None:
        if self._source_image is None:
            return

        display_w, display_h = self._scaled_display_size(
            self._source_image.width,
            self._source_image.height,
        )
        self._display_size = (display_w, display_h)

        if self._display_image is not None and self._display_image is not self._source_image:
            self._display_image.close()

        if display_w == self._source_image.width and display_h == self._source_image.height:
            self._display_image = self._source_image
        else:
            self._display_image = self._source_image.resize(
                (display_w, display_h),
                Image.Resampling.LANCZOS,
            )

        self.root.update_idletasks()
        view_w = max(1, self.canvas.winfo_width())
        view_h = max(1, self.canvas.winfo_height())
        scroll_w = max(display_w, view_w)
        scroll_h = max(display_h, view_h)

        self._photo = _tk_photoimage(self._display_image, master=self.canvas)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, scroll_w, scroll_h))
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _bind_loot_table_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_loot_table_mousewheel)
        if sys.platform == "linux":
            self.canvas.bind_all("<Button-4>", self._on_loot_table_mousewheel_linux)
            self.canvas.bind_all("<Button-5>", self._on_loot_table_mousewheel_linux)

    def _unbind_loot_table_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        if sys.platform == "linux":
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

    def _on_loot_table_mousewheel(self, event: tk.Event) -> None:
        if sys.platform == "darwin":
            self.canvas.yview_scroll(-int(event.delta), "units")
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_loot_table_mousewheel_linux(self, event: tk.Event) -> None:
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    def _refresh_loot_table_image(self) -> None:
        ppe = self._active_ppe()
        self._clear_loot_table_image()

        if not ppe:
            self._set_status("Create a PPE to preview the loot table.")
            return

        try:
            result = render_loot_table(
                flatten_loot_for_render(ppe),
                include_skins=self.include_skins_var.get(),
                include_limited=self.include_limited_var.get(),
            )
        except Exception as exc:
            logger.exception("Loot table render failed")
            self._set_status(f"Loot table image unavailable: {exc}")
            return

        self._custom_display_scale = None
        prepared = _prepare_loot_table_image(result.image)
        if prepared is not result.image:
            result.image.close()
        self._source_image = prepared
        self._update_canvas_image()
        self.root.after_idle(self._apply_loot_table_window_layout)

        parts = [f"Placed {result.items_placed} item(s) on the {result.variant} table."]
        if result.items_not_found:
            preview = ", ".join(result.items_not_found[:5])
            if len(result.items_not_found) > 5:
                preview += f" (+{len(result.items_not_found) - 5} more)"
            parts.append(f"Missing sprites: {preview}")
        if result.items_excluded:
            parts.append(f"{len(result.items_excluded)} item(s) hidden by this variant.")
        self._set_status(" ".join(parts))

    def _apply_loot_table_window_layout(self) -> None:
        """Reflow panes after render without forcing window size to the image dimensions."""
        self._favor_loot_table_pane()
        self.root.update_idletasks()
        if self._source_image is not None:
            self._update_canvas_image()

    def _on_close(self) -> None:
        self.root.destroy()

    def _default_loot_table_export_name(self) -> str:
        ppe = self._active_ppe()
        if ppe is None:
            return "loot_table.png"
        safe_name = "".join(
            ch if ch.isalnum() or ch in "._-" else "_"
            for ch in self.player.player_name.strip()
        ).strip("._") or "player"
        return f"{safe_name}_ppe{ppe.id}_loot_table.png"

    def _export_loot_table(self) -> None:
        if self._source_image is None:
            messagebox.showwarning("Nothing to export", "Create a PPE and render a loot table first.")
            return

        path = filedialog.asksaveasfilename(
            title="Export loot table",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
            initialfile=self._default_loot_table_export_name(),
        )
        if not path:
            return

        try:
            export_image = self._source_image.copy()
            if export_image.mode not in ("RGB", "RGBA"):
                export_image = export_image.convert("RGBA")
            export_image.save(path, format="PNG")
            export_image.close()
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        self._set_status(f"Exported loot table to {path}")


def _apply_window_icon(root: tk.Tk) -> None:
    path = app_icon_path()
    if not path.is_file():
        logger.warning("App icon not found: %s", path)
        return
    try:
        if sys.platform == "win32":
            ico_path = str(_cached_icon_ico(path).resolve())
            root.iconbitmap(ico_path)
            root.iconbitmap(default=ico_path)
        else:
            image = Image.open(path)
            if image.mode not in ("RGBA", "RGB"):
                image = image.convert("RGBA")
            photo = ImageTk.PhotoImage(image)
            root.iconphoto(True, photo)
            root._app_icon_photo = photo  # type: ignore[attr-defined]  # keep reference alive
    except (OSError, tk.TclError) as exc:
        logger.warning("Could not set window icon from %s: %s", path, exc)


def run_app(config: AppConfig, store: PlayerStore, player: LocalPlayerData) -> None:
    _set_windows_app_user_model_id()
    root = tk.Tk()
    _apply_window_icon(root)
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    MainWindow(root, config=config, store=store, player=player)
    root.mainloop()
