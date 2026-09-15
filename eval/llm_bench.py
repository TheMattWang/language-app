import json, time, urllib.request, statistics, sys

SYS = ("Eres Mateo, camarero en un bar de tapas en Madrid. Hablas SOLO en espanol "
       "peninsular (vosotros, distincion). Respuestas cortas y naturales, 1-2 frases, "
       "como habla un camarero de verdad. Nunca rompas el personaje ni traduzcas al ingles.")

# ~8 turns of prior context: realistic mid-scenario state, not a cold one-shot
HIST = [
 ("Hola, buenas.", "Buenas! Que os pongo?"),
 ("Una cana, por favor.", "Marchando una cana. Algo de comer?"),
 ("Que tapas teneis hoy?", "Hoy tenemos tortilla, croquetas de jamon y boquerones en vinagre."),
 ("Como son las croquetas?", "Caseras, de jamon iberico. Salen muy buenas, la verdad."),
 ("Vale, ponme unas croquetas.", "Perfecto. Una racion o media?"),
 ("Media esta bien.", "Media racion de croquetas. Algo mas?"),
 ("No, de momento nada mas.", "Estupendo, ahora mismo os lo saco."),
]
USER_TURN = "Perdona, al final me puedes poner tambien una racion de tortilla?"

def build(model):
    msgs=[{"role":"system","content":SYS}]
    for u,a in HIST:
        msgs.append({"role":"user","content":u}); msgs.append({"role":"assistant","content":a})
    msgs.append({"role":"user","content":USER_TURN})
    return {"model":model,"messages":msgs,"stream":False,
            "options":{"temperature":0.7,"num_predict":60,"num_ctx":2048}}

def run(model):
    req=urllib.request.Request("http://127.0.0.1:11434/api/chat",
        data=json.dumps(build(model)).encode(), headers={"Content-Type":"application/json"})
    t0=time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r: d=json.loads(r.read())
    wall=time.perf_counter()-t0
    ns=1e9
    return {
      "load_s": d.get("load_duration",0)/ns,
      "prefill_s": d.get("prompt_eval_duration",0)/ns,
      "prompt_tok": d.get("prompt_eval_count",0),
      "decode_s": d.get("eval_duration",0)/ns,
      "out_tok": d.get("eval_count",0),
      "wall_s": wall,
      "text": d["message"]["content"].strip().replace("\n"," ")[:220],
    }

models = sys.argv[1:]
print(f"{'model':<18}{'TTFT_s':>8}{'tok/s':>8}{'out':>5}{'gen_s':>8}{'wall_s':>8}   reply")
print("-"*130)
rows={}
for m in models:
    try:
        run(m)  # warm: load weights, discard
        runs=[run(m) for _ in range(3)]
    except Exception as e:
        print(f"{m:<18}  FAILED: {e}"); continue
    ttft = statistics.median(r["prefill_s"] for r in runs)
    tps  = statistics.median((r["out_tok"]/r["decode_s"]) if r["decode_s"]>0 else 0 for r in runs)
    out  = statistics.median(r["out_tok"] for r in runs)
    gen  = statistics.median(r["decode_s"] for r in runs)
    wall = statistics.median(r["wall_s"] for r in runs)
    rows[m]=dict(ttft=ttft,tps=tps,out=out,gen=gen,wall=wall,
                 ptok=runs[0]["prompt_tok"],text=runs[-1]["text"])
    print(f"{m:<18}{ttft:>8.3f}{tps:>8.1f}{out:>5.0f}{gen:>8.2f}{wall:>8.2f}   {runs[-1]['text'][:70]}")
print()
json.dump(rows, open("/private/tmp/claude-501/-Users-mattwang-dev-language-app/26b05c64-58c9-47f9-90f3-3651fc59f211/scratchpad/bench/llm_results.json","w"), indent=1)
for m,r in rows.items():
    print(f"== {m}  (prompt {r['ptok']} tok)\n   {r['text']}\n")
