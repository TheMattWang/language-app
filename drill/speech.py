"""Text-to-speech for the listening/dictation drill, via macOS `say`.

Shells out to `/usr/bin/say` with a Peninsular Spanish voice. Every
failure path here -- `say` missing entirely, no Peninsular voice
installed, the subprocess call itself failing -- degrades to a silent,
still-usable drill rather than raising. Callers (`drill/cli.py`
`cmd_listen`, `drill/app.py`'s replay button) are expected to check
`is_available()` up front and skip offering audio at all when it's
False, rather than relying on `speak()` failing silently every time.

Always shells out with an argument list, never `shell=True` -- card
text is arbitrary user/import content and must never be interpreted by
a shell.
"""

from __future__ import annotations

import re
import subprocess

SAY_BIN = "/usr/bin/say"

# Order is preference: Mónica first (the classic Spain voice), then the
# newer Siri-derived es_ES voices, in the order they were introduced.
PENINSULAR_VOICES: tuple[str, ...] = ("Mónica", "Eddy", "Flo", "Grandma", "Grandpa")

_PROBE_TIMEOUT = 3.0

_UNSET = object()
_cached_voice: object = _UNSET


def available_voice() -> str | None:
    """First entry of `PENINSULAR_VOICES` present as an es_ES voice, per
    `say -v '?'`. Cached after the first call (including a None result --
    a machine without `say` or without a Peninsular voice doesn't grow one
    mid-process, and re-probing on every card would be wasted latency in
    the listening loop).
    """
    global _cached_voice
    if _cached_voice is not _UNSET:
        return _cached_voice  # type: ignore[return-value]

    try:
        result = subprocess.run(
            [SAY_BIN, "-v", "?"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        _cached_voice = None
        return None

    if result.returncode != 0:
        _cached_voice = None
        return None

    lines = result.stdout.splitlines()
    for voice in PENINSULAR_VOICES:
        for line in lines:
            if not line.startswith(voice):
                continue
            rest = line[len(voice):]
            if rest and not rest[0].isspace():
                # e.g. a hypothetical "Eddystone" voice -- not a match.
                continue
            if re.search(r"\bes_ES\b", line):
                _cached_voice = voice
                return voice

    _cached_voice = None
    return None


def is_available() -> bool:
    return available_voice() is not None


def speak(text: str, *, voice: str | None = None, rate: int = 180, blocking: bool = False) -> bool:
    """Speak `text` aloud via `say`. Returns True if audio was launched
    (or, when `blocking=True`, completed successfully), False if TTS is
    unavailable or the call failed for any reason. Never raises.

    Non-blocking by default so a listening-loop or GUI caller doesn't
    freeze waiting for `say` to finish talking.
    """
    if not text:
        return False

    v = voice if voice is not None else available_voice()
    if v is None:
        return False

    # "--" terminates option parsing: a card beginning with "-" (a dash-led
    # phrase, a minus sign in a price) would otherwise be read by `say` as a
    # flag, and the non-blocking path below never sees the nonzero exit --
    # it would report success having played nothing.
    args = [SAY_BIN, "-v", v, "-r", str(rate), "--", text]

    try:
        if blocking:
            result = subprocess.run(args, timeout=30)
            return result.returncode == 0
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
