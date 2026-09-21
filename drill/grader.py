"""Grades a typed Spanish attempt against accept/reject vocabulary lists.

Design stance (see repo docs): a deterministic grader that is too strict
teaches the user the tool is broken. Every ambiguous case is resolved
toward ACCEPT. The only hard rejection this grader cares about is
LatAm vocabulary where Peninsular Spanish is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from drill.normalize import edit_distance, fold_accents, token_edit_distance, tokens

__all__ = ["Verdict", "grade"]


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    layer: str  # "L0_empty"|"L1_banned"|"L2_exact"|"L3_accent"|"L4_close"|"L5_reject"
    reason: str
    matched: str | None
    detail: str | None


# --- tolerance vocabularies -------------------------------------------------

_POLITENESS_MULTI: tuple[tuple[str, ...], ...] = (("por", "favor"),)
_POLITENESS_SINGLE: frozenset[str] = frozenset(
    {"porfa", "gracias", "perdona", "perdon", "oye", "hola"}
)

_PRONOUNS_FOLDED: frozenset[str] = frozenset(
    {
        "yo",
        "tu",
        "usted",
        "ustedes",
        "el",
        "ella",
        "nosotros",
        "nosotras",
        "vosotros",
        "vosotras",
        "ellos",
        "ellas",
    }
)

_ARTICLES_FOLDED: frozenset[str] = frozenset({"el", "la", "los", "las", "un", "una"})


def _strip_leading_politeness(toks: list[str]) -> list[str]:
    for phrase in _POLITENESS_MULTI:
        n = len(phrase)
        if len(toks) > n and tuple(fold_accents(t) for t in toks[:n]) == phrase:
            return toks[n:]
    if len(toks) > 1 and fold_accents(toks[0]) in _POLITENESS_SINGLE:
        return toks[1:]
    return toks


def _strip_trailing_politeness(toks: list[str]) -> list[str]:
    for phrase in _POLITENESS_MULTI:
        n = len(phrase)
        if len(toks) > n and tuple(fold_accents(t) for t in toks[-n:]) == phrase:
            return toks[:-n]
    if len(toks) > 1 and fold_accents(toks[-1]) in _POLITENESS_SINGLE:
        return toks[:-1]
    return toks


def _strip_leading_pronoun(toks: list[str]) -> list[str]:
    if len(toks) <= 1:
        return toks
    head = fold_accents(toks[0])
    if head in _PRONOUNS_FOLDED:
        return toks[1:]
    # A mistyped pronoun is still a pronoun. Without this, "vosoyros tenéis"
    # keeps a token the accept form dropped, the lists come out different
    # lengths, and every vosotros card fails on a single slip -- in the one
    # deck where vosotros is the whole point.
    if len(head) >= _SUB_MIN_LEN and any(
        len(p) >= _SUB_MIN_LEN and edit_distance(head, p) <= 1
        for p in _PRONOUNS_FOLDED
    ):
        return toks[1:]
    return toks


def _strip_leading_article(toks: list[str]) -> list[str]:
    if len(toks) > 1 and fold_accents(toks[0]) in _ARTICLES_FOLDED:
        return toks[1:]
    return toks


def _canonicalize(toks: Sequence[str], *, politeness: bool = True) -> list[str]:
    """Strip politeness wrapping, optional leading subject pronoun, and a
    leading article — none of these should ever decide a verdict."""
    current = list(toks)
    changed = True
    while changed:
        changed = False
        strippers = [_strip_leading_pronoun, _strip_leading_article]
        if politeness:
            strippers[:0] = [_strip_leading_politeness, _strip_trailing_politeness]
        for strip_fn in strippers:
            updated = strip_fn(current)
            if updated != current:
                current = updated
                changed = True
    return current


def _is_subsequence(sub: list[str], full: list[str]) -> bool:
    it = iter(full)
    return all(tok in it for tok in sub)


def _blocked_by_ene_tilde_confusion(x: str, y: str) -> bool:
    """True iff x and y differ ONLY in ñ-vs-n (e.g. "año"/"ano").

    Generic edit-distance tolerance must never paper over this: ñ is never
    folded, and a word pair that is "close" purely because ñ got swapped for
    n has to be rejected, not fuzzy-accepted.
    """
    if x == y:
        return False
    if "ñ" not in x and "ñ" not in y:  # neither contains ñ
        return False
    return x.replace("ñ", "n") == y.replace("ñ", "n")


# Tokens whose presence or absence should never decide a verdict: Spanish
# drops and re-adds these freely, and a learner who produced everything else
# correctly has demonstrated what the card is testing.
_OPTIONAL_TOKENS = frozenset(
    {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "lo",
        "de", "del", "a", "al", "en", "con", "por", "para", "que",
        "y", "o", "mi", "tu", "su", "me", "te", "se", "nos", "os", "le", "les",
    }
)

# A substituted token may differ by at most this many characters, and both
# forms must be at least this long. Together these let "cansado"/"cansaddo"
# (a typo) through while stopping "hambre"/"sed" and "soy"/"estoy".
_SUB_MAX_CHAR_DIST = 2
_SUB_MIN_LEN = 4

# Every real Spanish word of one to three letters that a learner might
# plausibly type here, accent-folded. Length alone cannot tell a typo from a
# word swap -- "hoi" for "hoy" is a slip, "soy" for "estoy" is a different
# verb -- but vocabulary can: if what was typed is not a word at all, it is a
# typo. Short words carry most of Spanish's grammar (prepositions, articles,
# clitics), which is exactly where a blunt length gate did the most damage.
_SHORT_REAL_WORDS: frozenset[str] = frozenset(
    """
    a e o u y
    ah al ay da de di do eh el en es ex fe ha he id ir la le lo me mi ni
    no oh os pa pe re se si su te ti tu un va ve vi ya yo
    ano aun bar con dar dan das dia dio dos doy ese esa eso
    fin fue fui gas gol hay hoy ida iba las les los luz mal mar mas mes mis
    muy nos oir par paz pan pie por que red rey rio sal san sed ser sin sol
    son soy sur sus tal tan tez tia tio tus una uno uso van vas ven ver ves
    vez vio vos voy
    """.split()
) | frozenset(
    # Second tier: four- and five-letter words that sit within a typo's reach
    # of a short one. Needed because the word typed can be longer than the
    # word expected -- "para" for "por", "estoy" for "soy" -- and those are
    # word confusions, not slips. Drawn from the deck vocabulary, so it is
    # deliberately in-domain rather than exhaustive; a real word missing from
    # it degrades to the old, more forgiving behaviour rather than to a
    # wrong rejection.
    """
    adios agua aire algo alli aqui auto ayer años baja baño bien buen
    buena busco cada cafe caro casa caso cero cien cola coman comen comi
    como copa creo cual dale deja dejar desde dias dice diez digas dije
    doce esta estan este esto estoy euro fila fresa frio fuera gafas grifo
    guay guey gusto hace haga hago hice hora jugo kilo lana lata lejos
    lunes madre majo malla mapa mayor media medio menos menu mesa miro
    mismo niño nota ocho okey onda otra padre pagar pana papa para pasar
    pedi pero pies piso pone poner quise rica rico robo ruido sabe saben
    saldo sale salgo sali salia salir salis salud seis sepa señal sido
    siga sois solo sono supe talla taxi tela tenia timo tinto tique todas
    todo todos tomar tomo trae tren tres vais vale vamos vaso veces venga
    vengo venid venis viene vimos vino visto viven zumo
    """.split()
)


def _forgivable_substitution(attempt_tok: str, accept_tok: str) -> bool:
    """True when `attempt_tok` reads as a mistyping of `accept_tok`.

    The question is not how short the token is -- an earlier version gated on
    length and got it wrong in both directions, forgiving "papa" for "para"
    while refusing "hoi" for "hoy". What matters is whether what was typed is
    a word: type a real, different Spanish word and you made an error; type
    something that is not a word at all and you made a slip.

    The lexicon is in-domain and partial by design. A real word missing from
    it falls back to plain edit distance -- the older, more forgiving
    behaviour -- so the failure mode is leniency, never a wrong rejection.
    """
    if edit_distance(attempt_tok, accept_tok) > _SUB_MAX_CHAR_DIST:
        return False
    return fold_accents(attempt_tok) not in _SHORT_REAL_WORDS



# Spanish pairs distinguished ONLY by the accent (tilde diacrítica). Folding
# accents is normally a kindness -- typing "donde esta" for "dónde está"
# should never be marked wrong -- but for these the accent IS the word, and
# folding conflates two different ones. The guard applies only when the whole
# expected answer is a single token, which is exactly the cloze-gap case where
# the distinction is what the card teaches; inside a full sentence the
# surrounding words carry the meaning and tolerance stays.
_DIACRITIC_HOMOGRAPHS: frozenset[frozenset[str]] = frozenset(
    frozenset(pair)
    for pair in (
        ("el", "él"), ("tu", "tú"), ("mi", "mí"), ("si", "sí"), ("se", "sé"),
        ("de", "dé"), ("te", "té"), ("mas", "más"), ("aun", "aún"),
        ("solo", "sólo"), ("que", "qué"), ("como", "cómo"), ("cual", "cuál"),
        ("quien", "quién"), ("donde", "dónde"), ("cuando", "cuándo"),
        ("cuanto", "cuánto"), ("esta", "está"), ("este", "éste"),
    )
)


def _is_diacritic_homograph(a: str, b: str) -> bool:
    """True when a and b are a real pair that differs only by the accent."""
    return a != b and frozenset((a, b)) in _DIACRITIC_HOMOGRAPHS

def _is_droppable(tok: str) -> bool:
    """True for a function word, or for a slip that can only be one.

    "la" mistyped as "lc" is still the article: it is not a Spanish word, and
    it is one keystroke from one. Requiring an exact match here made every
    mistyped article fail the whole sentence.
    """
    folded = fold_accents(tok)
    if folded in _OPTIONAL_TOKENS:
        return True
    if folded in _SHORT_REAL_WORDS:
        return False
    return any(edit_distance(folded, opt) <= 1 for opt in _OPTIONAL_TOKENS)


def _close_enough(att: list[str], acc: list[str]) -> bool:
    """True when `att` differs from `acc` by one *forgivable* token.

    Forgivable means either a typo/inflection of a single content word, or
    the insertion or omission of a function word. An arbitrary different
    word is NOT forgivable even though it is one token-edit away -- see the
    comment at the L4 call site for why that distinction carries the whole
    weight of this layer.
    """
    if att == acc:
        return True

    # Same length: at most one position may differ, and that pair must look
    # like a typo or an inflection rather than a different word.
    if len(att) == len(acc):
        diffs = [i for i, (x, y) in enumerate(zip(att, acc)) if x != y]
        if len(diffs) != 1:
            return False
        a_tok, b_tok = att[diffs[0]], acc[diffs[0]]
        return _forgivable_substitution(a_tok, b_tok)

    # Off by one token: allowed only when the extra token is a function word.
    if abs(len(att) - len(acc)) == 1:
        longer, shorter = (att, acc) if len(att) > len(acc) else (acc, att)
        for i in range(len(longer)):
            if longer[:i] + longer[i + 1 :] == shorter:
                return _is_droppable(longer[i])
        return False

    return False


def grade(attempt: str, *, accept: Sequence[str], reject: Sequence[str] = ()) -> Verdict:
    norm_attempt = " ".join(tokens(attempt))

    # L0: empty or a single character carries no gradeable content.
    if len(norm_attempt) <= 1:
        return Verdict(
            accepted=False,
            layer="L0_empty",
            reason="Escribe tu respuesta antes de comprobar.",
            matched=None,
            detail=None,
        )

    attempt_tokens = tokens(attempt)
    attempt_tokens_folded = [fold_accents(t) for t in attempt_tokens]

    # L1: banned (non-Peninsular) vocabulary — the one hard rejection.
    for r in reject:
        r_tokens_folded = [fold_accents(t) for t in tokens(r)]
        if not r_tokens_folded:
            continue
        if _is_subsequence(r_tokens_folded, attempt_tokens_folded):
            alt = accept[0] if accept else ""
            reject_word = r.strip()
            reason = f"En España no se dice «{reject_word}» — prueba con «{alt}»."
            detail = f"«{reject_word}» es de Latinoamérica; en España: «{alt}»"
            return Verdict(
                accepted=False,
                layer="L1_banned",
                reason=reason,
                matched=None,
                detail=detail,
            )

    canon_attempt_tokens = _canonicalize(attempt_tokens)
    canon_attempt = " ".join(canon_attempt_tokens)
    # A content word can collide with the politeness vocabulary: "hora"
    # mistyped as "hola" gets stripped as a greeting and the sentence loses a
    # token it needed. Keep an unstripped reading to compare against too.
    literal_attempt_tokens = _canonicalize(attempt_tokens, politeness=False)

    canon_accepts: list[tuple[str, list[str], str, list[str]]] = []
    for original in accept:
        toks_a = tokens(original)
        canon_tokens_a = _canonicalize(toks_a)
        canon_accepts.append(
            (
                original,
                canon_tokens_a,
                " ".join(canon_tokens_a),
                _canonicalize(toks_a, politeness=False),
            )
        )

    # L2: exact match (post-canonicalization), accent-sensitive.
    for original, _canon_tokens_a, canon_str_a, _lit_a in canon_accepts:
        if canon_attempt == canon_str_a:
            return Verdict(
                accepted=True,
                layer="L2_exact",
                reason="¡Correcto!",
                matched=original,
                detail=None,
            )

    # L3: matches once accents are folded — an accent slip, never a block.
    folded_attempt = fold_accents(canon_attempt)
    for original, _canon_tokens_a, canon_str_a, _lit_a in canon_accepts:
        # When the whole expected answer is one token and the pair differs
        # only by the accent that distinguishes two real words (se/sé,
        # el/él), folding would accept the wrong word outright. That is
        # precisely the distinction such a card exists to teach.
        if _is_diacritic_homograph(canon_attempt, canon_str_a):
            continue
        if folded_attempt == fold_accents(canon_str_a):
            return Verdict(
                accepted=True,
                layer="L3_accent",
                reason=f"Bien — ojo con la tilde: «{original}»",
                matched=original,
                detail=None,
            )

    # L4: close enough — absorbs articles, minor agreement slips, typos.
    #
    # Token-level distance <=1 is only meaningful when the accept form has
    # more than one token: for a single-token accept form, ANY differing
    # single-token attempt is trivially "1 token substitution" apart, which
    # would accept any wrong word. Single-token accept forms are judged by
    # character edit distance instead, per the contract's explicit OR clause.
    #
    # Multi-token forms need the same guard for the SAME reason. A bare
    # token-distance <=1 test accepts "tengo sed" for "tengo hambre" and
    # "soy aburrido" for "estoy aburrido" -- one token apart, opposite
    # meaning. In a *learning* tool that is worse than a false reject: a
    # false reject annoys you, a false accept teaches you the wrong thing.
    # `_close_enough` therefore requires that the one differing token be
    # lexically close (a typo or inflection), or that the inserted/dropped
    # token be a function word.
    for original, canon_tokens_a, canon_str_a, literal_tokens_a in canon_accepts:
        if _blocked_by_ene_tilde_confusion(canon_attempt, canon_str_a):
            continue
        # Same reason as at L3: edit distance would otherwise re-admit
        # the homograph the accent guard just excluded.
        if _is_diacritic_homograph(canon_attempt, canon_str_a):
            continue
        if len(canon_tokens_a) >= 1 and (
            _close_enough(canon_attempt_tokens, canon_tokens_a)
            or _close_enough(literal_attempt_tokens, canon_tokens_a)
            or _close_enough(literal_attempt_tokens, literal_tokens_a)
        ):
            return Verdict(
                accepted=True,
                layer="L4_close",
                reason=f"Aceptado — muy cerca de «{original}»",
                matched=original,
                detail=None,
            )
        if (
            len(canon_tokens_a) == 1
            and _forgivable_substitution(canon_attempt, canon_str_a)
        ):
            return Verdict(
                accepted=True,
                layer="L4_close",
                reason=f"Aceptado — muy cerca de «{original}»",
                matched=original,
                detail=None,
            )

    # A rejection caused solely by n-for-ñ is correct but baffling unless we
    # say so: ñ is the one character that is never folded (ano/año), and a
    # learner typing on a US keyboard will hit this constantly.
    for original, _canon_tokens_a, canon_str_a, _lit_a in canon_accepts:
        if _is_diacritic_homograph(canon_attempt, canon_str_a):
            return Verdict(
                accepted=False,
                layer="L5_reject",
                reason=f"La tilde cambia la palabra: «{original}»",
                matched=None,
                detail=f"«{canon_attempt}» y «{canon_str_a}» son palabras distintas, "
                "no la misma con o sin tilde.",
            )
        # Fold the *other* accents first, so an otherwise-accentless attempt
        # ("donde esta el bano") still reveals ñ as the sole real difference.
        if _blocked_by_ene_tilde_confusion(
            fold_accents(canon_attempt), fold_accents(canon_str_a)
        ):
            return Verdict(
                accepted=False,
                layer="L5_reject",
                reason=f"Cuidado con la ñ: «{original}»",
                matched=None,
                detail="La ñ nunca es opcional — «ano» y «año» no son lo mismo. "
                "En un teclado US: opción + n, luego la vocal.",
            )

    # L5: nothing matched — stay encouraging, this is the tool's failure mode.
    return Verdict(
        accepted=False,
        layer="L5_reject",
        reason="Casi — no coincide, pero vas bien. ¡Sigue intentando!",
        matched=None,
        detail=None,
    )
