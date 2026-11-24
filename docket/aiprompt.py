"""The AI instructions: a message the user copies into their AI's custom instructions, so it writes
lists in Docket's import format when they say the trigger phrase ("put it on the Docket").

VERSION goes up whenever the text changes in a way that matters; Settings then says
"Updated instructions available" to anyone who copied an older version.
"""
from __future__ import annotations

VERSION = 1
PHRASES = ["put it on the Docket", "send to Docket", "add to Docket"]
DEFAULT_PHRASE = PHRASES[0]

TEXT = """\
Docket instructions (v{version})

I use Docket, a Windows list app. When I say "{phrase}", turn the action items, steps or list we've been discussing into Docket's import format. Put it in a single code block so I can copy it into Docket's quick capture, with nothing else inside the block.

FORMAT
- Start each list with: ## List name
- Options go in square brackets after the name, separated by commas:
    checklist     for ordered steps (no due dates). Leave it out for a normal to-do list.
    a colour      blue, teal, sage, olive, amber, peach, rose, plum, lavender or slate
    timer         turns on the checklist timer; "limit 3h" sets a total time (checklists only)
    client: Name  only if I typed the client label myself in this chat
  Example: ## Map making [checklist, teal, timer]
- An optional description goes on lines starting with "> " right under the name line.
- One item per line: the name first, then any useful fields after " | ", in any order:
    a date           2026-12-03, or a range like Nov 24-28
    a priority       High, Med or Low
    a reminder       remind 3:00 PM
    notes            notes: any text
    a link           link https://example.com (or a folder or file path)
    checklist steps  limit 45m, category Name
- Extra note lines go under an item, indented 4 spaces.
- For checklist categories, add "@categories: Name; Name" under the name line, then "category Name" on each step.

RULES
- Write exact dates (YYYY-MM-DD) worked out from today's date. Never words like "tomorrow" or "Friday", since I may paste the list later.
- Only add fields that help. A plain item name is fine.
- Use categories only if I've told you my category names, and spell them exactly as I did.
- Never add a client label unless I typed it myself, and keep client and personal details out of list names and items.
- No bullets, numbering or # comment lines.
- Several lists can go in one block, each starting with its own ## line.
- If I just say "{phrase}", use the action items from our conversation.

EXAMPLE
## Website launch [teal]
Write the About page | 2026-12-03 | High
Send draft to Sam | 2026-12-05 | notes: Ask about the logo
Book a photographer | link https://example.com

## Launch day [checklist, timer]
@categories: Writing; Admin
Final proofread | limit 30m | category Writing
Publish and share | category Admin
"""


def clean_phrase(text: str) -> str:
    """A custom phrase: one line, no surrounding quotes, sensible length."""
    text = " ".join((text or "").split()).strip("\"'“”‘’ ")
    return text[:60]


def phrase_from(settings: dict) -> str:
    choice = settings.get("ai_phrase", DEFAULT_PHRASE) or DEFAULT_PHRASE
    if choice == "custom":
        return clean_phrase(settings.get("ai_phrase_custom", "")) or DEFAULT_PHRASE
    return choice


def instructions(phrase: str = DEFAULT_PHRASE) -> str:
    return TEXT.format(version=VERSION, phrase=clean_phrase(phrase) or DEFAULT_PHRASE)


def update_available(copied_version: int) -> bool:
    """True when the user copied an older version of the instructions."""
    return 0 < int(copied_version or 0) < VERSION
