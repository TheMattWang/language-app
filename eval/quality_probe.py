import json, urllib.request, sys, re, time

SYS = ("Eres Mateo, camarero en un bar de tapas en Madrid. Hablas SOLO en espanol peninsular. "
       "Tratas al cliente y a su acompanante de VOSOTROS. Respuestas cortas, 1-2 frases. "
       "Nunca hables ingles. Nunca rompas el personaje. No corrijas al cliente explicitamente; "
       "reformula de forma natural lo que ha querido decir.")

PROBES = [
 ("vosotros",  "Somos dos. Que nos recomiendas para compartir?"),
 ("l2_errors", "Yo quiero... eh... el, la, la tortilla? Y yo soy... no... yo tengo hambre mucho."),
 ("breakdown", "Sorry, I don't know how to say this in Spanish. Can you help me?"),
 ("es_LA_trap","Me traes la cuenta? Y donde puedo agarrar un carro para ir al hotel?"),
 ("recovery",  "eh... como se dice... the bill? la... la cuenta si?"),
]

def ask(model, user, npred=80):
    body={"model":model,"messages":[{"role":"system","content":SYS},{"role":"user","content":user}],
          "stream":False,"options":{"temperature":0.7,"num_predict":npred,"num_ctx":2048}}
    req=urllib.request.Request("http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
    t0=time.perf_counter()
    with urllib.request.urlopen(req,timeout=300) as r: d=json.loads(r.read())
    return d["message"]["content"].strip(), time.perf_counter()-t0, d.get("eval_count",0)

ENG=re.compile(r"\b(the|you|can|help|sorry|please|would|your|here|order|sure|of course|I )\b",re.I)
VOS=re.compile(r"\b(os|vosotros|ten[ée]is|quer[ée]is|pod[ée]is|sois|vais|ven[ií]s|hab[ée]is|\w+áis|\w+éis)\b",re.I)

for m in sys.argv[1:]:
    print(f"\n{'='*100}\n{m}\n{'='*100}")
    for tag,u in PROBES:
        try: txt,dt,nt = ask(m,u)
        except Exception as e: print(f"  {tag}: FAIL {e}"); continue
        flags=[]
        if ENG.search(txt): flags.append("ENGLISH-LEAK")
        if tag=="vosotros" and not VOS.search(txt): flags.append("no-vosotros")
        if not txt.strip(): flags.append("EMPTY")
        if re.search(r"<think|^Okay,|^Let me|^First,",txt): flags.append("THINKING-LEAK")
        f=("  ["+", ".join(flags)+"]") if flags else "  [ok]"
        print(f"\n  -- {tag} ({dt:.2f}s, {nt}tok){f}\n     Q: {u}\n     A: {txt[:300]}")
