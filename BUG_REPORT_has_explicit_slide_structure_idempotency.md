# Bug report: `has_explicit_slide_structure` silently returns wrong result on a repeat stream call

**Status:** Root-caused, reproduced on demand, not fixed (out of scope for the reporting session — this
came from investigating a chat-integration feature in the sibling `GenAI-Workspace-Dev` repo, not from
work on this codebase).

**Severity:** High for any workflow that relies on explicit-structure preservation (pasted/uploaded
outlines with `Slide N:` markers). Silent — no error, no log warning, still returns `200 OK` with a
plausible-looking outline. A user has no way to know their outline's structure was not preserved.

**One-line summary:** The very first successful call to `GET /api/v1/ppt/outlines/stream/{id}` for a
given presentation permanently and silently disables explicit-structure detection for every subsequent
call to that same `{id}`, because the first call's own side effect (backfilling `n_slides` from `0` to
the real slide count) changes which code branch the *next* call takes.

---

## Repro (under 2 minutes, no auth needed beyond the existing dev bypass key)

```bash
BASE=http://localhost:5001
KEY="dev-local-placeholder-key"   # or your real sk-presenton-* key

# 1. Create a presentation with an explicit-structure outline, n_slides OMITTED.
curl -s -X POST "$BASE/api/v1/ppt/presentation/create" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" \
  -d '{
    "content": "Slide 1: Overview\nA brief summary of the topic.\nSlide 2: Next Steps\nWhat we plan to do next.\n",
    "language": "English", "generation_mode": "smart", "smart_template": "eand",
    "include_title_slide": true
  }' | python3 -c "import json,sys; d=json.load(sys.stdin); print('id:', d['id']); print('n_slides at create:', d['n_slides'])"
# -> n_slides at create: 0   (correct precondition for explicit-structure detection)

PID=<paste the id from above>

# 2. Stream the outline ONCE. Wait for the "complete" event.
curl -sN --max-time 60 "$BASE/api/v1/ppt/outlines/stream/$PID" | grep -o '"has_explicit_slide_structure":[a-z]*'
# -> has_explicit_slide_structure:true   (correct - the content has 2 clean "Slide N:" markers)

# 3. Stream the SAME id a SECOND time. No change to the presentation in between.
curl -sN --max-time 60 "$BASE/api/v1/ppt/outlines/stream/$PID" | grep -o '"has_explicit_slide_structure":[a-z]*'
# -> has_explicit_slide_structure:false  <-- BUG. Same content, same id, wrong answer.
```

I ran this exact 3-step sequence directly (not through any orchestrator/chat integration) against the
real running `ai-presentation-studio-development-1` dev container and got exactly this result:
step 2 returned `true`, step 3 (same presentation, no other change) returned `false`.

## Root cause

`api/v1/ppt/endpoints/outlines.py`, `stream_outlines()`:

```python
has_explicit_slide_structure = False
if presentation.n_slides > 0:
    n_slides_to_generate = get_no_of_outlines_to_generate_for_n_slides(...)
else:
    detected_content_slides = detect_explicit_slide_count(presentation.content)
    if detected_content_slides is not None:
        has_explicit_slide_structure = True
        ...
```

and, at the end of the same function, after generation completes:

```python
if presentation.n_slides <= 0:
    presentation.n_slides = len(presentation_outlines.slides)
...
sql_session.add(presentation)
await sql_session.commit()
```

`detect_explicit_slide_count()` only ever runs in the `else` branch — i.e. only when
`presentation.n_slides` is still `0`. But the **first successful call** to this endpoint commits a
non-zero `n_slides` back to the row as its very last step. Since `stream_outlines()` re-fetches
`presentation` fresh from the DB on every call (`sql_session.get(PresentationModel, id)`, line ~91), the
**second call sees `n_slides > 0`** (left behind by the first call) and takes the *other* branch —
`detect_explicit_slide_count()` is never even called, so `has_explicit_slide_structure` stays at its
initialized default, `False`.

This is not randomness. It is a fully deterministic idempotency bug: **the endpoint's own state mutation
on success changes the behavior of the next call to the same endpoint.** The first call is always
correct (assuming detection would fire); every call after it, for the same `id`, is always wrong (until
someone resets `n_slides` back to `0` in the DB, which nothing does).

`detect_explicit_slide_count()` and its regex (`utils/outline_utils.py`) were checked directly and are
not the problem — called in isolation against the exact stored `content` for a presentation stuck on
the "false" branch, it correctly returns the real count every time. The bug is entirely in
`stream_outlines()`'s branch ordering, not in the detection logic itself.

## Why this matters in real usage, not just in a test harness

This codebase's **own frontend already has an automatic retry mechanism that reissues this exact
request against the same `id`**:
`app/(presentation-generator)/outline/hooks/useOutlineStreaming.ts`:

```js
const MAX_STREAM_RETRIES = 3;
...
eventSource.onerror = () => {
  if (!scheduleRetry("connection lost")) { ... }
};
```

`scheduleRetry` closes the current `EventSource` and reopens a new one against the identical
`/api/v1/ppt/outlines/stream/{presentationId}` URL, up to 3 times, on **any** connection drop —
`onerror` fires on ordinary network hiccups, a proxy/gateway idle-connection timeout during the
(sometimes many-seconds-long, real-LLM, high-reasoning-effort) outline generation, a backgrounded
browser tab, etc. Nothing in `stream_outlines()`'s own code guarantees the server-side generation for
a *dropped* first attempt actually aborts before it reaches the `n_slides` backfill/commit — if it
doesn't (and I did not find evidence in this codebase that it reliably does — see "Open question"
below), then the retry the user actually sees inherits the first attempt's now-flipped `n_slides`, and
silently gets the non-structure-preserving path with no error shown anywhere.

**Concretely: any real user who pastes or uploads a "Slide N:"-structured outline, and whose outline
page's SSE connection drops even once during generation (very plausible for a long-running high-
reasoning-effort call, especially on this app's own documented SSE-proxy-buffering-sensitive stack), can
silently lose the explicit-structure preservation Studio's own outline endpoint is supposed to guarantee
for them — with the UI showing nothing wrong.** This is not limited to the chat-integration feature that
surfaced it; it affects `/upload` and `/generation`'s own native paste/outline flows equally, since they
go through the same endpoint.

This does **not** affect a plain worded/topic-only request (no "Slide N:" markers in the content) — that
path never depends on `detect_explicit_slide_count()` in the first place, so there is nothing for this
bug to flip for it.

## Evidence this explains the original "nondeterminism" observation, not just theory

Cross-checked against real container access logs (`docker logs`) for the two original failing runs from
the sibling investigation: **both** presentation IDs that returned `has_explicit_slide_structure: false`
had been hit by `GET /outlines/stream/{id}` **more than once** before or at the point the `false` result
was observed (3 hits and 2 hits respectively). Every one of the 3 direct-curl successes in that same
investigation, and all 46 controlled follow-up runs (single stream call per presentation, varying
content length 2/3/6 sections, sequential vs. 6-way-concurrent, with and without a 3-second delay before
streaming), which never issued more than one stream call per presentation, came back `true` — 0
failures out of 46 when the endpoint is called exactly once, matching the mechanism exactly. Full data:
`GenAI-Workspace-Dev/CLAUDE.md`'s rule-4 entry (search "has_explicit_slide_structure") and this repo's
own `CLAUDE.md` entry for this finding.

## Open question for whoever picks this up (not investigated further — out of scope for the reporting session)

Does `stream_generate_events`'s `disconnect_checker` (threaded through
`utils/llm_calls/generate_presentation_outlines.py`) actually abort the LLM call and skip the
`sql_session.commit()` promptly when the client disconnects mid-stream, or does generation continue to
completion and commit regardless? If it does **not** reliably abort, every one of the frontend's 3
built-in retries is guaranteed to land on the degraded path once the first attempt's generation
eventually finishes in the background — making this considerably more than a rare edge case.

## Suggested fix direction (not implemented — this is diagnosis only)

The underlying assumption that "an `n_slides` of `0` means detection hasn't run yet" is what breaks once
the same request can legitimately be re-issued. A few options, for whoever owns this to weigh:
- Persist `has_explicit_slide_structure` itself (or the detected count) on the presentation row instead
  of re-deriving it from `n_slides == 0` on every call, so a repeat call reads the same decision instead
  of re-deriving a different one from now-mutated state.
- Make the endpoint idempotent by checking `presentation.outlines` (or a dedicated "generation already
  ran" flag) before doing any generation work at all, and short-circuit repeat calls to return the
  already-generated result rather than regenerating.
- At minimum, stop conflating "explicit structure was detected" with "n_slides is still 0" — these are
  two different facts that happen to start out correlated and silently decorrelate the moment the row is
  written to once.
