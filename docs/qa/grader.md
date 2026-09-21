# QA: `drill.grader.grade()`

Scope: `drill/grader.py` + `drill/normalize.py`, tested against the real decks in
`data/*.jsonl` (507 cards total: cloze_grammar 75, grammar_repair 80,
numbers_listening 85, peninsular_contrast 120, travel_production 100, scenarios
8×5 turns). All findings below are reproduced with a one-line
`python3 -c "..."` calling `drill.grader.grade()` directly — no DB, no CLI
touched. `~/.langapp/drill.db` was never opened.

## Measured rates

- **Sweep of every card's own accept/reject forms** (507 cards, all `accept`
  entries graded against their own card, all `reject` entries checked for
  `L1_banned`): **0 failures**. Every card accepts its own answers and rejects
  its own banned forms. Script: see Appendix A.
- **False-reject rate** (86 plausible-competent-speaker variants — pro-drop
  add, politeness lead/trail, article swap, accents stripped, ALL CAPS,
  inverted `¿?`, tú/usted swap — generated over 15 real cards spanning all 5
  decks): **0.0% (0/86)**. Well inside the 10% budget. The existing
  `tests/test_grader.py` / `tests/test_grader_adversarial.py` false-reject
  budgets (29 + 24 cases, both 0 failures on this run) corroborate this — the
  false-reject direction is solid.
- **False-accept rate, targeted minimal-pair probes**: **33 confirmed false
  accepts across 76 probes (43%)**, concentrated entirely in specific,
  identifiable code paths (below) — not spread evenly. The generic probes the
  task calls out by name (`tengo sed`/`tengo hambre`, dropped `no`, near-miss
  numbers, `ñ`-folding) are all **safe (0/34)**. The danger is narrower and
  worse than "noisy": it is a **systematic hole in three code paths** that
  happens to line up with exactly the grammar this app is built to teach
  (subjunctive, ser/estar, por/para, person, tilde-diacrítica homographs).

## Root causes (three, all in `drill/grader.py`)

1. **`_close_enough`'s single-token branch has no minimum-length /
   semantic gate.** The multi-token branch (`grader.py:158-165`) requires
   `min(len(a_tok), len(b_tok)) >= _SUB_MIN_LEN` (4 chars) before allowing an
   edit-distance-≤2 substitution — this is exactly what stops `hambre`/`sed`.
   The single-token branch (`grader.py:270-277`) has **no such gate**:
   `edit_distance(canon_attempt, canon_str_a) <= 2` fires on its own. Every
   card in `cloze_grammar` whose accept form is a single word (62 of 75
   cards — subjunctive/indicative verb forms, ser/estar forms, person forms,
   prepositions) and which has an **empty `reject` list** (all 75 do) is
   exposed. `por`↔`para`, `de`↔`en`, `es`↔`está`, `sabe`↔`sepa`-family swaps,
   and wrong-person conjugations land inside edit distance 2 routinely.
2. **The multi-token branch's char-distance gate treats real word pairs as
   typos.** `_SUB_MAX_CHAR_DIST=2, _SUB_MIN_LEN=4` was tuned to forgive
   `cansado`/`cansaddo` (typo), but it also forgives `hermano`/`hermana`,
   `médico`/`médica` — masculine/feminine noun pairs that are a **different
   person**, not an inflection of the same fact. `mi hermana` (my sister) is
   accepted for `mi hermano` (my brother).
3. **L3 accent-folding does not know about tilde-diacrítica homographs.**
   Spanish has a closed set of monosyllables distinguished *only* by a
   written accent that mark two different words, not one word with an accent
   slip: `el/él, tu/tú, mi/mí, te/té, se/sé, si/sí, de/dé, mas/más, aun/aún`.
   `fold_accents` correctly special-cases `ñ` for exactly this reason but
   applies no equivalent protection here, so L3 accepts all of them
   interchangeably. `se` (reflexive pronoun) vs `sé` ("I know") is a real
   card (`cz-053`) and is silently mis-graded via `L3_accent`.

A secondary, non-grading defect: the `L1_banned` reason string is hardcoded
to a register-mismatch framing ("En España no se dice «X»... es de
Latinoamérica") but is also the layer `grammar_repair`'s reject lists use for
ser/estar and tense traps (all **80/80** cards in that deck). The verdict
(reject) is correct; the *explanation* is a false claim about Spanish
dialects on every one of those 80 cards.

## Defect table

| # | Case | Input | Expected | Actual | Severity |
|---|---|---|---|---|---|
| 1 | Subjunctive→indicative, `cz-008` | `grade("es", accept=["sea"])` | Reject — "although it IS difficult" ≠ "although it MAY BE difficult" | **Accepted**, `L4_close` | **P0** |
| 2 | por/para swap, `cz-056` | `grade("por", accept=["para"])` | Reject — "the gift is because of you" ≠ "the gift is for you" | **Accepted**, `L4_close` | **P0** |
| 3 | por/para swap, `cz-059` | `grade("por", accept=["para"])` (studying *in order to* vs *because of*) | Reject | **Accepted**, `L4_close` | **P0** |
| 4 | ser/estar single word, `cz-040` | `grade("es", accept=["está"])` — "how's your mother" (health, needs *estar*) | Reject | **Accepted**, `L4_close` | **P0** |
| 5 | Wrong person, `cz-047` | `grade("pone", accept=["pongo"])` — "he sets" vs "I set" | Reject | **Accepted**, `L4_close` | **P0** |
| 6 | Wrong person, `cz-051` | `grade("conoce", accept=["conozco"])` | Reject | **Accepted**, `L4_close` | **P0** |
| 7 | Tilde-diacrítica homograph, real card `cz-053` | `grade("se", accept=["sé"])` — reflexive pronoun for "I know" | Reject — different word | **Accepted**, `L3_accent` | **P0** |
| 8 | Gender-referent flip (multi-token) | `grade("mi hermana", accept=["mi hermano"])` | Reject — sister ≠ brother | **Accepted**, `L4_close`, "muy cerca de «mi hermano»" | **P0** |
| 9 | Preposition swap, `cz-066` | `grade("en", accept=["de"])` | Reject | **Accepted**, `L4_close` | **P0** |
| 10 | Preposition swap, `cz-070` | `grade("de", accept=["en"])` | Reject | **Accepted**, `L4_close` | **P0** |
| 11 | Wrong messaging on 80/80 `grammar_repair` cards | `grade("está aburrido", accept=["es aburrido"], reject=["está aburrido"])` | Correctly reject, with a reason describing the ser/estar trap | Correctly rejects, but reason says *"En España no se dice «está aburrido» — es de Latinoamérica"* — false; `está aburrido` is fine Spanish, just wrong for this prompt | **P1** (content correctness, not a grading error) |
| 12 | Trailing emoji | `grade("quiero un café con leche ☕", accept=["quiero un café con leche"])` | Accept — decoration doesn't change content | Rejected, `L5_reject` | **P3** |

Full false-accept probe list (33 confirmed, superset of the table above,
covering all of `cz-004, cz-008, cz-013, cz-015, cz-018` [subjunctive],
`cz-034, cz-036, cz-040` [ser/estar], `cz-045, cz-047, cz-049, cz-051,
cz-055` [person], `cz-056–cz-061, cz-066, cz-070` [prepositions], the 9
tilde-diacrítica pairs `el/él tu/tú mi/mí te/té se/sé si/sí de/dé mas/más
aun/aún`, and `mi hermana/mi hermano`, `el médico/la médica`) is reproducible
with Appendix B.

## Confirmed-safe (for the record)

- `tengo sed` vs `tengo hambre`, `soy aburrido` vs `estoy aburrido` — rejected
  (existing `_SUB_MIN_LEN`/`_SUB_MAX_CHAR_DIST` gate on the *multi-token*
  path works as designed here).
- Dropped `no` (negation) — 21/21 real accept forms containing `no` correctly
  rejected when `no` is stripped.
- Near-miss numbers/times (`cincuenta`/`sesenta`, `treinta`/`cuarenta`, `son
  las tres`/`son las dos`, added/removed `y cuarto`/`y media`) — 8/8 rejected.
- `ñ` folding — `año/ano`, `niño/nino`, `señor/senor` all correctly blocked
  with the specific ñ-guidance message (`L5_reject`, "Cuidado con la ñ").
- Register enforcement — every one of the 139 `reject` entries across
  `peninsular_contrast` is caught as `L1_banned`, and the `detail` string
  names the correct Peninsular alternative in all 139 cases.
- Unicode/whitespace robustness — NFD-composed accents, non-breaking spaces,
  curly apostrophes, trailing whitespace, ALL CAPS, and a 5000-character
  input all normalize/grade without error or false reject (the 5000-char
  case is correctly *rejected* as garbage, not crashed on).
- `carro` does not false-positive inside `carrocería` (existing test,
  reconfirmed).

## Minimal pytest bodies (drop into `tests/test_grader_adversarial.py`)

```python
def test_l4_single_token_rejects_subjunctive_for_indicative() -> None:
    """'es' (indicative) must not satisfy 'sea' (subjunctive) — cz-008."""
    v = grade("es", accept=["sea"])
    assert not v.accepted, f"'es' wrongly accepted for 'sea' via {v.layer}"


def test_l4_single_token_rejects_por_para_swap() -> None:
    """por/para are not interchangeable — cz-056."""
    v = grade("por", accept=["para"])
    assert not v.accepted, f"'por' wrongly accepted for 'para' via {v.layer}"


def test_l4_single_token_rejects_ser_estar_swap() -> None:
    """'es' must not satisfy 'está' — cz-040 (cómo está tu madre)."""
    v = grade("es", accept=["está"])
    assert not v.accepted, f"'es' wrongly accepted for 'está' via {v.layer}"


def test_l4_single_token_rejects_wrong_person() -> None:
    """'pone' (he sets) must not satisfy 'pongo' (I set) — cz-047."""
    v = grade("pone", accept=["pongo"])
    assert not v.accepted, f"'pone' wrongly accepted for 'pongo' via {v.layer}"


def test_l3_accent_does_not_conflate_tilde_diacritica_homographs() -> None:
    """'se' (reflexive pronoun) and 'sé' (verb) are different words — cz-053.

    Accent-fold tolerance is for slips on the SAME word, not for Spanish's
    closed set of tilde-diacrítica pairs (el/él, tu/tú, mi/mí, te/té, se/sé,
    si/sí, de/dé, mas/más, aun/aún) which are different lexical items.
    """
    v = grade("se", accept=["sé"])
    assert not v.accepted, f"'se' wrongly accepted for 'sé' via {v.layer}"


def test_l4_multitoken_rejects_gender_referent_flip() -> None:
    """'mi hermana' (sister) must not satisfy 'mi hermano' (brother)."""
    v = grade("mi hermana", accept=["mi hermano"])
    assert not v.accepted, f"'mi hermana' wrongly accepted for 'mi hermano' via {v.layer}"


def test_l1_banned_message_is_not_regional_framing_for_grammar_traps() -> None:
    """grammar_repair's reject lists are ser/estar & tense traps, not LatAm
    vocabulary — the L1 reason must not claim 'en España no se dice X'."""
    v = grade("está aburrido", accept=["es aburrido"], reject=["está aburrido"])
    assert not v.accepted
    assert "no se dice" not in v.reason, (
        "L1 reason falsely frames a ser/estar grammar trap as a Spain-vs-"
        f"LatAm register issue: {v.reason!r}"
    )
```

## Appendix A — sweep script (own accept/reject forms, all 507 cards)

```
python3 -c "
import json, sys
sys.path.insert(0, '.')
from drill.grader import grade
decks = ['cloze_grammar','grammar_repair','numbers_listening','peninsular_contrast','travel_production']
fails = 0
for d in decks:
    for line in open(f'data/{d}.jsonl'):
        o = json.loads(line)
        acc, rej = o.get('accept', []), o.get('reject', [])
        for a in acc:
            if not grade(a, accept=acc, reject=rej).accepted: fails += 1
        for r in rej:
            if grade(r, accept=acc, reject=rej).layer != 'L1_banned': fails += 1
print('failures:', fails)
"
```

## Appendix B — false-accept probe (one-liners)

```
python3 -c "import sys; sys.path.insert(0,'.'); from drill.grader import grade; print(grade('por', accept=['para']))"
python3 -c "import sys; sys.path.insert(0,'.'); from drill.grader import grade; print(grade('es', accept=['sea']))"
python3 -c "import sys; sys.path.insert(0,'.'); from drill.grader import grade; print(grade('se', accept=['sé']))"
python3 -c "import sys; sys.path.insert(0,'.'); from drill.grader import grade; print(grade('mi hermana', accept=['mi hermano']))"
python3 -c "import sys; sys.path.insert(0,'.'); from drill.grader import grade; print(grade('pone', accept=['pongo']))"
```
