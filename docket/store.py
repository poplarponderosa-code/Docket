"""SQLite storage for lists (tabs), items and settings. No Qt in here."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

PRIORITIES = ("High", "Med", "Low")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tabs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    popped INTEGER NOT NULL DEFAULT 0,
    geometry TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'list',
    color TEXT NOT NULL DEFAULT '',
    collapsed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tab_id INTEGER NOT NULL REFERENCES tabs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    due TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    reminder INTEGER NOT NULL DEFAULT 0,
    reminded INTEGER NOT NULL DEFAULT 0,
    remind_time TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ITEM_FIELDS = {"name", "due", "end", "priority", "notes", "reminder", "reminded", "remind_time", "done", "tab_id"}


@dataclass
class Tab:
    id: int
    name: str
    position: int = 0
    popped: bool = False
    geometry: str = ""
    kind: str = "list"      # "list" (dates & priority) or "checklist"
    color: str = ""         # a key from themes.LIST_COLORS, or "" for the theme accent
    collapsed: bool = False # shown as a pill (pop-out windows)

    @property
    def is_checklist(self) -> bool:
        return self.kind == "checklist"


@dataclass
class Item:
    id: int
    tab_id: int
    name: str
    due: str = ""          # ISO date or ""
    end: str = ""          # ISO date or "" (end of a range)
    priority: int = 1      # 0 High, 1 Med, 2 Low
    notes: str = ""
    reminder: bool = False
    reminded: bool = False
    done: bool = False
    created: str = ""
    remind_time: str = ""   # "HH:MM", or "" to use the default from Settings
    position: int = 0       # manual order (used by checklists)


class Store:
    """Change listeners get the tab id that changed, or None for list-level changes.

    quiet=True changes (typing in notes, editing dates in an open row) skip the
    change listeners, so the open row isn't rebuilt under the cursor, but still
    reach the "dirty" listeners used for backups and counts.
    """

    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()
        self._listeners: list[Callable[[int | None], None]] = []
        self._dirty_listeners: list[Callable[[], None]] = []

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(items)")}
        if "remind_time" not in cols:
            self.db.execute("ALTER TABLE items ADD COLUMN remind_time TEXT NOT NULL DEFAULT ''")
        if "position" not in cols:
            self.db.execute("ALTER TABLE items ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
            self.db.execute("UPDATE items SET position = id")
        tcols = {r["name"] for r in self.db.execute("PRAGMA table_info(tabs)")}
        if "kind" not in tcols:
            self.db.execute("ALTER TABLE tabs ADD COLUMN kind TEXT NOT NULL DEFAULT 'list'")
        if "color" not in tcols:
            self.db.execute("ALTER TABLE tabs ADD COLUMN color TEXT NOT NULL DEFAULT ''")
        if "collapsed" not in tcols:
            self.db.execute("ALTER TABLE tabs ADD COLUMN collapsed INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    # ---- notifications -----------------------------------------------------
    def subscribe(self, cb: Callable[[int | None], None]) -> None:
        self._listeners.append(cb)

    def subscribe_dirty(self, cb: Callable[[], None]) -> None:
        self._dirty_listeners.append(cb)

    def _emit(self, tab_id: int | None, quiet: bool = False, dirty: bool = True) -> None:
        self.db.commit()
        if not quiet:
            for cb in list(self._listeners):
                cb(tab_id)
        if dirty:
            for cb in list(self._dirty_listeners):
                cb()

    # ---- tabs --------------------------------------------------------------
    @staticmethod
    def _tab(row: sqlite3.Row) -> Tab:
        return Tab(row["id"], row["name"], row["position"], bool(row["popped"]), row["geometry"],
                   row["kind"] or "list", row["color"] or "", bool(row["collapsed"]))

    def tabs(self) -> list[Tab]:
        return [self._tab(r) for r in self.db.execute("SELECT * FROM tabs ORDER BY position, id")]

    def tab(self, tab_id: int) -> Tab | None:
        r = self.db.execute("SELECT * FROM tabs WHERE id = ?", (tab_id,)).fetchone()
        return self._tab(r) if r else None

    def add_tab(self, name: str, kind: str = "list", color: str = "") -> Tab:
        tab_id = self._insert_tab(name, kind, color)
        self._emit(None)
        return self.tab(tab_id)

    def _insert_tab(self, name: str, kind: str = "list", color: str = "") -> int:
        pos = self.db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM tabs").fetchone()[0]
        kind = kind if kind in ("list", "checklist") else "list"
        cur = self.db.execute("INSERT INTO tabs (name, position, kind, color) VALUES (?, ?, ?, ?)",
                              (name or "List", pos, kind, color or ""))
        return cur.lastrowid

    def set_tab_kind(self, tab_id: int, kind: str) -> None:
        self.db.execute("UPDATE tabs SET kind = ? WHERE id = ?", (kind, tab_id))
        self._emit(None)

    def set_tab_color(self, tab_id: int, color: str) -> None:
        self.db.execute("UPDATE tabs SET color = ? WHERE id = ?", (color, tab_id))
        self._emit(None, dirty=False)

    def set_tab_collapsed(self, tab_id: int, collapsed: bool) -> None:
        self.db.execute("UPDATE tabs SET collapsed = ? WHERE id = ?", (int(collapsed), tab_id))
        self._emit(None, quiet=True, dirty=False)

    def rename_tab(self, tab_id: int, name: str) -> None:
        self.db.execute("UPDATE tabs SET name = ? WHERE id = ?", (name, tab_id))
        self._emit(None)

    def delete_tab(self, tab_id: int) -> None:
        self.db.execute("DELETE FROM items WHERE tab_id = ?", (tab_id,))
        self.db.execute("DELETE FROM tabs WHERE id = ?", (tab_id,))
        self._emit(None)

    def reorder_tabs(self, ids: list[int]) -> None:
        for pos, tab_id in enumerate(ids):
            self.db.execute("UPDATE tabs SET position = ? WHERE id = ?", (pos, tab_id))
        self._emit(None, quiet=True)

    def set_tab_popped(self, tab_id: int, popped: bool) -> None:
        self.db.execute("UPDATE tabs SET popped = ? WHERE id = ?", (int(popped), tab_id))
        self._emit(None, quiet=True, dirty=False)

    def set_tab_geometry(self, tab_id: int, geometry: str) -> None:
        self.db.execute("UPDATE tabs SET geometry = ? WHERE id = ?", (geometry, tab_id))
        self._emit(None, quiet=True, dirty=False)

    # ---- items -------------------------------------------------------------
    @staticmethod
    def _item(r: sqlite3.Row) -> Item:
        return Item(r["id"], r["tab_id"], r["name"], r["due"], r["end_date"], r["priority"],
                    r["notes"], bool(r["reminder"]), bool(r["reminded"]), bool(r["done"]), r["created"],
                    r["remind_time"], r["position"])

    def items(self, tab_id: int) -> list[Item]:
        rows = self.db.execute("SELECT * FROM items WHERE tab_id = ? ORDER BY position, id", (tab_id,))
        return [self._item(r) for r in rows]

    def all_items(self) -> list[Item]:
        return [self._item(r) for r in self.db.execute("SELECT * FROM items ORDER BY id")]

    def item(self, item_id: int) -> Item | None:
        r = self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._item(r) if r else None

    def add_item(self, tab_id: int, name: str, due: str = "", end: str = "", priority: int = 1,
                 notes: str = "", reminder: bool = False, done: bool = False,
                 remind_time: str = "") -> Item:
        item_id = self._insert_item(tab_id, dict(name=name, due=due, end=end, priority=priority, notes=notes,
                                                 reminder=reminder, done=done, remind_time=remind_time))
        self._emit(tab_id)
        return self.item(item_id)

    def _insert_item(self, tab_id: int, it: dict) -> int:
        due, end = it.get("due", "") or "", it.get("end", "") or ""
        if end and (not due or end <= due):
            end = ""
        pos = self.db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM items WHERE tab_id = ?",
                              (tab_id,)).fetchone()[0]
        cur = self.db.execute(
            "INSERT INTO items (tab_id, name, due, end_date, priority, notes, reminder, remind_time, done, created,"
            " position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tab_id, it.get("name", ""), due, end, int(it.get("priority", 1)), it.get("notes", "") or "",
             int(bool(it.get("reminder"))), it.get("remind_time", "") or "", int(bool(it.get("done"))),
             dt.datetime.now().isoformat(timespec="seconds"), pos))
        return cur.lastrowid

    def move_item(self, item_id: int, before_id: int | None) -> None:
        """Manual order: put item_id just before before_id (None = at the end)."""
        current = self.item(item_id)
        if current is None or item_id == before_id:
            return
        ids = [i.id for i in self.items(current.tab_id) if i.id != item_id]
        index = ids.index(before_id) if before_id in ids else len(ids)
        ids.insert(index, item_id)
        for pos, iid in enumerate(ids, start=1):
            self.db.execute("UPDATE items SET position = ? WHERE id = ?", (pos, iid))
        self._emit(current.tab_id)

    def reset_checklist(self, tab_id: int) -> int:
        cur = self.db.execute("UPDATE items SET done = 0 WHERE tab_id = ? AND done = 1", (tab_id,))
        self._emit(tab_id)
        return cur.rowcount

    def update_item(self, item_id: int, quiet: bool = False, **fields: Any) -> Item | None:
        unknown = set(fields) - ITEM_FIELDS
        if unknown:
            raise ValueError(f"unknown item fields: {unknown}")
        current = self.item(item_id)
        if current is None:
            return None
        if ({"due", "end", "reminder", "remind_time"} & set(fields)) and "reminded" not in fields:
            fields["reminded"] = False
        due = fields.get("due", current.due)
        end = fields.get("end", current.end)
        if end and (not due or end <= due):
            fields["end"] = ""
        cols, vals = [], []
        for key, value in fields.items():
            cols.append(f"{'end_date' if key == 'end' else key} = ?")
            vals.append(int(value) if isinstance(value, bool) else value)
        vals.append(item_id)
        self.db.execute(f"UPDATE items SET {', '.join(cols)} WHERE id = ?", vals)
        self._emit(current.tab_id, quiet=quiet)
        return self.item(item_id)

    def delete_item(self, item_id: int) -> None:
        current = self.item(item_id)
        if current is None:
            return
        self.db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self._emit(current.tab_id)

    # ---- settings ----------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        r = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if r is None:
            return default
        try:
            return json.loads(r["value"])
        except json.JSONDecodeError:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, json.dumps(value)))
        self.db.commit()

    # ---- whole-store operations (backup / restore) ---------------------------
    def snapshot(self) -> list[tuple[Tab, list[Item]]]:
        return [(t, self.items(t.id)) for t in self.tabs()]

    def replace_all(self, data: list[dict]) -> None:
        """data: [{"name": str, "items": [{name, due, end, priority, notes, reminder, remind_time, done}]}]"""
        self.db.execute("DELETE FROM items")
        self.db.execute("DELETE FROM tabs")
        for tab in data:
            tab_id = self._insert_tab(tab.get("name") or "List", tab.get("kind", "list"), tab.get("color", ""))
            for it in tab.get("items", []):
                self._insert_item(tab_id, it)
        self._emit(None)

    def add_lists(self, data: list[dict]) -> list[Tab]:
        """Add imported lists as new tabs after the existing ones."""
        made = []
        for tab in data:
            tab_id = self._insert_tab(tab.get("name") or "Imported", tab.get("kind", "list"), tab.get("color", ""))
            for it in tab.get("items", []):
                self._insert_item(tab_id, it)
            made.append(tab_id)
        self._emit(None)
        return [self.tab(t) for t in made]
