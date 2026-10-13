"""Quality signals at scale, on a Colab GPU (self-contained: fetches its own data).

    colab new -s quality --gpu A100
    colab upload -s quality interp/quality/colab_quality.py /content/colab_quality.py
    # then launch in the background on the VM and poll /content/out/log.txt

The MLX run (quality.py) on Qwen3-4B 4-bit had three problems this fixes:
  * its "meaning" corruptions changed length or broke the grammar, so a
    character count explained most of the hub check's score (drop_clause:
    length alone 0.89 vs hub 1.00). Here the meaning corruptions are
    fluent, grammatical and length-preserving -- negation, number, entity,
    antonym -- so only a comparison against the source can catch them;
  * no length baseline: now a column for every corruption;
  * no uncertainty: every number carries a 95% bootstrap interval.
Also: full EsCoLA train (not a 2k sample), ~1,700 NTREX sentences (not
150), bf16 weights where the GPU has them (fp16 on T4), hub layers found per model (not Qwen's 6-23), two models.

Writes /content/out/<model>.json and /content/out/log.txt.
"""

from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

OUT = Path(os.environ.get("QUALITY_OUT", "/content/out"))
OUT.mkdir(parents=True, exist_ok=True)
LOG = open(OUT / "log.txt", "a", buffering=1)
MODELS = sys.argv[1:] or ["Qwen/Qwen3-4B-Instruct-2507", "unsloth/gemma-3-4b-it"]
SEED, BOOT = 0, 1000
N_HUB = 300  # NTREX sentences used to locate each model's hub; corruptions use the rest
MAX_PAIRS = 400  # per corruption type: keeps one model well inside a Colab session


def log(*a):
    print(*a, file=LOG, flush=True)
    print(*a, flush=True)


# --- data ---------------------------------------------------------------------

NTREX = "https://raw.githubusercontent.com/MicrosoftTranslator/NTREX/main/NTREX-128/newstest2019-ref.{}.txt"
ESCOLA = "https://huggingface.co/datasets/nbel/EsCoLA/resolve/main/EsCoLA_InDomain{}.tsv"


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8")


def escola(split: str) -> list[tuple[str, int]]:
    rows = csv.DictReader(io.StringIO(fetch(ESCOLA.format(split))), delimiter="\t")
    return [(r["Sentence"], int(r["Label"])) for r in rows]


# --- corruptions ----------------------------------------------------------------
# form: the Spanish is broken.  meaning: fluent Spanish that no longer says
# what the English source says -- only a source comparison can catch these.

_WORD = re.compile(r"\b\w+\b", re.UNICODE)


def _swap_first(text, table):
    for m in _WORD.finditer(text):
        w = m.group(0)
        if w.lower() in table:
            new = table[w.lower()]
            new = new.capitalize() if w[0].isupper() else new
            return text[: m.start()] + new + text[m.end():]
    return None


ARTICLES = {"el": "la", "la": "el", "los": "las", "las": "los", "un": "una", "una": "un"}
VERB_NUMBER = {"es": "son", "son": "es", "está": "están", "están": "está", "tiene": "tienen",
               "tienen": "tiene", "ha": "han", "han": "ha", "fue": "fueron", "fueron": "fue",
               "puede": "pueden", "pueden": "puede", "dijo": "dijeron", "dijeron": "dijo"}
ANTONYMS = {"más": "menos", "menos": "más", "antes": "después", "después": "antes",
            "mayor": "menor", "menor": "mayor", "ganó": "perdió", "perdió": "ganó",
            "subió": "bajó", "bajó": "subió", "aumentó": "disminuyó", "disminuyó": "aumentó",
            "aceptó": "rechazó", "rechazó": "aceptó", "abrió": "cerró", "cerró": "abrió",
            "mejor": "peor", "peor": "mejor", "siempre": "nunca", "nunca": "siempre"}
PLACES = ["México", "Chile", "Perú", "Francia", "Alemania", "Italia", "China", "Japón", "Rusia",
          "Brasil", "Canadá", "Londres", "París", "Madrid", "Berlín", "Moscú", "Escocia", "Irlanda",
          "India", "Australia", "Texas", "California", "Florida", "Siria", "Irán", "Israel"]
NEGATABLE = {"es", "era", "fue", "ha", "había", "hay", "está", "son", "tiene", "puede", "dijo",
             "han", "estaba", "será", "habría", "podría", "quiere", "sabe"}


def gender(t, rng):
    return _swap_first(t, ARTICLES)


def verb_number(t, rng):
    return _swap_first(t, VERB_NUMBER)


def nonword(t, rng):
    ws = [m for m in _WORD.finditer(t) if len(m.group(0)) >= 7 and m.group(0).isalpha()]
    if not ws:
        return None
    m = rng.choice(ws)
    w, i = m.group(0), len(m.group(0)) // 2
    new = w[:i - 1] + w[i] + w[i - 1] + w[i + 1:]
    return None if new == w else t[: m.start()] + new + t[m.end():]


def negation(t, rng):
    """Remove an existing 'no', else add one before a common finite verb."""
    m = re.search(r"\bno (?=\w)", t)
    if m:
        return t[: m.start()] + t[m.end():]
    for m in _WORD.finditer(t):
        if m.group(0) in NEGATABLE:
            return t[: m.start()] + "no " + t[m.start():]
    return None


def number(t, rng):
    """Change one number to a different one with the same digit count."""
    ms = [m for m in re.finditer(r"\b\d+\b", t)]
    if not ms:
        return None
    m = rng.choice(ms)
    s = m.group(0)
    lo, hi = (10 ** (len(s) - 1) if len(s) > 1 else 1), 10 ** len(s) - 1
    choices = [n for n in range(lo, hi + 1) if str(n) != s] if hi - lo < 50 else None
    new = str(rng.choice(choices)) if choices else str((int(s) + rng.randint(1, 9) * (10 ** max(0, len(s) - 2))) % (hi + 1) or lo)
    new = new.zfill(len(s)) if len(new) < len(s) else new
    return None if new == s else t[: m.start()] + new + t[m.end():]


def entity(t, rng):
    """Swap one place name for another."""
    for m in _WORD.finditer(t):
        if m.group(0) in PLACES:
            other = rng.choice([p for p in PLACES if p != m.group(0)])
            return t[: m.start()] + other + t[m.end():]
    return None


def antonym(t, rng):
    return _swap_first(t, ANTONYMS)


FORM = {"gender": gender, "verb_number": verb_number, "nonword": nonword}
MEANING = {"negation": negation, "number": number, "entity": entity, "antonym": antonym}


# --- encoding ---------------------------------------------------------------------


@torch.no_grad()
def encode(model, tok, texts, layers, bs=16, skip_first=1):
    """Per-layer mean-pooled residual (fp16, CPU) and mean/min token log-prob."""
    pooled, meanlp, minlp = [], [], []
    for b in range(0, len(texts), bs):
        batch = texts[b:b + bs]
        enc = tok(batch, return_tensors="pt", padding=True, truncation=True, max_length=128).to(model.device)
        out = model(**enc, output_hidden_states=True)
        mask = enc["attention_mask"].clone()
        mask[:, :skip_first] = 0
        m = mask.unsqueeze(-1).to(out.hidden_states[0].dtype)
        # hidden_states[0] is the embedding; [i + 1] is the residual after block i
        hs = torch.stack([out.hidden_states[i + 1] for i in layers], 1)  # [B, L, T, d]
        # fp32, not fp16: Gemma has massive activations (>65504) that overflow fp16 to inf
        pooled.append(((hs.float() * m.unsqueeze(1).float()).sum(2) / m.sum(1).unsqueeze(1).float()).cpu())
        logp = torch.log_softmax(out.logits[:, :-1].float(), -1)
        tgt = enc["input_ids"][:, 1:]
        tlp = logp.gather(-1, tgt.unsqueeze(-1))[..., 0]
        valid = enc["attention_mask"][:, 1:].bool()
        meanlp.append(((tlp * valid).sum(1) / valid.sum(1)).cpu())
        minlp.append(tlp.masked_fill(~valid, 0.0).min(1).values.cpu())
    return torch.cat(pooled).numpy(), torch.cat(meanlp).numpy(), torch.cat(minlp).numpy()


# --- statistics -------------------------------------------------------------------


def fit_probe(X, y, k=128, steps=600, lr=0.5, l2=1e-2):
    X = torch.tensor(X, dtype=torch.float32, device="cuda")
    y = torch.tensor(y, dtype=torch.float32, device="cuda")
    mu = X.mean(0)
    _, _, V = torch.pca_lowrank(X - mu, q=k, center=False)
    A = (X - mu) @ V
    s = A.std(0) + 1e-6
    A = A / s
    w = torch.zeros(A.shape[1], device="cuda")
    b = torch.zeros((), device="cuda")
    for _ in range(steps):
        p = torch.sigmoid(A @ w + b)
        g = p - y
        w -= lr * (A.T @ g / len(A) + l2 * w)
        b -= lr * g.mean()
    return lambda Z: (((torch.tensor(Z, dtype=torch.float32, device="cuda") - mu) @ V / s) @ w + b).cpu().numpy()


def auc(scores, labels):
    pos, neg = scores[labels == 1], scores[labels == 0]
    return float((pos[:, None] > neg[None]).mean() + 0.5 * (pos[:, None] == neg[None]).mean())


def boot(fn, n, rng):
    """95% bootstrap interval of fn(idx) over resampled indices."""
    vals = sorted(fn(rng.integers(0, n, n)) for _ in range(BOOT))
    return [float(vals[int(0.025 * BOOT)]), float(vals[int(0.975 * BOOT)])]


def pairwise(clean, bad):
    """Fraction of pairs where clean scores above corrupted; ties count half."""
    return (clean > bad).astype(float) + 0.5 * (clean == bad)


def hub_scores(en, es, en_mu, es_mu):
    a, b = en - en_mu, es - es_mu
    return ((a * b).sum(-1) / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1))).mean(-1)


def retrieval(a, b):
    a = a - a.mean(0)
    b = b - b.mean(0)
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    return float(((a @ b.T).argmax(1) == np.arange(len(a))).mean())


# --- run --------------------------------------------------------------------------


def run(model_id, data):
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(model_id)
    tok.padding_side = "right"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    # T4 (Turing) has no native bf16; fp16 there. Gemma is known to overflow
    # in fp16, so NaNs are checked for below rather than silently averaged.
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype, device_map="cuda").eval()
    log(f"[{model_id}] dtype {dtype}, gpu {torch.cuda.get_device_name()}")
    n_layers = model.config.get_text_config().num_hidden_layers
    layers = list(range(n_layers))
    log(f"[{model_id}] loaded, {n_layers} layers, {time.time() - t0:.0f}s")

    def enc(texts, label):
        t = time.time()
        r = encode(model, tok, texts, layers)
        log(f"  {label}: {len(texts)} in {time.time() - t:.0f}s")
        return r

    probe_nan = encode(model, tok, [s for s, _ in data["dev"][:4]], layers)
    if np.isnan(probe_nan[0].astype(np.float32)).any() or np.isnan(probe_nan[1]).any():
        log(f"[{model_id}] NaN activations at {dtype}; skipping this model")
        return
    tr, trm, _ = enc([s for s, _ in data["train"]], "escola train")
    dv, dvm, dvn = enc([s for s, _ in data["dev"]], "escola dev")
    ytr = np.array([l for _, l in data["train"]], dtype=np.float32)
    ydv = np.array([l for _, l in data["dev"]])

    # 1. EsCoLA: absolute judgement
    res = {"model": model_id, "n_layers": n_layers, "complete": False}
    path = OUT / f"{model_id.replace('/', '__')}.json"

    def save():
        path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    rng = np.random.default_rng(SEED)
    res["escola"] = {
        "n_dev": len(ydv),
        "surprisal_mean": {"auc": auc(dvm, ydv), "ci": boot(lambda i: auc(dvm[i], ydv[i]), len(ydv), rng)},
        "surprisal_min": {"auc": auc(dvn, ydv), "ci": boot(lambda i: auc(dvn[i], ydv[i]), len(ydv), rng)},
    }
    probes, curve = [], []
    for L in layers:
        try:
            f = fit_probe(tr[:, L], ytr)
            probes.append(f)
            curve.append(auc(f(dv[:, L]), ydv))
        except Exception as e:  # one ill-conditioned layer shouldn't sink the model
            log(f"  probe layer {L} failed: {type(e).__name__}")
            probes.append(None)
            curve.append(float("nan"))
    best = int(np.nanargmax(curve))
    pdv = probes[best](dv[:, best])
    res["escola"]["probe_curve"] = curve
    res["escola"]["probe"] = {"layer": best, "auc": curve[best], "ci": boot(lambda i: auc(pdv[i], ydv[i]), len(ydv), rng),
                              "note": "layer chosen on this same dev set, so slightly optimistic"}
    save()
    log(f"  escola: surprisal {res['escola']['surprisal_mean']['auc']:.3f}, probe {curve[best]:.3f} @ {best}")

    # 2. locate this model's hub on held-aside sentences
    hen, _, _ = enc(data["hub_en"], "hub en")
    hes, _, _ = enc(data["hub_es"], "hub es")
    ret = [retrieval(hen[:, L].astype(np.float32), hes[:, L].astype(np.float32)) for L in layers]
    hub = [L for L in layers if ret[L] >= 0.95 * max(ret)]
    res["hub"] = {"retrieval_curve": ret, "layers": hub}
    log(f"  hub layers {hub[0]}-{hub[-1]} (retrieval peak {max(ret):.2f})")
    en_mu = hen[:, hub].astype(np.float32).mean(0)
    es_mu = hes[:, hub].astype(np.float32).mean(0)

    # 3. corruption pairs
    res["pairs"] = {}
    for name, items in data["pairs"].items():
        src = [data["en"][i] for i, _ in items]
        cln = [data["es"][i] for i, _ in items]
        bad = [b for _, b in items]
        ea, _, _ = enc(src, f"{name} en")
        ca, cm, cn = enc(cln, f"{name} clean")
        ba, bm, bn = enc(bad, f"{name} bad")
        sig = {
            "length": (-np.abs(np.array([len(c) / len(s) for c, s in zip(cln, src)]) - 1.15),
                       -np.abs(np.array([len(b) / len(s) for b, s in zip(bad, src)]) - 1.15)),
            "surprisal_mean": (cm, bm),
            "surprisal_min": (cn, bn),
            "probe": (probes[best](ca[:, best]), probes[best](ba[:, best])),
            "hub": (hub_scores(ea[:, hub].astype(np.float32), ca[:, hub].astype(np.float32), en_mu, es_mu),
                    hub_scores(ea[:, hub].astype(np.float32), ba[:, hub].astype(np.float32), en_mu, es_mu)),
        }
        row = {"n": len(items), "family": "form" if name in FORM else "meaning",
               "example": {"en": src[0], "clean": cln[0], "bad": bad[0]}}
        for k, (c, b) in sig.items():
            w = pairwise(c, b)
            row[k] = {"acc": float(w.mean()), "ci": boot(lambda i: float(w[i].mean()), len(w), rng)}
        res["pairs"][name] = row
        save()
        log(f"  {name:<12} n={len(items):<4} " + "  ".join(f"{k} {row[k]['acc']:.2f}" for k in sig))

    res["seconds"] = time.time() - t0
    res["complete"] = True
    save()
    del model
    torch.cuda.empty_cache()


def main():
    rng = random.Random(SEED)
    es = fetch(NTREX.format("spa")).splitlines()
    en = fetch(NTREX.format("eng-US")).splitlines()
    pairs = {n: [] for n in [*FORM, *MEANING]}
    for i in range(N_HUB, min(len(es), len(en))):
        for n, fn in {**FORM, **MEANING}.items():
            bad = fn(es[i], rng)
            if bad and bad != es[i]:
                pairs[n].append((i, bad))
    pairs = {n: rng.sample(v, min(len(v), MAX_PAIRS)) for n, v in pairs.items()}
    data = {"train": escola("Train"), "dev": escola("Dev"), "es": es, "en": en,
            "hub_en": en[:N_HUB], "hub_es": es[:N_HUB], "pairs": pairs}
    log(f"data: escola train {len(data['train'])}, dev {len(data['dev'])}; pairs " +
        ", ".join(f"{k} {len(v)}" for k, v in pairs.items()))
    for m in MODELS:
        try:
            run(m, data)
        except Exception as e:  # keep going to the next model
            log(f"[{m}] FAILED: {type(e).__name__}: {e}")
    log("DONE")


if __name__ == "__main__":
    main()
