# RUNBOOK

Operational reference for `drill`. Departure 2026-10-03.

What the tool is and why it grades the way it does: `README.md`. The plan it sits inside,
including the daily-load trade-off: `docs/PROGRAM.md`. This page is only how to run it.

Every command is written `python3 -m drill ...`, which works from a clean checkout with
nothing installed.

## 1. Start here tonight

Zero prior state — 460 cards, none seen, no session ever run. From the repo root, in order:

```bash
python3 -m drill import data/*.jsonl
```
Loads every deck into `~/.langapp/drill.db`. Safe to re-run any time — it upserts by card
id, and it skips `data/scenarios.jsonl`, which is a different schema.

```bash
python3 -m drill stats
```
Confirms the import worked: 460 cards, all new.

```bash
python3 -m drill daily
```
The first real session. Paced: reviews first, then new cards, rate derived from days left
until 2026-10-03.

## 2. Every day

```bash
python3 -m drill daily
```
This is the one thing that still happens if the day collapses.

**Read this before the first session.** Starting from 460 unseen cards with 13 days left,
the derived rate is ~36 new cards a day against a 40-card session cap — **30+ minutes, not
15**, with almost no room left for reviews, so a backlog starts on day two. Two options:

- Full set: run it as-is, ~36 new/day plus backlog passes. About an hour a day.
- Reduced: `python3 -m drill daily --new 20`. ~20–25 minutes, reviews keep up, and roughly
  200 of the 460 cards are never introduced before the flight — thinned across every deck,
  grammar and cloze worst.

Pick one tonight and stay with it. The reasoning and the deck-order detail are in
[`docs/PROGRAM.md`](PROGRAM.md#a-note-on-the-daily-load).

Optional, same day: `python3 -m drill listen` (dictation), `python3 -m drill scene`
(scripted conversation), `python3 -m drill sprint` (timed recall on cards you already know).

## 3. Before each tutor session

```bash
python3 -m drill weak
```
Shows weakest tags and most-missed cards — bring this list. It's what to ask the tutor to
drill on out loud, since the tool only grades typed production, not speech. It needs ≥3
attempts per tag before it will rank, so expect "not enough history" for the first day or
two.

If you've been correcting mid-session (see below), also run `python3 -m drill stats` to
sanity-check nothing regressed.

Session dates and briefs: `docs/TUTOR.md`.

## 4. On the plane / offline

Everything works with no network — stdlib only, local SQLite DB, no account. `daily`,
`review`, `listen`, `scene`, `sprint`, `weak`, `stats`, `add` all run fully offline.
`listen` needs macOS `say`, which is also local.

Have on your phone: the exported markdown sheet.

```bash
python3 -m drill export
```
Writes `docs/MIS_FALLOS.md` — your most-missed cards, readable with no app. Regenerate
before you fly; put the file on your phone (Notes, Files, whatever syncs) since the phone
can't run the tool itself.

## 5. If something goes wrong

| Symptom | Fix |
|---|---|
| Database seems wrong / want to start over | DB lives at `~/.langapp/drill.db`. `rm ~/.langapp/drill.db` — this loses review history and scheduling, but **not cards**: cards live in `data/*.jsonl`. Re-run `python3 -m drill import data/*.jsonl` to rebuild from scratch. |
| A card rejects an answer you believe is correct | Edit the card in its `data/*.jsonl` file — add the form to `accept`, or remove it from `reject`. Then re-run `python3 -m drill import data/<file>.jsonl` to load the fix (safe, upserts by id). Consider `python3 -m pytest tests/test_content.py -q` to confirm the deck still validates. |
| The desktop app (`python3 -m drill gui` / double-clicking `bin/Drill.command`) won't open | Check tkinter is present: `python3 -c "import tkinter"`. If that errors, your Python build lacks Tk (common with some pyenv builds) — install a Python with Tk support, or use `python3 -m drill daily` from the terminal instead. |
| Audio silent in `python3 -m drill listen` | Check for a Peninsular voice: `say -v '?'` and look for Mónica, Eddy, Flo, Grandma, or Grandpa. If none are installed, add one in System Settings → Accessibility → Spoken Content → System Voice, or just keep using the drill without audio — it degrades to text-only silently either way. |
| Session is far longer than expected | Expected — see §2. `--new 20` shortens it; `--max 25` caps the whole session, backlog included. |

## 6. What is NOT in this tool

No speaking practice with feedback. No listening comprehension beyond dictation of
sentences you already have on file. No live conversation — `scene` is scripted, and the
other side says the same thing every time. This tool grades typed production and enforces
Peninsular register — that's it.

A human tutor covers speaking, listening to unfamiliar speech, and real conversation. This
tool is the retrieval practice that happens between tutor sessions, not a substitute for
them.
