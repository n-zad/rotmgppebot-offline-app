"""Item name entry with a floating suggestion list."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from app.core_adapter.loot_catalog import filter_item_names

_LISTBOX_HEIGHT = 8
_POPUP_PAD = 1
_HIDE_DELAY_MS = 150
_IGNORE_KEYS = frozenset(
    {
        "Shift_L",
        "Shift_R",
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Caps_Lock",
        "Num_Lock",
        "Tab",
        "Return",
        "Escape",
        "Up",
        "Down",
        "Left",
        "Right",
        "Prior",
        "Next",
        "Home",
        "End",
        "Win_L",
        "Win_R",
        "Menu",
    }
)


class ItemAutocomplete(ttk.Frame):
    """Type-ahead item picker; suggestions float over content below the entry."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        variable: tk.StringVar,
        on_change: Callable[[], None] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(master, **kwargs)
        self._variable = variable
        self._on_change = on_change
        self._suggestions_visible = False
        self._hide_after_id: str | None = None

        self.columnconfigure(0, weight=1)

        self.entry = ttk.Entry(self, textvariable=self._variable)
        self.entry.grid(row=0, column=0, sticky="ew")

        root = self.winfo_toplevel()
        self._popup = tk.Toplevel(root)
        self._popup.withdraw()
        self._popup.overrideredirect(True)
        self._popup.transient(root)
        self._popup.configure(borderwidth=1, relief=tk.SOLID)

        list_frame = ttk.Frame(self._popup, padding=_POPUP_PAD)
        list_frame.pack(fill=tk.BOTH, expand=True)
        list_frame.columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, height=_LISTBOX_HEIGHT, exportselection=False)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=scroll.set)
        self._list_frame = list_frame

        self.entry.bind("<KeyRelease>", self._on_entry_key_release)
        self.entry.bind("<KeyPress>", self._on_entry_key_press)
        self.entry.bind("<Button-1>", self._on_entry_button_press)
        self.entry.bind("<FocusIn>", self._on_entry_focus_in)
        self.entry.bind("<FocusOut>", self._on_entry_focus_out)
        self.listbox.bind("<Button-1>", self._on_listbox_button)
        self._popup.bind("<Enter>", self._cancel_hide)
        self._popup.bind("<FocusIn>", self._cancel_hide)

        root.bind("<Configure>", self._on_root_configure, add="+")
        root.bind("<Button-1>", self._on_global_button_press, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _safe_focus_get(self) -> tk.Misc | None:
        try:
            return self.focus_get()
        except (KeyError, tk.TclError):
            return None

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def _is_internal_widget(self, widget: tk.Misc | None) -> bool:
        current: tk.Misc | None = widget
        while current is not None:
            if current in (self, self._popup):
                return True
            current = current.master  # type: ignore[assignment]
        return False

    def _entry_has_focus(self) -> bool:
        focused = self._safe_focus_get()
        return focused is not None and focused == self.entry

    def _defocus_entry(self) -> None:
        try:
            self.winfo_toplevel().focus_set()
        except tk.TclError:
            pass

    def _select_all_entry_text(self) -> None:
        if not self._entry_has_focus():
            return
        self.entry.select_range(0, tk.END)
        self.entry.icursor(tk.END)

    def _cancel_hide(self, *_args: object) -> None:
        if self._hide_after_id is not None:
            self.after_cancel(self._hide_after_id)
            self._hide_after_id = None

    def _schedule_hide(self) -> None:
        self._cancel_hide()
        self._hide_after_id = self.after(_HIDE_DELAY_MS, self._maybe_hide_suggestions)

    def _is_pointer_over_popup(self) -> bool:
        if not self._suggestions_visible:
            return False
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            widget = self.winfo_containing(x, y)
        except tk.TclError:
            return False
        return widget is not None and self._is_internal_widget(widget)

    def _position_popup(self) -> None:
        self.update_idletasks()
        self._list_frame.update_idletasks()
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        width = max(self.entry.winfo_width(), 180)
        height = self._list_frame.winfo_reqheight() + (_POPUP_PAD * 2)
        self._popup.geometry(f"{width}x{height}+{x}+{y}")

    def _show_suggestions(self, matches: list[str]) -> None:
        self.listbox.delete(0, tk.END)
        for name in matches:
            self.listbox.insert(tk.END, name)
        if not matches:
            self._hide_suggestions()
            return

        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(0)
        self.listbox.activate(0)
        self._position_popup()
        self._popup.deiconify()
        self._popup.lift()
        self._suggestions_visible = True

    def _hide_suggestions(self) -> None:
        self._cancel_hide()
        self._popup.withdraw()
        self._suggestions_visible = False

    def _refresh_suggestions(self) -> None:
        matches = filter_item_names(self._variable.get())
        if matches:
            self._show_suggestions(matches)
        else:
            self._hide_suggestions()
        self._notify_change()

    def _select_listbox_index(self, index: int) -> None:
        if index < 0 or index >= self.listbox.size():
            return
        value = self.listbox.get(index)
        self._variable.set(value)
        self._hide_suggestions()
        self._notify_change()
        self.entry.focus_set()

    def _accept_listbox_selection(self) -> bool:
        selection = self.listbox.curselection()
        if not selection:
            return False
        self._select_listbox_index(selection[0])
        return True

    def _move_selection(self, delta: int) -> None:
        if not self._suggestions_visible or self.listbox.size() == 0:
            return
        current = self.listbox.curselection()
        index = current[0] if current else 0
        index = max(0, min(self.listbox.size() - 1, index + delta))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)

    def _on_entry_button_press(self, _event: tk.Event) -> None:
        self.after_idle(self._select_all_entry_text)

    def _on_entry_focus_in(self, _event: tk.Event) -> None:
        self._refresh_suggestions()

    def _on_entry_focus_out(self, _event: tk.Event) -> None:
        self._schedule_hide()

    def _maybe_hide_suggestions(self) -> None:
        self._hide_after_id = None
        if self._is_internal_widget(self._safe_focus_get()):
            return
        if self._is_pointer_over_popup():
            return
        self._hide_suggestions()

    def _on_global_button_press(self, event: tk.Event) -> None:
        if self._is_internal_widget(event.widget):
            return
        if self._entry_has_focus():
            self._defocus_entry()
        if self._suggestions_visible:
            self._hide_suggestions()

    def _on_root_configure(self, event: tk.Event) -> None:
        if not self._suggestions_visible:
            return
        if event.widget is not self.winfo_toplevel():
            return
        self._position_popup()

    def _on_destroy(self, _event: tk.Event) -> None:
        self._cancel_hide()
        if self._popup.winfo_exists():
            self._popup.destroy()

    def _on_entry_key_release(self, event: tk.Event) -> None:
        if event.keysym in _IGNORE_KEYS:
            return
        self._refresh_suggestions()

    def _on_entry_key_press(self, event: tk.Event) -> str | None:
        if event.keysym == "Down":
            if self._suggestions_visible:
                self._move_selection(1)
            return "break"
        if event.keysym == "Up":
            if self._suggestions_visible:
                self._move_selection(-1)
            return "break"
        if event.keysym == "Return":
            if self._suggestions_visible and self._accept_listbox_selection():
                return "break"
            return None
        if event.keysym == "Escape":
            if self._suggestions_visible:
                self._hide_suggestions()
                return "break"
        return None

    def _on_listbox_button(self, event: tk.Event) -> str:
        self._cancel_hide()
        index = self.listbox.nearest(event.y)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self._select_listbox_index(index)
        return "break"
