"""Does the model know when its Spanish is wrong?

Run (from repo root):  .venv/bin/python interp/quality/quality.py [--model REPO]
(needs interp/fetch_data.sh, plus EsCoLA in interp/data/ -- see NOTES.md)

Three reference-free quality signals, compared on the same sentences:
  surprisal  mean / min log-prob the model gives the sentence's own tokens.
             No interp at all: the baseline anything else must beat.
  probe      linear probe on each layer's mean-pooled residual stream,
             trained on EsCoLA (linguist-labelled grammatical / not).
  hub        cosine between the English source and the Spanish candidate in
             the middle layers where language_geometry found meaning shared
             across languages (layers 6-23 for Qwen3-4B). Catches *meaning*
             errors a grammar signal can't see.

Tested on:
  EsCoLA dev                  AUC, per layer for the probe
  controlled corruption pairs pairwise accuracy: does the signal rank the
                              clean NTREX sentence above its corrupted copy?
                              (form: gender, verb_number, nonword;
                               meaning: drop_clause, swap_content)
Saves cache/, results.json, quality.png.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
sys.path.insert(0, str(HERE.parent / "language_geometry"))

import corrupt  # noqa: E402

N_TRAIN = 2000  # EsCoLA training subsample (stratified) -- keeps the run ~15 min on the Air
N_PAIRS = 150   # NTREX sentences to corrupt
HUB = (6, 23)   # language_geometry: translation retrieval >= 0.93 here (Qwen3-4B)


def escola(split: str) -> list[tuple[str, int]]:
    path = DATA / f"EsCoLA_InDomain{split}.tsv"
    with path.open(encoding="utf-8") as f:
        return [(r["Sentence"], int(r["Label"])) for r in csv.DictReader(f, delimiter="\t")]


def ntrex(lang: str) -> list[str]:
    return (DATA / f"newstest2019-ref.{lang}.txt").read_text(encoding="utf-8").splitlines()


def build_sets(rng: random.Random) -> dict:
    train = escola("Train")
    by = {0: [s for s in train if s[1] == 0], 1: [s for s in train if s[1] == 1]}
    k0 = int(N_TRAIN * len(by[0]) / len(train))
    train = rng.sample(by[0], k0) + rng.sample(by[1], N_TRAIN - k0)

    es, en = ntrex("spa"), ntrex("eng-US")
    idx = rng.sample(range(150, len(es)), N_PAIRS)  # skip language_geometry's first 150
    pool = [es[i] for i in range(len(es)) if i not in idx]
    pairs = {name: [] for name in [*corrupt.FORM, *corrupt.MEANING]}
    for i in idx:
        for name, fn in corrupt.FORM.items():
            bad = fn(es[i], rng)
            if bad:
                pairs[name].append((i, bad))
        bad = corrupt.drop_clause(es[i], rng)
        if bad:
            pairs["drop_clause"].append((i, bad))
        bad = corrupt.swap_content(es[i], rng, pool)
        if bad:
            pairs["swap_content"].append((i, bad))
    return {"train": train, "dev": escola("Dev"), "idx": idx, "es": es, "en": en, "pairs": pairs}


def encode(cap, texts: list[str], layers: list[int], label: str) -> tuple[np.ndarray, list[np.ndarray]]:
    acts, logps = [], []
    t0 = time.time()
    for j, t in enumerate(texts):
        a, lp = cap.pooled_and_logprobs(t, layers)
        acts.append(a)
        logps.append(lp)
        if (j + 1) % 250 == 0:
            print(f"  {label}: {j + 1}/{len(texts)}  {time.time() - t0:.0f}s", flush=True)
    return np.stack(acts), logps


def collect(model: str, sets: dict) -> dict:
    cache = HERE / "cache" / f"{model.replace('/', '__')}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        return {k: z[k] for k in z.files}
    from capture import Capture

    cap = Capture(model)
    layers = sorted(set(range(0, cap.n_layers, 2)) | {cap.n_layers - 1})
    out: dict = {"layers": np.array(layers)}
    texts = {
        "train": [s for s, _ in sets["train"]],
        "dev": [s for s, _ in sets["dev"]],
        "en": [sets["en"][i] for i in sets["idx"]],
        "clean": [sets["es"][i] for i in sets["idx"]],
    }
    for name, items in sets["pairs"].items():
        texts[f"bad_{name}"] = [bad for _, bad in items]
    for key, items in texts.items():
        acts, logps = encode(cap, items, layers, key)
        out[f"{key}_acts"] = acts
        out[f"{key}_meanlp"] = np.array([lp.mean() if len(lp) else 0.0 for lp in logps])
        out[f"{key}_minlp"] = np.array([lp.min() if len(lp) else 0.0 for lp in logps])
    cache.parent.mkdir(exist_ok=True)
    np.savez_compressed(cache, **out)
    return out


# --- tools ----------------------------------------------------------------------


def fit_probe(X: np.ndarray, y: np.ndarray, k: int = 128, steps: int = 500, lr: float = 0.5, l2: float = 1e-2):
    """Logistic regression on PCA-k features; returns a scorer (higher = grammatical)."""
    X = X.astype(np.float32)
    mu = X.mean(0)
    _, _, Vt = np.linalg.svd(X - mu, full_matrices=False)
    P = Vt[:k].T
    A = (X - mu) @ P
    s = A.std(0) + 1e-6
    A /= s
    w, b = np.zeros(A.shape[1]), 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(A @ w + b)))
        g = p - y
        w -= lr * (A.T @ g / len(A) + l2 * w)
        b -= lr * g.mean()
    return lambda Z: (((Z.astype(np.float32) - mu) @ P) / s) @ w + b


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """P(score of a random positive > score of a random negative)."""
    pos, neg = scores[labels == 1], scores[labels == 0]
    return float((pos[:, None] > neg[None]).mean() + 0.5 * (pos[:, None] == neg[None]).mean())


def hub_cos(en: np.ndarray, es: np.ndarray, en_mu: np.ndarray, es_mu: np.ndarray) -> np.ndarray:
    a, b = en - en_mu, es - es_mu
    return (a * b).sum(-1) / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mlx-community/Qwen3-4B-Instruct-2507-4bit")
    args = ap.parse_args()

    rng = random.Random(0)
    sets = build_sets(rng)
    d = collect(args.model, sets)
    layers = list(d["layers"])
    ytr = np.array([l for _, l in sets["train"]], dtype=float)
    ydev = np.array([l for _, l in sets["dev"]])

    # EsCoLA dev: surprisal baselines vs a probe at every captured layer
    res: dict = {"model": args.model, "layers": [int(x) for x in layers]}
    res["escola_auc_meanlp"] = auc(d["dev_meanlp"], ydev)
    res["escola_auc_minlp"] = auc(d["dev_minlp"], ydev)
    scorers, res["escola_auc_probe"] = [], []
    for j in range(len(layers)):
        f = fit_probe(d["train_acts"][:, j], ytr)
        scorers.append(f)
        res["escola_auc_probe"].append(auc(f(d["dev_acts"][:, j]), ydev))
    best = int(np.argmax(res["escola_auc_probe"]))  # chosen on EsCoLA dev, not on the pairs
    res["best_probe_layer"] = int(layers[best])

    # Corruption pairs: does each signal rank clean above corrupted?
    hub_j = [j for j, L in enumerate(layers) if HUB[0] <= L <= HUB[1]]
    en_acts = d["en_acts"][:, hub_j].astype(np.float32)
    clean_acts = d["clean_acts"][:, hub_j].astype(np.float32)
    en_mu, es_mu = en_acts.mean(0), clean_acts.mean(0)
    pos = {i: k for k, i in enumerate(sets["idx"])}

    def signals(prefix: str) -> dict[str, np.ndarray]:
        return {
            "surprisal_mean": d[f"{prefix}_meanlp"],
            "surprisal_min": d[f"{prefix}_minlp"],
            "probe": scorers[best](d[f"{prefix}_acts"][:, best]),
        }

    clean_sig = signals("clean")
    clean_sig["hub"] = hub_cos(en_acts, clean_acts, en_mu, es_mu).mean(-1)
    res["pairs"] = {}
    for name, items in sets["pairs"].items():
        rows = [pos[i] for i, _ in items]
        bad = signals(f"bad_{name}")
        bad["hub"] = hub_cos(en_acts[rows], d[f"bad_{name}_acts"][:, hub_j].astype(np.float32), en_mu, es_mu).mean(-1)
        res["pairs"][name] = {"n": len(rows), **{
            # ties count half: a corruption that leaves the score unchanged
            # is undetected, not detected backwards
            sig: float((clean_sig[sig][rows] > bad[sig]).mean() + 0.5 * (clean_sig[sig][rows] == bad[sig]).mean())
            for sig in clean_sig
        }}

    (HERE / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    plot(res)

    print(f"\nEsCoLA dev AUC   surprisal mean {res['escola_auc_meanlp']:.3f}   min {res['escola_auc_minlp']:.3f}   "
          f"probe {max(res['escola_auc_probe']):.3f} (layer {res['best_probe_layer']})")
    print(f"\n{'pairs: clean ranked higher':<28}{'n':>5}{'surp_mean':>11}{'surp_min':>10}{'probe':>8}{'hub':>7}")
    for name, r in res["pairs"].items():
        print(f"  {name:<26}{r['n']:>5}{r['surprisal_mean']:>11.2f}{r['surprisal_min']:>10.2f}{r['probe']:>8.2f}{r['hub']:>7.2f}")


def plot(res: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(13, 4.2))
    ax[0].plot(res["layers"], res["escola_auc_probe"], marker="o", ms=3, label="linear probe on residual")
    ax[0].axhline(res["escola_auc_meanlp"], color="C1", ls="--", label="surprisal (mean log-prob)")
    ax[0].axhline(res["escola_auc_minlp"], color="C2", ls=":", label="surprisal (min log-prob)")
    ax[0].axhline(0.5, color="grey", lw=0.8)
    ax[0].set(xlabel="layer", ylabel="AUC", title="EsCoLA dev: grammatical vs not", ylim=(0.4, 1.0))
    ax[0].legend(fontsize=8)
    names = list(res["pairs"])
    sigs = ["surprisal_mean", "surprisal_min", "probe", "hub"]
    x = np.arange(len(names))
    for k, s in enumerate(sigs):
        ax[1].bar(x + (k - 1.5) * 0.2, [res["pairs"][n][s] for n in names], 0.2, label=s)
    ax[1].axhline(0.5, color="grey", lw=0.8)
    ax[1].set_xticks(x, names, rotation=15)
    ax[1].set(ylabel="clean ranked above corrupted", title="controlled corruptions", ylim=(0, 1.02))
    ax[1].legend(fontsize=8)
    fig.suptitle(res["model"])
    fig.tight_layout()
    fig.savefig(HERE / "quality.png", dpi=120)


if __name__ == "__main__":
    main()
