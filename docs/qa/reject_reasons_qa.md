# QA: truthful reject reasons (`why:` tags)

Scope: verify `grade()`'s per-category reject message, the `why:` tag never
reaching the learner, backward compatibility, the region path being a
no-op, no grader regression, the full test suite, and the live DB.
Methodology: real pipeline execution (`store.import_jsonl` into temp DBs,
`store.get_card`, `grade(...)`), not code reading. Scripts under
`/private/tmp/claude-501/-Users-mattwang-dev-language-app/26b05c64-58c9-47f9-90f3-3651fc59f211/scratchpad/qa/`.

## Result: no P0 or P1 found. Ship it.

## 1. Truthfulness end to end

All 455 cards imported from `data/*.jsonl` (`scenarios.jsonl` is a
different schema, correctly skipped by import — 0 reject-bearing cards in
it anyway). 189 cards carry a non-empty `reject` list: `region`=69,
`meaning`=60, `form`=30, `register`=30 (0 untagged). For every one of
those 189 cards, every reject form (233 total when swept across the full
grader in §5) produces the category's exact template with the correct `X`
(the reject-list entry that actually matched, per the grader's own
first-match order) and `Y` (`accept[0]`). **0 mismatches.**

## 2. `why:` tag never reaches the learner — P0 check

Grepped/exercised every surface with real reviews recorded:
- CLI `review`/`daily` (`cli._run_review_loop`, shared by both): 189
  cards forced through their reject form, 61KB of output, 0 `why:`
  occurrences.
- `listen` (fresh DB, `peninsular_contrast`, speech mocked): 0
  occurrences.
- `sprint` (post-review "already seen" cards): 0 occurrences.
- `stats`, `weak` (tag-ranking table populated from real review history):
  0 occurrences — `store.tag_performance` already filters `why:` tags
  before ranking.
- `export` markdown (`docs/MIS_FALLOS.md`-shaped output, 37.7KB,
  weak-tags + failing-cards + trampas sections all populated): 0
  occurrences.
- Tkinter GUI, driven headlessly (`tk.Tk()` + `withdraw()`, no display
  needed): all 115 `peninsular_contrast` cards shown via `_show_card`
  (`lbl_tag` reads `card.display_tags`) and answered with their reject
  form via `_submit` (`lbl_verdict`, `lbl_note`, `lbl_target`), plus
  `_refresh_progress`'s weak-tag rows. 0 occurrences across all widget
  texts.

## 3. Region path is a no-op

Loaded the pre-change grader via `git show 39a5306:drill/grader.py`.
For all 69 `why:region` cards / 101 reject forms, `reason` and `detail`
are byte-identical between old and new grader. As a sanity check that
this isn't vacuous, the same comparison on the 132 non-region reject
forms diverges from the old (always-region) message in all 132 cases —
confirming the category logic is actually engaged.

## 4. Backward compatibility

`grade()` without `reject_reason` defaults to `"unspecified"` and uses
the default template. Garbage values (`"why:banana"`, `"banana"`, `""`,
`"why:"`, case variants, trailing whitespace) all degrade to
`DEFAULT_REJECT_REASON` and never raise. `reject_reason_from_tags`
likewise degrades on unknown/malformed/duplicate `why:` tags.
`drill/cli.py`'s `cmd_scene` (via `scenario.py`) still calls
`grade_attempt` with no `reject_reason` kwarg and works.

## 5. No grader regression — quantified

Full sweep, all 455 imported cards:
- **Accept forms:** 634/634 pass (**100.00%**, 0 false rejects).
- **Reject forms:** 233/233 caught at `L1_banned` (**100.00%**).
- Accent tolerance on full sentences: confirmed (`cuantos años tienes` →
  `L3_accent` accepted; `que hora es` → `L3_accent` accepted).
- Genuine typo forgiveness: `hoi`→`hoy` and `em`→`en` both `L4_close`
  accepted.
- Real-word confusions rejected: `por`/`para` and `papa`/`para` (explicit
  reject lists) → `L1_banned`; `soy aburrido`/`estoy aburrido` → `L5_reject`
  (not accepted).
- ñ-vs-n guard intact: `ano`→`año` still rejected (`L5_reject`, "Cuidado
  con la ñ").

## 6. Full suite

`python3 -m pytest tests/ -q` → **337 passed**, 0 failures.

## 7. Live DB (read-only)

`~/.langapp/drill.db` mtime **Sep 20 22:18:16 2026**, md5
`8ba7a3dd955cbacd2f5c0d42f977f6aa` — identical before and after this QA
run (checked via a copy, never opened the original for writes). The copy
holds all 455 cards / 189 reject-bearing, same tag distribution
(region=69, meaning=60, form=30, register=30), 0 message mismatches.

## Findings

None ranked P0/P1/P2 — no defects found in this sprint item.
