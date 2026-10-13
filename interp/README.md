# interp/ — looking inside the local model

Experiments that open up the local model drill runs (residual stream,
probes, steering) to answer product questions. They follow the loop from
the interp-topology track: understand what the model does, then optimize
the part that carries the weight. Results feed `research/` and `drill/`.

| Dir | Question | Status |
|---|---|---|
| `language_geometry/` | Where does the model keep *which language* vs *what it means*? Is Spain vs Latin America a feature? | probes run on Qwen3-4B, causal half open |
| `quality/` | Does the model know when its Spanish is wrong? Surprisal vs a linear probe vs cross-lingual alignment | run on Qwen3-4B: surprisal ranks form errors, the hub check catches meaning errors |

Setup (Apple Silicon; MLX):

    python3 -m venv .venv && .venv/bin/pip install -e '.[interp]'
    interp/fetch_data.sh                       # NTREX-128, CC-BY-SA-4.0
    # EsCoLA (CC-BY-NC-SA-4.0, research only -- never train a shipped model on it):
    for f in EsCoLA_InDomainTrain.tsv EsCoLA_InDomainDev.tsv; do
      curl -sfL -o interp/data/$f https://huggingface.co/datasets/nbel/EsCoLA/resolve/main/$f; done

Corpora and activation caches are git-ignored. Runs over ~15 minutes belong
on Colab (use the HF weights and torch forward hooks there; MLX is Mac-only).
