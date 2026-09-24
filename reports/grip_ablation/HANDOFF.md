# HHGOA GRIP integration handoff

Updated: 2026-09-25 (Asia/Kolkata)

The GRIP experiment and static action-consistency fix are complete. The static TigerGraph path remains the default. Do not use public IEEE-CIS/Kaggle `isFraud` labels to infer any case outcome; HHGOA intentionally removed them.

## Current status

- Phase 0: saved the 20 original static answer files under `reports/grip_ablation/static_baseline/`. `BASELINE.txt` records the prior 16-passed result.
- Phase 1: GRIP 0.5.0 is configured for existing TigerGraph `HHGOA`. The saved pre-benchmark status in `phase1_raw_tools.json` identifies `backend=tigergraph`, graph `HHGOA`, version `release_4.2.5_08-26-2026`, 633,412 vertices and 1,758,428 edges. Its file timestamp is 2026-09-24 23:34:57 local; there is no probe timestamped immediately before the benchmark. The new post-benchmark probe in `live_status_after_benchmark.json` confirms TigerGraph/HHGOA with 648,353 vertices, 1,786,304 edges, 12 vertex types and 15 edge types. The GRIP launcher is fail-closed on a non-TigerGraph health check and has no demo adapter.
- Phase 2: complete. Live HHGOA has 5,570 GRIP `Paper` documents: 4 fraud-policy chunks, 1 fraud-pattern chunk, 5,565 closed-case text documents, and no regulatory documents present locally. The public transaction rows were not embedded.
- Embeddings: complete and verified. Cloudflare Workers AI `@cf/baai/bge-base-en-v1.5`, 768 dimensions; live TigerGraph counts reconciled to `Paper=5570`, `PaperEmb=5570`. See `ingest_report.json` and `embedding_report.json`.
- Additive schema now has 12 vertex types / 15 edge types: original 8/13 plus `Paper`, `Author`, `Concept`, `PaperEmb`, `AUTHORED_BY`, and `MENTIONS`. Author count is 0; frequency extraction populated Concepts. Original HHGOA transaction graph data was not cleared or rewritten.
- GRIP vector and graph retrieval works after all four GRIP retrieval queries were explicitly reinstalled together. `tg_vector_search` initially returned `REST-1005` (“Query endpoint ... is disabled”); after `INSTALL QUERY -FORCE tg_concept_members, tg_local_search, tg_top_concepts, tg_vector_search`, all four endpoints were enabled and direct vector search returned PaperEmb matches.
- Phase 3: code is wired behind `GRAPHRAG_MODE=grip`; default remains `static`. Static local policy/pattern context is retained. GRIP retrieval is appended, capped, and cached across investigation rounds. Closed-case heuristic matches are semantically reranked through `graphrag_batch_similarity` when present.
- Phase 4/5: all 20 GRIP cases ran sequentially and were compared with archived static answers. Same-session static controls exist for HHG-001, 003, 004, 005, 009, 012, 013, 014, 015, 016, 017, and 019. Full comparison is in `comparison_report.md`. Per-case GRIP responses are not persisted; `assemble_context` can fall back to static context on a GRIP tool error, so individual retrieval success is not audit-proven.
- Static submission validation: current `cases/` passed `scripts/validate_tigergraph_answers.py` 20/20 after fixes; answer schema, graph-known IDs, graph-write markers, and live Transaction count (590,742) passed. The new action-language audit found no mismatches in current `cases/`.
- Historical GRIP/static-control audit: the new check finds stale mismatches in HHG-004, HHG-014, and HHG-016 in pre-fix saved outputs. Those experiment files remain preserved. Repository-wide `python -m pytest -q -p no:cacheprovider` passes 24 tests.
- Renamed the live Cloudflare embedding smoke script to `scripts/smoke_grip_embedding_api.py`, so pytest no longer runs network code during collection.
- The separate `scripts/run_cases_nvidia_cloudflare.py` uses Groq → NVIDIA NIM → Cloudflare Workers AI without changing `src/llm.py`. The static submission runner remains `scripts/run_cases_groq.py` (Groq → OpenRouter). HHG-004, HHG-014, and HHG-016 were regenerated into `cases/` through the static runner after the fix. Per-call provider identity is not stored in answer JSON.
- Root cause fix: graph hints previously treated lone new-device/CNP and out-of-region anomalies as corroboration, suppressing R1. TigerGraph and CSV hint derivation now keep these as single weak signals; the LLM cannot override the graph-derived R1 gate. Summaries now use the policy action allowlist and avoid inventing actions when the final list is empty. `validate.py` flags action-like summary/SAR prose when final actions are empty.
- Static remains the default. Comparisons are mixed, with pattern and outcome changes; GRIP has not demonstrated a consistent improvement over static.
- No Python process is currently running.

## Live retrieval behavior and chosen weights

Installed `tigergraph-mcp`/GRIP source was inspected. The adapter does **not** use Reciprocal Rank Fusion: `RetrievalContract` normalizes the weights, then the TigerGraph adapter scales graph relevance and vector cosine scores, takes the maximum score for duplicate IDs, and sorts by the resulting score.

Weight probe results are in `hybrid_weight_probe.json`. On card-testing, shared-origin, and customer-denial prompts, 0.7 vector / 0.3 graph reliably returned the relevant policy/pattern documents. 0.8/0.2 returned the same top five IDs in these probes, so 0.7/0.3 was selected to retain more graph contribution. GRIP formatter benchmark is in `format_benchmark.json`; app integration currently uses top_k=6 and max_tokens=350.

## Case comparisons so far

Compare archived answers with care: Groq output varied between runs, and the archived baseline predates the new Groq key. Same-session static controls are available for HHG-017 and HHG-003.

| Case | Archived static | Current static control | GRIP (current compact path) | Note |
|---|---|---|---|---|
| HHG-017 | uncertain / none / p=0.20 | uncertain / none / p=0.28; 8,367 tokens, 36.17s | uncertain / none / p=0.28; 12,950 tokens, 109.19s | Current static and GRIP agree on verdict, pattern, probability, and actions. Initial uncapped GRIP run (preserved as `grip_cases/HHG-017_initial.json`) took 169.15s / 19,737 tokens; compacted run improved that. |
| HHG-003 | legitimate / none / p=0.10 | uncertain / none / p=0.28; 19,903 tokens, 125.45s | uncertain / out_of_region_use / p=0.28; 13,656 tokens, 107.06s | Current controls agree on verdict/probability/status/actions; GRIP changed the pattern. Static control and GRIP both used the refreshed Groq key. |
| HHG-006 | fraud / card_not_present_new_device / p=0.74; 9,364 tokens, 50.23s | not run | fraud / account_takeover / p=0.74; 11,437 tokens, 77.79s | Verdict/probability/status/actions match archived static; pattern differs. |
| HHG-012 | legitimate / none / p=0.10; 10,014 tokens, 17.59s | uncertain / none / p=0.28; 17,499 tokens, 128.28s | uncertain / none / p=0.28; 13,018 tokens, 95.01s | Same-session static and GRIP agree on verdict, pattern, probability, status, and actions. Archived static differed due provider/run variance. |

Additional completed cases are recorded in `comparison_report.md`, including HHG-007 through HHG-020. Notable historical same-session results: HHG-013 static/GRIP both fraud/account_takeover with the same actions (p=.72/.74); pre-fix HHG-014/016 artifacts had empty actions paired with action-recommending prose; HHG-015 exact same-session output; HHG-019 differs in pattern between same-session static and GRIP. The current submission outputs are detailed in `final_static_cases_report.md`.

Comparison caveat: HHG-004 is a same-session material outcome difference (static open/uncertain/.68 vs GRIP closed_fraud/fraud/.82); HHG-019 has a GRIP-specific pattern change. Static remains default. The three historical empty-action mismatches are detected by the new validator and no longer occur in current submission outputs.

Important preserved failure: the first unbounded GRIP run on HHG-003 received Groq HTTP 413: `Limit 7000, Requested 8116`; OpenRouter fallback received HTTP 429 (`qwen/qwen3.8-27b:free is temporarily rate-limited upstream`). The run fell back to graph heuristics and changed the answer. It is saved at `grip_cases/HHG-003_failed_provider_fallback.json`. Prompt caps were subsequently reduced. Do not treat that file as a valid GRIP model result.

The user updated the Groq API key in `.env`; do not print it. `scripts/smoke_llm_providers.py groq` passed 2/2 small JSON/prose prompts with the refreshed key. Current provider preference is Groq, with configured OpenRouter free-model fallback. Long full-context calls may still hit rate/latency limits; report exact errors.

## Important implementation/source findings

- `scripts/grip_mcp_server.py` forces a real TigerGraph adapter and supplies a Cloudflare embedding function; it never accepts GRIP's demo fallback. It also preserves the adapter's vector/keyword note in the MCP response because GRIP 0.5.0's normalization drops that diagnostic.
- `scripts/grip_ingest_corpus.py` calls GRIP's actual `graphrag_ingest` MCP tool in 50-document batches. A resumable bulk-upsert patch in the custom MCP launcher was needed for runtime. The first failed batch created four policy Papers; later code validates and upserts those idempotently. Do not clear the graph.
- TigerGraph `getVertexCount` lagged acknowledged upserts. Final later live reads returned exactly 5,570 Papers and 5,570 PaperEmb vectors. This lag is documented in `embedding_report.json`.
- Author/Concept primary IDs are configured with `PRIMARY_ID_AS_ATTRIBUTE="true"`. pyTigerGraph exposes this under `PrimaryId.PrimaryIdAsAttribute`, not in the ordinary `Attributes` array.
- `src/grip_client.py` was fixed to enter and exit MCP async contexts on the same loop task; preserve that shutdown fix.

## Files changed/added for this experiment

- Core: `src/config.py`, `src/graphrag.py`, `src/orchestrator.py`, `src/grip_client.py`.
- Schema: `schema/grip_corpus_schema.gsql`, `schema/grip_fix_entity_schema.gsql`.
- Runners/tools: `scripts/grip_probe.py`, `scripts/prepare_grip_corpus.py`, `scripts/apply_grip_schema.py`, `scripts/fix_grip_entity_schema.py`, `scripts/grip_mcp_server.py`, `scripts/grip_ingest_corpus.py`, `scripts/grip_embed_corpus.py`, `scripts/grip_hybrid_probe.py`, `scripts/benchmark_grip_format.py`, `scripts/run_grip_case.py`, `scripts/smoke_grip_embedding_api.py`, `scripts/summarize_grip_ablation.py`, `scripts/summarize_submission_cases.py`, `scripts/audit_empty_action_language.py`.
- Data: `data/grip_corpus/documents.jsonl`.
- Reports: this directory.

There are other uncommitted workspace files (including `Jevelric.zip`, `create_zip_v2.ps1`, and `web/`) that are outside this GRIP handoff; inspect before changing or committing them.

## Next actions, in order

1. Keep `GRAPHRAG_MODE=static` as the default; GRIP results are mixed and per-case retrieval response metadata was not persisted.
2. The action/prose issue is fixed in code and current static outputs; the full static set passes the added validator check.
3. For any future GRIP benchmark, persist graph ID, retrieval note, result count, provider, and fallback errors per case so static fallback cannot be mistaken for successful GRIP retrieval.
4. Continue the remaining UI, semantic-review, demo, and blog tasks.

## Resume command

From `D:\JEVelric`, after ensuring the refreshed `.env` remains present:

```powershell
.venv\Scripts\python.exe scripts\run_grip_case.py HHG-001 grip
```

The runner writes to `reports/grip_ablation/grip_cases/` and does not overwrite `cases/` or the archived static baseline. If network access is denied by the current execution sandbox, request the normal escalated permission for this specific runner; do not print credentials. Start the next session by reading this file and checking `git status --short`.
