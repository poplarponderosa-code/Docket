# Docket

A small, quiet to-do window for Windows 11: lists as tabs, each either a priority list
(due date, item, priority, notes) or a checklist (steps in order), soft colour themes,
reminders, and plain-text backups you can keep in OneDrive or Google Drive.

## Get it running

You need Python 3.10 or newer from python.org. Tick "Add python.exe to PATH" when you install it.

**Try it from the source files:** double-click `run_from_source.bat`.
The first run installs PySide6 (about 60 MB), then Docket opens.

**Make a normal app (Docket.exe):** double-click `build.bat`. When it finishes, the app
is in `dist\Docket\`. Move that whole folder wherever you like (e.g. `Documents\Docket`)
and run `Docket.exe` from there. Once it's running, Docket adds itself to Windows startup
(turn that off in Settings). If you move the folder later, run Docket.exe once from the
new place so startup points to the right spot.

Your lists live in `%APPDATA%\Docket\docket.db`, separate from the app, so rebuilding or
moving the app never touches them.

## Keyboard shortcuts and Stream Deck

Three shortcuts work from any program, set in Settings > Keyboard shortcuts:

| Action | Default |
|---|---|
| Show or hide Docket | F13 |
| Tick the top item on the active list | F14 |
| Start or pause the timer | F15 |

F13–F15 aren't on most keyboards, so they can't clash with other programs' shortcuts, but a
Stream Deck can send them. To set up a Stream Deck: drag a **Hotkey** action (System) onto a key and
set its hotkey to the shortcut; repeat for the other two. If you'd rather use your keyboard, pick any
other combination in Settings; it tells you if another program already uses it. "Active list" means
the checklist whose timer is running, otherwise the list you used last.

## Updates

Docket checks GitHub once a day for a newer release (Settings > About & updates, where you can also
check now or turn it off). When there is one it shows what's new and offers **Update now**, **Later**
or **Skip this version**. Update now downloads the installer from the GitHub release, closes Docket,
installs quietly and reopens it, keeping your lists. Publishing a new release on GitHub, with the
setup `.exe` attached, is what makes an update appear.

## Making an installer to share Docket

To give Docket to someone who doesn't use Python or GitHub, make a normal Windows installer:

1. Quit Docket if it's running (tray icon > Quit Docket).
2. Double-click `build_installer.bat`. It builds `Docket.exe`, installs **Inno Setup** (a free
   installer maker) through winget the first time, then makes the installer. When it's done, the
   `installer_output` folder opens with **Docket-Setup-1.0.0.exe** in it.
3. Send that one file (through a OneDrive or Google Drive link if it's too big to email).

What the person you send it to gets:

* A setup wizard; it installs for them alone, with no admin password needed.
* Docket in the Start menu, and a desktop shortcut if they tick that box.
* "Launch Docket" at the end of setup; from then on it starts with Windows (they can turn that
  off in Settings).
* An uninstaller under Settings > Apps. Uninstalling keeps their lists in `%APPDATA%\Docket`,
  so reinstalling later brings them back.
* Windows may say "Windows protected your PC" when they open the installer, because it isn't
  signed with a paid publisher certificate: **More info > Run anyway**.

If Docket is running when they install or uninstall, setup asks to close it first.

**For a new version:** change `MyAppVersion` near the top of `installer.iss` (and `__version__`
in `docket\__init__.py`), then run `build_installer.bat` again. Attach the new setup file to a new
GitHub release (tag `v` plus the version, like `v1.2.0`) so the in-app updater finds it. Installing the new one over the
old one updates it and keeps their lists. Don't change the `AppId` line: it's how Windows
recognises an update.

To use your own name as the publisher shown in Settings > Apps, change `MyAppPublisher` in
`installer.iss`.

## Updating to a new version

There's nothing to uninstall. Docket has no installer; it's just a folder.

1. **Quit the running Docket first:** right-click the tray icon > Quit Docket. (If it's still
   running, opening the new one just brings the old window forward.)
2. Unzip the new version over the old folder, or into a new folder.
3. Run `run_from_source.bat` again, or `build.bat` again to rebuild `dist\Docket\Docket.exe`.
   If you had copied the old `Docket` folder somewhere else, replace it with the new one.

Your lists and settings carry over and are upgraded automatically. The Windows startup entry
updates itself the first time the new version runs.

## Adding items

Type in the box at the top and press Enter. A date or a priority at the end of the text is
picked up for you, and the grey line under the box shows what it understood before you add:

| You type | You get |
|---|---|
| `call mom tomorrow` | due tomorrow |
| `dentist fri !high` | due this Friday, High priority |
| `plan offsite nov 24-28 !low` | Nov 24–28 range, Low |
| `trip nov 30 - dec 2` | Nov 30–Dec 2 range |
| `renew passport next week !h` | Mon–Fri of next week, High |
| `pay invoice 12/15` | Dec 15 (month/day) |
| `send report in 3 days` | 3 days from today |
| `clean garage weekend` | this Sat–Sun |
| `dentist fri 3pm` | due Friday, reminder at 3:00 PM |
| `call bank at 10:30am` | due today, reminder at 10:30 AM |

* Priority: `!high` `!h` `!1`, `!med` `!m` `!2`, `!low` `!l` `!3`, anywhere in the text.
* Dates are only read at the **end** of what you type, so "Watch Friday Night Lights" stays a name.
  "on", "by", "due" and "from" before the date are dropped ("pay rent by dec 1").
* Ranges: join two dates with `-`, `to`, `until` or `through`.
* A time (`3pm`, `3:30 pm`, `at 9am`, `@14:00`) turns on that item's reminder at that time.
  With no date, it's due today. A colon time without am/pm is 24-hour, except 1:00–6:59,
  which is read as afternoon (`2:30` = 2:30 PM).
* Or skip typing dates: the **Date** button has One day / Date range, quick picks
  (Today, Tomorrow, Friday, In a week, Weekend, Next week) and two date boxes.
* Anything typed wins over the Date button and the priority box.

## Everyday use

* **Click a row** (or its chevron) to open notes, start/end dates, Remind (with its own time)
  and Delete. The reminder time starts at your default from Settings; change it per item.
* **Click a priority** to cycle High → Med → Low. **Tick the box** to mark done.
  Done items sink to the bottom; "Hide done" in the footer hides them.
* **Click a column header** to sort; click again to reverse. Due date is the default.
  Right-click the header to hide (or show) the Priority column. Column order and the Priority
  column are also in Settings.
* **Tabs:** `+` makes a new priority list; the small arrow beside it offers **New checklist**,
  **New from template** and **Import a list…**. Type the new list's name and press Enter (Esc keeps
  the default name). Double-click a tab to rename it, drag tabs to reorder.
  Right-click a tab for Rename, Colour, Show as a checklist / priority list, Export, Delete.
* **List colours:** every list has one of ten soft colours (Blue, Teal, Sage, Olive, Amber,
  Peach, Rose, Plum, Lavender, Slate), shown as a dot on its tab, its own window and its pill.
  New lists get the next unused colour; change it with right-click > Colour. Dark mode uses
  lighter versions of the same colours. Turn on **Fill whole tabs with their list's colour** in
  Settings to tint the whole tab instead, along with the list's own window title and its pill.
* Tabs show just the list's name; hover a tab to see how many items are open (or how many
  steps are done).
* **Separate windows, like Chrome:** drag a tab down (or up) out of the tab bar and it becomes
  its own small window that follows your mouse. Drag a list window by its title back onto the
  main window's tab bar (it highlights) and drop it to put it back as a tab, at the spot you drop it.
  The small arrow on a tab and the square button on a list window do the same with one click.
  Each window remembers where you put it.
* **Pills:** double-click any title bar (or press its chevron) to shrink the window to a slim
  pill in the list's colour. It shows a **tick box and the list's top item**; tick it and the
  next one slides in. Drag its edges to resize it; make it taller and the next items appear
  underneath, each with its own tick box. **Double-click the pill's left or right edge** to widen
  it to fit the whole item, and again to go back to your width. The pill's buttons (pin, open,
  close) only appear while the mouse is over it. A pill has its own pin, separate from the full
  window's. Double-click the title or click an item line to open the full window again.
* **Pill height:** drag a pill's bottom edge and it snaps to show 1, 2 or 3 items (3 at most). The
  default for new pills is in Settings.
* **Pills snap** to each other, the main window and the screen edges as you drag them, on any side.
  Turn snapping off in Settings.
* **Docket remembers your layout:** which lists are in their own windows, where they are, which
  windows are pills, and which tab was open all come back the next time it starts.
* **Resizing:** drag any edge or corner of a window. **Double-click the resize corner** (bottom
  right) to fit the window to every item in the list, full names included.
* **Docket lives in the system tray, with no taskbar button.** Close (×) and minimize (–) both hide it
  there; it keeps running for reminders and timers.
  Click the tray icon to bring it back, right-click it for Quick add, Back up now, Settings, Quit.
* **The D logo** (top left) opens Docket's menu: companion apps (**Open Ledger**, or **Get Ledger…** if
  it isn't installed), Open time logs folder, Settings, Check for updates and Quit.
* **Clear done** in the footer (or right-click a tab > Clear checked items…) deletes every ticked item
  in that list, after asking. Your backups still have them.
* The **pin** keeps windows on top; it fills in while it's on. The **moon/sun** flips dark mode.

## Checklists

For processes you repeat, like making a map. A checklist has steps instead of dates:

* No dates or priority, and no reminders. Steps stay in the order you put them:
  **drag a step** up or down to move it.
* Ticked steps stay where they are, crossed out, so you can see where you are. "Hide done" in the
  footer still hides them.
* Progress shows on the tab (`Map making 7/23`), in the footer and on the pill (`7 of 23`).
* **Reset** in the footer (or right-click the tab > Reset checklist…) unticks every step,
  after asking first.
* Any list can switch between a priority list and a checklist (right-click its tab). Dates and
  priorities are hidden in checklist view, never deleted, so switching back brings them back.

**Timer (optional):** right-click a checklist's tab > **Use a timer**. A Time column appears.

* Press **▶** in the header (or on the pill) to start. Time always runs on the top unticked step.
  Tick it and its time is saved and the next step starts at once. Ticking the last step stops the
  timer and saves a **time log**.
* Hover a step to see its own ▶: it moves the timer onto that step (or pauses it if it's running).
* **Time limits are optional.** Open a step and type a limit (`15m`, `1h30`, `1:30`, `90s`); click the
  total in the header for a limit on the whole checklist. With a limit the step counts down, and at
  zero you hear a soft sound and the pill or title bar gently flashes for a few seconds (click to
  stop it). It keeps counting as overtime (`+2:15`).
* Lock the PC or put it to sleep and the timer pauses; when you're back, Docket asks whether to
  resume. If Docket was closed with a timer running, it asks the same when it starts.
* Only one checklist's timer runs at a time.
* **Time logs** are a text file (and a CSV copy for Excel or Google Sheets) with the checklist's name,
  description, start and finish, and each step's start, end, duration and limit. They go to
  `Time logs` inside your backup folder (change it in Settings). Right-click the tab > **Export time
  log…** saves one at any point. **Reset** clears the times as well as the ticks, after asking.

**Categories (optional):** open a step and pick a **Category**, or choose **New category…** to make
one. Each checklist has its own categories (edit, rename or remove them with **Edit categories…**, or
right-click the tab > Categories…), and templates keep them. Right-click the column headings to show
or hide the **Category** column. Time logs list each step's category and add up time per category.

**Ledger:** Docket Ledger is the companion app that turns time logs into PDF timesheets. When a timed
checklist is finished, a small Ledger icon appears beside its timer (and on its pill) until you reset
it; click it, or right-click the tab > **Make a PDF in Ledger…**, to open that checklist's newest time
log in Ledger. If Ledger isn't installed, these open its download page. Ledger finds Docket's time
logs folder on its own.

**Description:** every list has an **ⓘ** at the right of its column headings. Click it to write a
description; it's kept with exports, templates, backups and time logs.

**Templates:** right-click a checklist's tab > **Save as template…** saves a clean copy (every
step unticked, notes kept) to your templates folder. Start a fresh one with the arrow beside
`+` > **New from template**. A template is a plain `.txt` file, so you can send it to someone;
they use **New from template > Load a template file…** (or Import a list). The templates folder
is `Templates` inside your backup folder unless you pick another in Settings.

## Settings (sliders icon)

* Themes: Light, Dark, Sage, Lavender, Sand
Everything fits the window now; nothing hides off to the side. The scroll wheel scrolls the
settings page and lists without changing dropdowns, dates, times or numbers you scroll over.

* Launch when Windows starts, start hidden in the tray, keep windows on top, keep pills on top
* Reminder notifications and the default time (9:00 AM). Each item can have its own time.
  A reminder appears on the item's start date, or straight away if the item is already late.
* Columns: drag them by the handle to reorder, untick Priority to hide it; sort order;
  show/hide done items
* Fill whole tabs with their list's colour
* Backup: on/off, folder (Change folder…), how often (after every change, hourly, daily), how many
  files to keep, Back up now, Restore from backup, Open folder
* Checklist templates: the templates folder, with Change folder… and Open folder
* Import & export: Import a list…, export any list (pick it from the dropdown), and Save example
  files…

## Importing lists you already have

Settings > **Import a list…** (also on the tab right-click menu and the tray menu). Each list in
the file becomes a new tab; nothing you already have is changed. Settings > **Save example
files…** saves examples of both formats (also in the `examples` folder of this download).

To move a single list to another PC, or keep a copy of it: pick it in Settings > Import & export
and press **Export…** (or right-click its tab > Export this list…). The file it saves can be
imported again anywhere.

A list's name line can say it's a checklist and give its colour: `## Map making [checklist, teal]`.

* **Text (.txt or .md):** one item per line, written like you'd type it in the add box
  (`plan offsite nov 24-28 !low`), or in columns separated by `|`
  (`Dentist | Dec 3 | Med | remind 3:00 PM | notes: bring forms`). `## Name` starts a list,
  indented lines become notes, `[x]` marks an item done, and `-` / `*` bullets or `1.` numbers
  are ignored. A list pasted from most note apps works as-is.
* **Spreadsheet (.csv):** a header row with any of List, Item, Due, End, Priority, Remind, Notes,
  Done. Only Item is required. In Excel use File > Save As > CSV; in Google Sheets,
  File > Download > CSV.

A Docket backup file can be imported too, if you want to copy lists from one PC to another
without replacing what's there.

## Backups

Backups are plain `.txt` files named like `Docket backup 2026-11-20 131500.txt`, one file
with every list:

```
## Work
- [ ] Submit quarterly report | due: 2026-11-20 | priority: High | remind 15:00
    Pull figures from the shared drive.
- [x] Plan offsite | due: 2026-11-24 to 2026-11-28 | priority: Low
```

Point the backup folder at a folder inside OneDrive or Google Drive and the files sync
like anything else. To move to a new PC: install Docket, open Settings > Restore from backup,
and pick the newest file. Restoring replaces your current lists, so Docket saves a backup of
them to `%APPDATA%\Docket\backups` first.

## For tinkering

```
docket/
  parser.py     typed dates and priorities (pure Python, unit tested)
  dates.py      date labels, ranges, quick picks
  store.py      SQLite storage
  backup.py     text backup write / read
  importer.py   list import (.txt / .md / .csv), export, checklist templates, examples
  timer.py      the checklist timer and time logs (plain Python, unit tested)
  geometry.py   pill snapping (unit tested)
  system.py     Windows shortcuts, lock/sleep notices, alert sound
  updates.py    GitHub update check and install
  companions.py companion apps (Ledger): finding and opening them, shared.json
  themes.py     palettes and the Qt stylesheet; add a theme by adding a palette
  app.py        tray, reminders, backups, startup, single instance
  ui/           windows, list page, date picker, settings
tests/          python -m pytest tests
```

## Licences

Docket's own code is under the licence in `LICENSE`. It's built with Qt for Python (PySide6, LGPLv3),
Python and PyInstaller; see `THIRD-PARTY-NOTICES.txt`, which the installer also includes.
