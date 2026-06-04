"""Read-only loot list with seamless bold first letter on each item name."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from app.core_adapter.loot_service import loot_label_display
from app.storage.models import LocalLootEntry

_SELECTED_BG = "#d8e8f8"


class LootListView(ttk.Frame):
    """Listbox-like loot list; bolds the first letter of each item name in one text flow."""

    def __init__(self, master: tk.Misc, *, height: int = 10, **kwargs: object) -> None:
        super().__init__(master, **kwargs)
        self._entries: list[LocalLootEntry] = []
        self._selected_index: int | None = None

        style = ttk.Style(self)
        bg = style.lookup("TLabel", "background") or style.lookup("TFrame", "background") or "#f0f0f0"
        fg = style.lookup("TLabel", "foreground") or "#000000"

        self._base_font = tkfont.nametofont("TkDefaultFont")
        self._bold_font = self._base_font.copy()
        self._bold_font.configure(weight="bold")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.text = tk.Text(
            self,
            height=height,
            wrap=tk.NONE,
            font=self._base_font,
            background=bg,
            foreground=fg,
            borderwidth=1,
            relief=tk.SUNKEN,
            highlightthickness=0,
            cursor="arrow",
            exportselection=False,
            padx=4,
            pady=2,
            spacing1=0,
            spacing2=0,
            spacing3=0,
        )
        self.text.grid(row=0, column=0, sticky="nsew")
        self.text.tag_configure("item_first", font=self._bold_font)
        self.text.tag_configure("selected", background=_SELECTED_BG)

        scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)

        self.text.bind("<Button-1>", self._on_click)
        self.text.bind("<Key>", lambda _event: "break")
        self.text.bind("<Enter>", self._bind_mousewheel)
        self.text.bind("<Leave>", self._unbind_mousewheel)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.text.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        self.text.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.text.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def set_entries(self, entries: list[LocalLootEntry]) -> None:
        self._entries = list(entries)
        self._selected_index = None

        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        for index, entry in enumerate(self._entries):
            line_tag = f"line_{index}"
            display = loot_label_display(entry)
            self.text.insert(tk.END, display.prefix, line_tag)
            if display.item_first:
                self.text.insert(tk.END, display.item_first, ("item_first", line_tag))
            self.text.insert(tk.END, f"{display.item_rest}\n", line_tag)
        self.text.configure(state=tk.DISABLED)
        self.text.yview_moveto(0)

    def entry_at(self, index: int) -> LocalLootEntry | None:
        if index < 0 or index >= len(self._entries):
            return None
        return self._entries[index]

    def size(self) -> int:
        return len(self._entries)

    def curselection(self) -> tuple[int, ...]:
        if self._selected_index is None:
            return ()
        return (self._selected_index,)

    def selection_clear(self, _start: int, _end: int) -> None:
        self._select_index(None)

    def _select_index(self, index: int | None) -> None:
        if index is not None and (index < 0 or index >= len(self._entries)):
            index = None

        self.text.configure(state=tk.NORMAL)
        self.text.tag_remove("selected", "1.0", tk.END)
        self._selected_index = index
        if index is not None:
            line = index + 1
            self.text.tag_add("selected", f"{line}.0", f"{line}.end")
        self.text.configure(state=tk.DISABLED)

    def _line_index_at(self, event: tk.Event) -> int | None:
        index = self.text.index(f"@{event.x},{event.y}")
        line = int(str(index).split(".")[0]) - 1
        if line < 0 or line >= len(self._entries):
            return None
        return line

    def _on_click(self, event: tk.Event) -> str | None:
        if not self._entries:
            self.selection_clear(0, tk.END)
            return "break"

        line = self._line_index_at(event)
        if line is None:
            self.selection_clear(0, tk.END)
            return "break"

        self._select_index(line)
        return None
