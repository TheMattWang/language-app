# Peninsular Spanish Linguistic Audit

Reviewed all 189 cards with non-empty `reject` across `data/*.jsonl` (gr: 77, pc: 95, tv: 15, nl: 2).
Sources cited where used: RAE DLE (dle.rae.es), RAE's own X/Twitter usage notes (@RAEinforma), and
general dialectology references on Peninsular regional variation (Galician/Asturian/Canarian Spanish).
Unsourced judgments are marked "my judgment" and are based on ordinary native-speaker usage.

## Question 1 — Cards that reject correct, ordinary Peninsular Spanish

### High confidence (fix these — they punish a correct answer)

1. **pc-092** — rejects `qué lata` (accepts only `qué rollo`) for "what a pain/drag". `dar la lata` / `¡qué lata!` is a very common, everyday Peninsular Spanish expression (documented as Madrid street-Spanish), not a regionalism to avoid. **Fix:** move `qué lata` to `accept`. Confidence: high. Source: multiple Spain-based etymology/usage write-ups (yorokobu.es, palabraspormadrid.blogspot.com).

2. **pc-010** — rejects `apartamento` alongside `departamento` for "the flat/apartment (Spain)". `departamento` is genuinely LatAm, but `apartamento` is standard Peninsular Spanish, used constantly in Spain (real-estate listings, vacation rentals: "apartamento turístico"). It simply implies something smaller/temporary vs. `piso` for a regular home — not a wrong word. **Fix:** move `apartamento` to `accept` (or a secondary-accept tier); keep `departamento` as the region reject. Confidence: high.

3. **tv-048 / tv-090** — reject `caminando` ("is it walkable" / "far to walk"), claiming "andando is Spain default; caminando is LatAm." False as an absolute claim: `caminar`/`caminando` is standard, correct Spanish used throughout Spain (preferred in some regions, e.g. Canarias; `andar` preferred in others, e.g. Andalucía) — it is not a LatAm-only word. **Fix:** accept both `andando` and `caminando`; drop the region framing. Confidence: high.

4. **tv-097** — rejects `tomar una foto` ("could you take a photo of us"), claiming "hacer is Spain; tomar is LatAm." RAE's own account states `hacer`, `tomar`, `sacar`, `tirar`, `echar` are all normal usage with "foto" in Spain; `tomar` is simply more formal, not regionally excluded. **Fix:** accept `tomar una foto`/`puede tomarnos una foto`; reword note to "hacer/sacar are the everyday choice in Spain; tomar is correct but sounds more formal." Confidence: high (RAE-sourced).

5. **pc-020** — rejects `pastel` alongside `torta` for "the cake (Spain)". In Spain, `tarta` and `pastel` are used largely as synonyms for cake (`pastel de cumpleaños`, `pastelería`); `pastel` leans toward an individual portion but is ordinary Peninsular vocabulary. Only `torta` (flatbread/slap in Spain) is a genuine mismatch. **Fix:** add `pastel` to `accept`; keep `torta` rejected. Confidence: medium-high.

### Medium confidence (the underlying rule is real but stated too absolutely)

6. **gr-067, pc-094, pc-095, pc-096, tv-012** — reject the simple preterite (`hoy comí`, `esta mañana fui...`, `lo viste`, `mi maleta no ha llegado` vs. `llegó`) for hodiernal/recent-past statements, framed as "Spain uses present perfect, LatAm uses preterite." This is the correct *prestige/Madrid-Castilian norm* and a safe default to teach, but the "en España no se dice" framing overstates it: Galician-, Asturian-, León-, and Canarian-influenced Spanish (i.e., large parts of Spain itself) regularly use the simple preterite for today/recent events, the same pattern as most of Latin America. So `hoy comí` genuinely is said in Spain, just not in the Madrid/central standard the deck is teaching. **Recommendation:** soften wording (e.g., "en el español estándar de España se prefiere..." rather than "no se dice"), or keep the reject as a pedagogical simplification but note the regional caveat. Confidence: medium (dialectology-sourced, not a flat error).

## Question 2 — `why:` category correctness / miscategorization

- **pc-062** — tagged `why:register` for the whole card, but the two reject items are different error types: `siéntense` (ustedes imperative) is genuinely a register mismatch; `sentados` is not an imperative at all (it's the past participle/adjective "seated") — that's a `why:form` error, not register. **Fix:** split tags or move `sentados` under a `why:form` framing. Confidence: high.

- **pc-011 / tv-017** — reject `guagua` (and `camión`) tagged `why:region`, framed as not being said "in Spain." `camión` (Mexico) is fair. `guagua`, however, is authentic Spanish spoken in Spain — it's the everyday word for "bus" in the Canary Islands. Given the deck evidently targets mainland/Castilian-standard Spain, keeping it rejected is a defensible simplification, but the "not Spain" framing is technically inaccurate. Confidence: medium, low impact.

- **pc-033** — rejects `el sanitario` (public toilet) tagged `why:meaning` ("ask for los servicios, not el baño"). This is arguably a `why:region` case (sanitario-as-restroom is a Latin American usage) rather than a true false-friend/different-meaning case, since in Spain `sanitario(s)` mainly denotes bathroom fixtures/health staff rather than meaning something unrelated. Low-confidence nuance, not a hard error.

All other `why:region` (money/food/clothing/tech lexicon), `why:register` (vosotros conjugations), `why:meaning` (ser/estar, false friends, preterite/imperfect grammar drills), and `why:form` (subjunctive triggers, clitics, gustar-type verbs, personal a) cards checked out as linguistically sound.
