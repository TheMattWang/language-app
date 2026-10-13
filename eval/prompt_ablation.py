import sys; sys.argv=['x']; from pathlib import Path; ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / 'eval')); sys.path.insert(0, str(ROOT))
import vosotros_rate as v
from drill import llm, probes
OLD = probes.SYSTEM_PROMPTS['es-ES']
NO_LIST = v.RULES.replace(" (queréis, tenéis, os, vuestro)", "")
variants = {"old probe prompt": lambda s: OLD, "new, no form list": lambda s: v.SCENES[s] + NO_LIST, "new, with forms": lambda s: v.SCENES[s] + v.RULES}
def ask(model, msgs):
    for attempt in range(3):
        try: return llm.chat(msgs, model=model, temperature=0.7, max_tokens=80, timeout=180).text
        except llm.LLMUnavailable:
            if attempt == 2: raise
for model in ["qwen2.5:3b", "gemma3:4b", "qwen3:4b-instruct-2507-q8_0"]:
    for name, sysp in variants.items():
        cls = [v.classify(ask(model, [{"role":"system","content":sysp(s)},{"role":"user","content":p}]))
               for s, ps in v.PROMPTS.items() for p in ps]
        n=len(cls); vos=cls.count('vos'); neu=cls.count('neutral')
        print(f"{model:<28} {name:<18} vos {vos/n:4.0%}  neutral {neu/n:4.0%}  vos|addr {vos/max(1,n-neu):4.0%}", flush=True)
