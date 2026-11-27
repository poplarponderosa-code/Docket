"""The in-app tour and one-time tips: what each step says and which part of the window it points at.

Steps belong to a mode feature (see modes.FEATURES); "basic" steps are for everyone. A tour for a
mode shows the steps that mode has. Switching to a higher mode offers a short tour of just the
steps it adds. The widgets that show them are in ui/tour.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import modes


@dataclass(frozen=True)
class Step:
    key: str
    feature: str          # "basic", or a modes.FEATURES key
    target: str           # which widget it points at (resolved in ui/tour.py); "" = the middle of the window
    title: str
    text: str


STEPS = [
    Step("tabs", "basic", "tabs", "Your lists",
         "Each list is a tab. Right-click a tab to rename it, change its colour, switch between a checklist "
         "and a priority list, copy it, or open it in its own window."),
    Step("new_list", "basic", "add_tab", "New lists",
         "+ makes a new list. The arrow next to it has more choices, like importing a list from a file."),
    Step("add", "basic", "input", "Adding items",
         "Type an item and press Enter. A date, time or priority at the end is picked up, like "
         "“dentist fri 3pm !high”. Paste several lines to add them all."),
    Step("items", "basic", "list", "Your items",
         "Tick an item when it's done. Click its arrow for notes, dates, a reminder and a link; Enter or "
         "Esc closes it again. In a checklist, drag steps to change the order."),
    Step("pill", "basic", "collapse", "Pills",
         "This shrinks the window to a pill that keeps the top item in view; the same button brings the "
         "window back. A list in its own window can be a pill too."),
    Step("capture", "quick_capture", "", "Quick capture",
         "Press {capture_key} anywhere in Windows to add an item without opening Docket. Tab picks the "
         "list and Shift+Enter keeps the box open for another. You can change the key in Settings > "
         "Shortcuts."),
    Step("shortcuts", "shortcuts", "settings", "Shortcuts",
         "{show_key} shows or hides Docket and {tick_key} ticks off the top item. Change the keys in "
         "Settings > Shortcuts; they work from a Stream Deck too."),
    Step("templates", "templates", "add_tab", "Templates",
         "Save a checklist as a template from its tab's right-click menu. Start a new one from the arrow "
         "next to +, then New from template."),
    Step("timer", "timer", "tabs", "Checklist timer",
         "Right-click a checklist's tab and choose Use a timer. Time runs on the top unticked step and "
         "ticking it starts the next. Click a step's time to give it a limit."),
    Step("categories", "categories", "tabs", "Categories and clients",
         "A checklist's right-click menu also has Categories… and a Client label. The client label is "
         "mainly for Ledger, so it knows who to bill. Keep it short, like “Acme”."),
    Step("timelogs", "timelogs", "logo", "Time logs",
         "Ticking a timed checklist's last step saves a time log. Open the folder from this menu. Ledger "
         "turns time logs into invoices."),
    Step("settings", "basic", "settings", "Settings",
         "Modes, themes, backups and more. Settings > AI has instructions that teach an AI to write lists "
         "you can paste into Docket. An AI can't see your lists unless you give it access to Docket's files."),
]

WELCOME = Step("welcome", "basic", "", "Welcome to Docket",
               "A quick tour, about a minute. Docket lives in the tray by the clock: closing this window "
               "keeps it running. Press Esc to stop the tour any time.")
DONE = Step("done", "basic", "", "That's the tour",
            "Tips pop up the first time you use some features. Turn them off, or take this tour again, in "
            "Settings > General.")

# One-time tips, shown the first time a feature is used (if tips are on).
TIPS = {
    "panel": ("Item details", "Enter saves the name and closes the item. Esc closes it and undoes the "
                              "name you were typing. Notes save as you type."),
    "pill": ("Pill", "Drag the bottom edge to show 1, 2 or 3 items. Hold Ctrl while dragging to move "
                     "every pill snapped to this one. Double-click the side edge to fit the item's width."),
    "timer": ("Timer on", "Time runs on the top unticked step; ticking it starts the next. Click a step's "
                          "time to set a limit, or the total in the header for the whole checklist."),
}


def _fmt(step: Step, keys: dict) -> Step:
    values = {"capture_key": keys.get("capture_key") or "your quick capture key",
              "show_key": keys.get("show_key") or "The show key",
              "tick_key": keys.get("tick_key") or "the tick key"}
    try:
        text = step.text.format(**values)
    except (KeyError, IndexError):
        text = step.text
    return Step(step.key, step.feature, step.target, step.title, text)


def steps_for(mode: str, keys: dict | None = None) -> list[Step]:
    """The full tour for a mode: welcome, every step the mode has, then the closing step."""
    keys = keys or {}
    body = [s for s in STEPS if s.feature == "basic" or modes.has(mode, s.feature)]
    return [_fmt(s, keys) for s in [WELCOME, *body, DONE]]


def steps_new_in(old_mode: str, new_mode: str, keys: dict | None = None) -> list[Step]:
    """Just the steps a higher mode adds (empty when the new mode is the same or lower)."""
    keys = keys or {}
    if modes.rank(new_mode) <= modes.rank(old_mode):
        return []
    new = [s for s in STEPS if s.feature != "basic"
           and modes.has(new_mode, s.feature) and not modes.has(old_mode, s.feature)]
    if not new:
        return []
    label = modes.LABELS.get(new_mode, new_mode)
    intro = Step("intro", "basic", "", f"What {label} adds",
                 f"A short tour of the {len(new)} things {label} mode adds. Press Esc to stop any time.")
    return [_fmt(s, keys) for s in [intro, *new]]


def should_offer_tour(settings: dict) -> bool:
    """Existing users who haven't seen or dismissed the tour get one invitation."""
    return bool(settings.get("setup_done")) and not settings.get("tour_done")


def tip_due(settings: dict, key: str) -> bool:
    return bool(settings.get("tips_on", True)) and key in TIPS and key not in (settings.get("tips_seen") or [])
