"""drill.llm error messages -- what a learner is told when the model fails."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from drill import llm


def _raise(exc):
    def urlopen(*_, **__):
        raise exc
    return urlopen


def test_timeout_is_not_reported_as_missing_ollama(monkeypatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raise(urllib.error.URLError(socket.timeout("timed out"))))
    with pytest.raises(llm.LLMUnavailable, match="running but .* didn't answer"):
        llm.chat([{"role": "user", "content": "hola"}], model="m", timeout=5)


def test_bare_timeout_is_slow_not_missing(monkeypatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raise(TimeoutError()))
    with pytest.raises(llm.LLMUnavailable, match="didn't answer within 5s"):
        llm.chat([{"role": "user", "content": "hola"}], model="m", timeout=5)


def test_refused_connection_says_install(monkeypatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raise(urllib.error.URLError(ConnectionRefusedError())))
    with pytest.raises(llm.LLMUnavailable, match="Can't reach Ollama"):
        llm.chat([{"role": "user", "content": "hola"}], model="m")


def test_missing_model_says_pull(monkeypatch) -> None:
    err = urllib.error.HTTPError("u", 404, "not found", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", _raise(err))
    with pytest.raises(llm.LLMUnavailable, match="ollama pull m"):
        llm.chat([{"role": "user", "content": "hola"}], model="m")
