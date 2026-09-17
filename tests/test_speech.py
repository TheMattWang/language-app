"""Tests for `drill.speech`. Never actually plays audio -- `subprocess.run`
and `subprocess.Popen` are monkeypatched throughout."""

from __future__ import annotations

import subprocess

import pytest

from drill import speech


@pytest.fixture(autouse=True)
def _reset_cache():
    speech._cached_voice = speech._UNSET
    yield
    speech._cached_voice = speech._UNSET


def _probe_output(voices: str) -> "subprocess.CompletedProcess":
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=voices, stderr="")


def test_speak_builds_argv_list_never_shell(monkeypatch):
    monkeypatch.setattr(speech, "available_voice", lambda: "Eddy")
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

        class _P:
            pass

        return _P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    ok = speech.speak("hola", voice="Eddy")
    assert ok is True
    assert captured["args"][:3] == ["/usr/bin/say", "-v", "Eddy"]
    assert "hola" in captured["args"]
    assert "shell" not in captured["kwargs"]


def test_speak_passes_metacharacters_as_single_argv_element(monkeypatch):
    monkeypatch.setattr(speech, "available_voice", lambda: "Eddy")
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args

        class _P:
            pass

        return _P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    nasty = "hola; rm -rf / `echo pwned` $(whoami)"
    speech.speak(nasty, voice="Eddy")
    assert captured["args"][-1] == nasty
    assert captured["args"].count(nasty) == 1


def test_available_voice_none_when_say_missing(monkeypatch):
    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("no such file: /usr/bin/say")

    monkeypatch.setattr(subprocess, "run", raise_missing)
    assert speech.available_voice() is None


def test_speak_false_when_say_missing(monkeypatch):
    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("no such file: /usr/bin/say")

    monkeypatch.setattr(subprocess, "run", raise_missing)
    assert speech.speak("hola") is False


def test_probe_result_is_cached(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _probe_output("Eddy (Spanish (Spain)) es_ES    # hola\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    first = speech.available_voice()
    second = speech.available_voice()
    assert first == "Eddy" == second
    assert len(calls) == 1


def test_available_voice_picks_first_peninsular_match(monkeypatch):
    output = (
        "Alex                en_US    # hi\n"
        "Flo (Spanish (Spain)) es_ES    # hola\n"
        "Grandma (Spanish (Spain)) es_ES    # hola\n"
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _probe_output(output))
    assert speech.available_voice() == "Flo"


def test_speak_returns_false_when_subprocess_fails(monkeypatch):
    monkeypatch.setattr(speech, "available_voice", lambda: "Eddy")

    def raise_oserror(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "Popen", raise_oserror)
    assert speech.speak("hola", voice="Eddy") is False


def test_speak_blocking_returns_false_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(speech, "available_voice", lambda: "Eddy")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1)
    )
    assert speech.speak("hola", voice="Eddy", blocking=True) is False


def test_speak_false_without_a_voice(monkeypatch):
    monkeypatch.setattr(speech, "available_voice", lambda: None)
    assert speech.speak("hola") is False


def test_is_available_reflects_voice_presence(monkeypatch):
    monkeypatch.setattr(speech, "available_voice", lambda: None)
    assert speech.is_available() is False
    monkeypatch.setattr(speech, "available_voice", lambda: "Eddy")
    assert speech.is_available() is True


def test_cmd_listen_exits_nonzero_when_tts_unavailable(monkeypatch, tmp_path, capsys):
    from drill.cli import build_parser

    monkeypatch.setattr(speech, "is_available", lambda: False)
    db = tmp_path / "t.db"
    args = build_parser().parse_args(["--db", str(db), "listen"])
    rc = args.func(args)
    assert rc != 0
    err = capsys.readouterr().err
    assert err.strip() != ""
