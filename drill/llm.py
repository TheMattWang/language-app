"""Local LLM backends: one `chat()` call, served by Ollama or MLX.

Everything runs on the learner's machine. Ollama is reached over its
localhost HTTP API with `urllib`, so the core stays stdlib-only; MLX
(Apple Silicon) is an optional extra whose `mlx_lm` import happens only
when that backend is first used.

The model is a conversational engine, never the language authority:
nothing here decides whether the learner was right (see the README's
"no LLM at grade time"). Callers check what comes back with
`drill.register` before showing it.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND",
    "DEFAULT_MODELS",
    "LLMUnavailable",
    "Message",
    "Reply",
    "available",
    "chat",
]

Message = dict  # {"role": "system"|"user"|"assistant", "content": str}

BACKENDS = ("ollama", "mlx")
DEFAULT_BACKEND = "ollama"
# 3-4B instruct is the Spanish quality floor (research/02a-quality-floor.md);
# the final pick waits on the probe gate in drill/probes.py.
DEFAULT_MODELS = {
    "ollama": "qwen2.5:3b",
    "mlx": "mlx-community/Qwen2.5-3B-Instruct-8bit",
}
OLLAMA_HOST = "http://127.0.0.1:11434"


class LLMUnavailable(RuntimeError):
    """The backend isn't installed, isn't running, or lacks the model.

    The message says what to do about it, in a form fit to show a learner.
    """


@dataclass(frozen=True)
class Reply:
    text: str
    seconds: float
    backend: str
    model: str


def chat(
    messages: Sequence[Message],
    *,
    backend: str = DEFAULT_BACKEND,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 120,
    timeout: float = 120.0,
) -> Reply:
    """One assistant turn for `messages`. Raises LLMUnavailable."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}; expected one of {BACKENDS}")
    model = model or DEFAULT_MODELS[backend]
    start = time.perf_counter()
    if backend == "ollama":
        text = _ollama_chat(messages, model, temperature, max_tokens, timeout)
    else:
        text = _mlx_chat(messages, model, temperature, max_tokens)
    return Reply(text=text.strip(), seconds=time.perf_counter() - start, backend=backend, model=model)


def available(backend: str = DEFAULT_BACKEND, model: str | None = None) -> str | None:
    """None when `backend` can serve `model`, else why not (learner-facing)."""
    model = model or DEFAULT_MODELS.get(backend, "")
    if backend == "ollama":
        try:
            tags = _ollama_get("/api/tags", timeout=2.0)
        except LLMUnavailable as exc:
            return str(exc)
        names = {m.get("name") for m in tags.get("models", [])}
        if model not in names and f"{model}:latest" not in names:
            return f"Ollama is running but doesn't have {model}. Run:  ollama pull {model}"
        return None
    if backend == "mlx":
        try:
            import mlx_lm  # noqa: F401
        except ImportError:
            return "MLX isn't installed. Run:  pip install mlx-lm   (Apple Silicon only)"
        return None
    return f"unknown backend {backend!r}"


# --- Ollama --------------------------------------------------------------------


def _ollama_get(path: str, *, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(OLLAMA_HOST + path, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise LLMUnavailable(
            "Can't reach Ollama. Install it from https://ollama.com and make sure it's running."
        ) from exc


def _ollama_chat(
    messages: Sequence[Message], model: str, temperature: float, max_tokens: int, timeout: float
) -> str:
    body = {
        "model": model,
        "messages": list(messages),
        "stream": False,
        # Reasoning models spend the whole budget thinking and return an
        # empty reply (research/06-bench-local-baseline.md); never let them.
        "think": False,
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 4096},
    }
    req = urllib.request.Request(
        OLLAMA_HOST + "/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LLMUnavailable(
                f"Ollama doesn't have {model}. Run:  ollama pull {model}"
            ) from exc
        raise LLMUnavailable(f"Ollama returned HTTP {exc.code} for {model}.") from exc
    except TimeoutError as exc:
        raise LLMUnavailable(_slow(model, timeout)) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise LLMUnavailable(_slow(model, timeout)) from exc
        raise LLMUnavailable(
            "Can't reach Ollama. Install it from https://ollama.com and make sure it's running."
        ) from exc
    except ConnectionError as exc:
        raise LLMUnavailable(
            "Can't reach Ollama. Install it from https://ollama.com and make sure it's running."
        ) from exc
    return data.get("message", {}).get("content", "")


def _slow(model: str, timeout: float) -> str:
    # Ollama answered the connection but not the request in time: it's
    # running, so "install Ollama" would be the wrong advice.
    return (
        f"Ollama is running but {model} didn't answer within {timeout:.0f}s. "
        "The machine may be busy, or the model too large for it."
    )


# --- MLX -----------------------------------------------------------------------

_mlx_cache: dict[str, tuple[object, object]] = {}


def _mlx_chat(messages: Sequence[Message], model: str, temperature: float, max_tokens: int) -> str:
    try:
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler
    except ImportError as exc:
        raise LLMUnavailable(
            "MLX isn't installed. Run:  pip install mlx-lm   (Apple Silicon only)"
        ) from exc
    if model not in _mlx_cache:
        _mlx_cache[model] = load(model)
    mlx_model, tokenizer = _mlx_cache[model]
    prompt = tokenizer.apply_chat_template(list(messages), add_generation_prompt=True)
    return generate(
        mlx_model,
        tokenizer,
        prompt=prompt,
        max_tokens=max_tokens,
        sampler=make_sampler(temp=temperature),
    )
