"""Lab 06 -- where does a model keep *which language* it's in?

Worked first pass. Run (from repo root):  .venv/bin/python interp/language_geometry/language_geometry.py [--model REPO] [--n 150]

Measures, per layer of the residual stream:
  A. language identity  -- linear probe over 15 languages (held-out sentences)
  B. meaning alignment  -- translation retrieval: is a sentence's nearest
                           neighbour in another language its own translation?
  C. language share     -- fraction of variance explained by language centroids
  D. variety            -- Spain vs Latin American Spanish on minimal pairs,
                           probe tested on held-out *words*
  E. shared variety axis (exploratory) -- does the Spain-vs-LatAm direction
                           also separate pt vs pt-BR, fr vs fr-CA, en-GB vs en-US?

The expected picture (Wendler et al. 2024, "Do Llamas Work in English?";
Tang et al. 2024 language-specific neurons): language identity is high at
the edges, meaning converges in the middle. Whether *variety* behaves like
a small language or like a style is the open question this lab asks.
Saves activations to cache/, results.json and language_geometry.png.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from pairs import pairs

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
LANGS = ["eng-US", "spa", "por", "fra", "deu", "ita", "rus", "zho-CN", "jpn", "arb", "hin", "kor", "tur", "vie", "swa"]
VARIANT_PAIRS = [("spa", "spa-MX"), ("por", "por-BR"), ("fra", "fra-CA"), ("eng-GB", "eng-US")]  # (Europe, Americas)


def ntrex(lang: str, n: int) -> list[str]:
    return (DATA / f"newstest2019-ref.{lang}.txt").read_text(encoding="utf-8").splitlines()[:n]


def collect(model: str, n: int) -> dict[str, np.ndarray]:
    """Mean-pooled residual stream [n_sentences, n_layers, d] per dataset, cached."""
    cache = HERE / "cache" / f"{model.replace('/', '__')}_n{n}.npz"
    if cache.exists():
        return dict(np.load(cache))
    from capture import Capture

    cap = Capture(model)
    out: dict[str, np.ndarray] = {}
    langs = sorted(set(LANGS) | {l for p in VARIANT_PAIRS for l in p})
    t0 = time.time()
    for lang in langs:
        out[lang] = np.stack([cap.mean_pooled(s) for s in ntrex(lang, n)])
        print(f"  {lang:<7} {time.time() - t0:6.0f}s")
    ps = pairs()
    out["pairs_spain"] = np.stack([cap.mean_pooled(p["spain"]) for p in ps])
    out["pairs_latam"] = np.stack([cap.mean_pooled(p["latam"]) for p in ps])
    cache.parent.mkdir(exist_ok=True)
    np.savez_compressed(cache, **out)
    return out


# --- tools (the fundamentals, kept small enough to read) ---------------------


def pca_fit(X: np.ndarray, k: int):
    """Center + project onto the top-k principal directions (fit on train only)."""
    mu = X.mean(0)
    _, _, Vt = np.linalg.svd(X - mu, full_matrices=False)
    return lambda Z: (Z - mu) @ Vt[:k].T


def probe(Xtr, ytr, Xte, yte, k=128, steps=400, lr=0.5, l2=1e-3) -> float:
    """Multinomial logistic regression on PCA-k features; held-out accuracy.

    Linear on purpose: a linear probe that works means the information is
    *readable by a single direction*, which is what the model itself can use.
    """
    proj = pca_fit(Xtr, min(k, len(Xtr) - 1))
    A, B = proj(Xtr), proj(Xte)
    s = A.std(0) + 1e-6
    A, B = A / s, B / s
    classes = np.unique(ytr)
    Y = (ytr[:, None] == classes[None]).astype(float)
    W = np.zeros((A.shape[1], len(classes)))
    b = np.zeros(len(classes))
    for _ in range(steps):
        Z = A @ W + b
        Z -= Z.max(1, keepdims=True)
        P = np.exp(Z)
        P /= P.sum(1, keepdims=True)
        G = (P - Y) / len(A)
        W -= lr * (A.T @ G + l2 * W)
        b -= lr * G.sum(0)
    return float((classes[(B @ W + b).argmax(1)] == yte).mean())


def retrieval(src: np.ndarray, tgt: np.ndarray) -> float:
    """Top-1 translation retrieval by cosine, after removing each language's mean.

    Centering matters: without it the language identity component dominates
    every cosine and all Spanish sentences look closer to each other than to
    their own English source.
    """
    a = src - src.mean(0)
    b = tgt - tgt.mean(0)
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    return float(((a @ b.T).argmax(1) == np.arange(len(a))).mean())


def between_share(groups: list[np.ndarray]) -> float:
    """Between-group variance / total variance (an R^2 for 'which language')."""
    allx = np.concatenate(groups)
    mu = allx.mean(0)
    total = ((allx - mu) ** 2).sum()
    between = sum(len(g) * ((g.mean(0) - mu) ** 2).sum() for g in groups)
    return float(between / total)


# --- the experiment ----------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mlx-community/Qwen3-4B-Instruct-2507-4bit")
    ap.add_argument("--n", type=int, default=150)
    args = ap.parse_args()

    acts = collect(args.model, args.n)
    n_layers = acts["spa"].shape[1]
    n_train = int(args.n * 2 / 3)
    ps = pairs()
    items = np.array([p["item"] for p in ps])
    kinds = np.array([p["kind"] for p in ps])
    uniq = sorted(set(items))
    rng = np.random.default_rng(0)
    test_items = set(rng.choice(uniq, size=len(uniq) // 3, replace=False))
    is_test = np.array([i in test_items for i in items])

    res = {k: [] for k in ("lang_probe", "retrieval", "between_share", "variety_probe",
                           "variety_probe_lexical", "variety_probe_address", "variety_cos_lex_addr")}
    for L in range(n_layers):
        X = np.concatenate([acts[l][:, L] for l in LANGS])
        y = np.repeat(np.arange(len(LANGS)), args.n)
        idx = np.tile(np.arange(args.n), len(LANGS))
        res["lang_probe"].append(probe(X[idx < n_train], y[idx < n_train], X[idx >= n_train], y[idx >= n_train]))
        res["retrieval"].append(float(np.mean([retrieval(acts["eng-US"][:, L], acts[l][:, L]) for l in LANGS[1:]])))
        res["between_share"].append(between_share([acts[l][:, L] for l in LANGS]))

        S, A = acts["pairs_spain"][:, L], acts["pairs_latam"][:, L]
        V = np.concatenate([S, A])
        vy = np.r_[np.zeros(len(S)), np.ones(len(A))]
        vt, vk = np.r_[is_test, is_test], np.r_[kinds, kinds]
        res["variety_probe"].append(probe(V[~vt], vy[~vt], V[vt], vy[vt], k=32))
        for kind in ("lexical", "address"):
            tr, te = ~vt & (vk == kind), vt & (vk == kind)
            res[f"variety_probe_{kind}"].append(probe(V[tr], vy[tr], V[te], vy[te], k=16))
        # Are "Spain vocabulary" and "vosotros" the same direction?
        d = {kind: (S[kinds == kind] - A[kinds == kind]).mean(0) for kind in ("lexical", "address")}
        res["variety_cos_lex_addr"].append(float(
            d["lexical"] @ d["address"] / (np.linalg.norm(d["lexical"]) * np.linalg.norm(d["address"]))))

    # E. exploratory: project NTREX variant pairs on the Spanish variety direction
    best = int(np.argmax(res["variety_probe"]))
    direction = (acts["pairs_spain"][:, best] - acts["pairs_latam"][:, best]).mean(0)
    direction /= np.linalg.norm(direction)
    shared = {}
    for eu, am in VARIANT_PAIRS:
        diff = (acts[eu][:, best] - acts[am][:, best]) @ direction
        shared[f"{eu} vs {am}"] = {"mean_proj": float(diff.mean()), "frac_positive": float((diff > 0).mean())}

    out = {"model": args.model, "n": args.n, "n_layers": n_layers, "best_variety_layer": best,
           "held_out_items": sorted(test_items), "shared_variety_axis": shared, **res}
    (HERE / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    plot(out)

    peak = lambda k: (int(np.argmax(res[k])), max(res[k]))
    print(f"\nlanguage probe:   min {min(res['lang_probe']):.2f} (layer {int(np.argmin(res['lang_probe']))}), "
          f"max {max(res['lang_probe']):.2f}")
    print(f"retrieval en->X:  peak {peak('retrieval')[1]:.2f} at layer {peak('retrieval')[0]}")
    print(f"language share:   layer 0 {res['between_share'][0]:.2f}, min {min(res['between_share']):.2f} "
          f"(layer {int(np.argmin(res['between_share']))}), last {res['between_share'][-1]:.2f}")
    print(f"variety probe:    peak {peak('variety_probe')[1]:.2f} at layer {best} "
          f"(lexical {max(res['variety_probe_lexical']):.2f}, address {max(res['variety_probe_address']):.2f})")
    print(f"lex/address cos:  at layer {best}: {res['variety_cos_lex_addr'][best]:+.2f}")
    for k, v in shared.items():
        print(f"shared axis {k:<18} Europe-side projects higher in {v['frac_positive']:.0%} of sentences")


def plot(out: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    layers = np.arange(out["n_layers"])
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    ax[0].plot(layers, out["lang_probe"], label="language ID probe (15 langs)")
    ax[0].plot(layers, out["retrieval"], label="translation retrieval en→X")
    ax[0].set_title("A/B. which language vs what it means")
    ax[1].plot(layers, out["between_share"], color="C2")
    ax[1].set_title("C. variance explained by language")
    ax[2].plot(layers, out["variety_probe"], label="variety (all, held-out words)")
    ax[2].plot(layers, out["variety_probe_lexical"], label="lexical only", ls="--")
    ax[2].plot(layers, out["variety_probe_address"], label="vosotros/ustedes only", ls="--")
    ax[2].axhline(0.5, color="grey", lw=0.8)
    ax[2].set_title("D. Spain vs Latin America")
    for a in ax:
        a.set_xlabel("layer")
        a.set_ylim(0, 1.02)
    ax[0].legend(fontsize=8)
    ax[2].legend(fontsize=8)
    fig.suptitle(out["model"])
    fig.tight_layout()
    fig.savefig(HERE / "language_geometry.png", dpi=120)


if __name__ == "__main__":
    main()
