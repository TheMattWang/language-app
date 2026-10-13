"""Layer-drop sweep: which layers does the model's *Spanish* depend on?

    interp/quality/colab_run.sh Qwen/Qwen3-4B-Instruct-2507 L4 colab_layer_sweep.py

Tests the premise behind layer swapping (Bandarkar et al. 2024): language-
specific work sits in the first and last layers, language-neutral work in
the middle. language_geometry found that shape in Qwen3-4B's *geometry*;
this asks whether it holds *causally*. Each layer is skipped in turn (its
input passed straight through, so the residual stream just loses that
block's contribution) and we measure:

  loss     mean next-token loss on the same 300 NTREX sentences in Spanish,
           English, French and German. A Spanish-specific layer raises
           Spanish loss more than English; a Romance-generic one raises
           Spanish and French together.
  judge    surprisal pairwise accuracy on clean-vs-corrupted Spanish
           (gender, verb_number, negation): does the model still notice
           broken Spanish without this layer?

Writes /content/out/colab_layer_sweep__<model>.json after every layer.
"""

from __future__ import annotations

import json
import random
import sys
import time

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

import colab_quality as cq  # corruptions, data fetch, logging

N_SENT = 300
N_PAIRS = 200
LANGS = {"es": "spa", "en": "eng-US", "fr": "fra", "de": "deu"}
PAIR_TYPES = ["gender", "verb_number", "negation"]


@torch.no_grad()
def token_logprobs(model, tok, texts, bs=16):
    """Per-sentence mean log-prob of each actual next token."""
    out = []
    for b in range(0, len(texts), bs):
        enc = tok(texts[b:b + bs], return_tensors="pt", padding=True, truncation=True,
                  max_length=128).to(model.device)
        logits = model(**enc).logits[:, :-1].float()
        lp = torch.log_softmax(logits, -1).gather(-1, enc["input_ids"][:, 1:, None])[..., 0]
        valid = enc["attention_mask"][:, 1:].bool()
        out.append(((lp * valid).sum(1) / valid.sum(1)).cpu())
    return torch.cat(out).numpy()


class Skip:
    """Forward hook that makes one decoder layer return its input unchanged."""

    def __init__(self):
        self.handle = None

    def __call__(self, module, args, kwargs, output):
        h = args[0] if args else kwargs["hidden_states"]
        return (h, *output[1:]) if isinstance(output, tuple) else h

    def on(self, layer):
        self.handle = layer.register_forward_hook(self, with_kwargs=True)

    def off(self):
        if self.handle:
            self.handle.remove()
            self.handle = None


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen3-4B-Instruct-2507"
    path = cq.OUT / f"colab_layer_sweep__{model_id.replace('/', '__')}.json"
    rng = random.Random(cq.SEED)

    sents = {k: cq.fetch(cq.NTREX.format(v)).splitlines()[:N_SENT] for k, v in LANGS.items()}
    es_all = cq.fetch(cq.NTREX.format("spa")).splitlines()
    pairs = {}
    for name in PAIR_TYPES:
        fn = {**cq.FORM, **cq.MEANING}[name]
        items = [(s, b) for s in es_all[N_SENT:] if (b := fn(s, rng)) and b != s]
        pairs[name] = rng.sample(items, min(N_PAIRS, len(items)))

    tok = AutoTokenizer.from_pretrained(model_id)
    tok.padding_side = "right"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype, device_map="cuda").eval()
    layers = model.model.layers
    cq.log(f"[sweep {model_id}] {len(layers)} layers, {dtype}")

    def measure():
        loss = {k: float(-token_logprobs(model, tok, v).mean()) for k, v in sents.items()}
        judge = {}
        for name, items in pairs.items():
            c = token_logprobs(model, tok, [s for s, _ in items])
            b = token_logprobs(model, tok, [x for _, x in items])
            judge[name] = float(((c > b) + 0.5 * (c == b)).mean())
        return {"loss": loss, "judge": judge}

    t0 = time.time()
    res = {"model": model_id, "n_layers": len(layers), "baseline": measure(), "dropped": {}}
    cq.log(f"  baseline {res['baseline']}  ({time.time() - t0:.0f}s)")
    skip = Skip()
    for i, layer in enumerate(layers):
        skip.on(layer)
        try:
            m = measure()
        finally:
            skip.off()
        base = res["baseline"]
        m["delta_loss"] = {k: m["loss"][k] - base["loss"][k] for k in LANGS}
        res["dropped"][i] = m
        path.write_text(json.dumps(res, indent=1))
        d = m["delta_loss"]
        cq.log(f"  drop {i:>2}: dloss es {d['es']:+.3f} en {d['en']:+.3f} fr {d['fr']:+.3f} de {d['de']:+.3f}  "
               + " ".join(f"{k} {v:.2f}" for k, v in m["judge"].items()))
    res["complete"] = True
    path.write_text(json.dumps(res, indent=1))
    cq.log("DONE")


if __name__ == "__main__":
    main()
