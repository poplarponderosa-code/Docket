"""Basic, Advanced and Pro: which features each mode shows. Switching only hides or shows; nothing is lost."""
from __future__ import annotations

MODES = ("basic", "advanced", "pro")
LABELS = {"basic": "Basic", "advanced": "Advanced", "pro": "Pro"}

# feature -> the lowest mode that has it
FEATURES = {
    "quick_capture": "advanced",
    "shortcuts": "advanced",
    "templates": "advanced",
    "tab_tint": "advanced",
    "timer": "pro",
    "categories": "pro",
    "timelogs": "pro",
    "client": "pro",
    "ledger": "pro",
}

SUMMARIES = {
    "basic": ("Just lists.",
              ["Lists and checklists", "Quick add with typed dates and priority", "Reminders",
               "Pills and pop-out windows", "List colours, themes and item links"]),
    "advanced": ("More control, for power users.",
                 ["Everything in Basic", "Quick capture from anywhere (F16)", "Keyboard shortcuts and Stream Deck",
                  "Checklist templates", "Whole-tab colour"]),
    "pro": ("Free, for time tracking at work.",
            ["Everything in Advanced", "Checklist timer and time limits", "Categories and client labels",
             "Time logs (.txt and .csv)", "Ledger links for timesheets and invoices"]),
}


def rank(mode: str) -> int:
    return MODES.index(mode) if mode in MODES else len(MODES) - 1


def has(mode: str, feature: str) -> bool:
    return rank(mode) >= rank(FEATURES.get(feature, "basic"))
