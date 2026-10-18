# Feedback on Nebius Token Factory, Sandboxes and NVIDIA models

Running log, kept from day one (required for submission; basis of the Most Valuable Feedback prize).
Each item: what happened, how to reproduce, impact, suggestion. Dates are IST.

## Docs

1. **Structured-output page: Python example does not run** (2026-10-18). On `/ai-models-inference/json`, the Python
   snippet has `response_format={"type": "json_schema" "json_schema": Film.model_json_schema()}` with no comma after
   `"json_schema"` and no comma after the closing brace, so copy-paste gives `SyntaxError`. The cURL example has the
   same missing comma and spells the key **`"response format"`** (space instead of underscore), so even after fixing the
   comma the API would receive an unknown field and return unstructured text, a silent failure.
   *Suggestion:* run doc snippets in CI.
2. **Structured output: which `json_schema` shape is expected?** (2026-10-18). The Python example passes a bare JSON
   Schema as `json_schema`; the "valid JSON schema" example on the same page is the OpenAI wrapper
   `{name, schema, strict}`. The page does not say which one the API requires or whether both work.
   *Suggestion:* state the accepted shape(s) and whether `strict` is enforced. (Our probe tests both; results will be added below.)
3. **Function calling: no model support matrix** (2026-10-18). `/ai-models-inference/function-calling` documents
   `tool_choice` `auto` and a named function, but not which models support tools, whether parallel tool calls are
   supported, or `"required"`/`"none"`. Builders have to probe each model. *Suggestion:* a "Tools" / "Parallel tools"
   column on model cards and in `GET /v1/models?verbose=true`.
4. **Typo**: card title "Strucrured output - Cookbook" on the JSON page.

## Sandboxes (Beta)

5. **Python SDK cannot disable networking** (2026-10-18). Docs recommend running untrusted code with
   `networking.enabled=false`, but `contree-sdk==0.3.6` `Image.run()` has no networking parameter (checked the
   reference page and the installed source: no "network" string anywhere). The official recipe drops to raw REST
   with httpx. *Impact:* every agent that runs LLM-written code, the main Sandboxes use case, has to maintain its own
   REST client. *Suggestion:* `run(..., networking=False)` in the SDK, ideally default-off for disposable runs.
6. **Undocumented capacity** (2026-10-18). CPU count, RAM, upload size and per-operation timeout cap are not on the
   limits page ("exposed in token limits" for timeout only). *Suggestion:* publish defaults per VM so builders can
   size shards without trial and error. (Our probe measures them; numbers will be added below.)
7. **No idempotency key on spawn** (noted from docs, 2026-10-18). A transport error after `POST /v1/instances` leaves
   the outcome unknown; the docs say to reconcile by application ID, but there is nowhere to attach one.
   *Suggestion:* accept a client-supplied idempotency key or label and allow listing operations by it.

## Inference (to be filled by the Phase 0 probe)

- Catalog snapshot, per-model tool-calling and JSON results, streaming TTFT, latency, rate-limit behaviour.

## What worked well

- OpenAI-compatible API: the standard `openai` SDK works with only `base_url` changed.
- Rate-limit docs are unusually clear: dynamic scaling rules, every header listed, including
  `x-ratelimit-over-limit`.
- Every docs page is available as `.md` plus an `llms.txt` index, which made agent-assisted reading fast.
