# AI-Presentation-Studio

## AUTO-UPDATE RULES FOR CLAUDE
- Maximum file length: 300 lines.
- When updating this file, always PRUNE outdated session notes, resolved bugs, and old context.
- Keep only HIGH-LEVEL architectural decisions, recurring project patterns, and unresolved edge cases.
- Never write entire raw code snippets or log dumps in this file. Full session history for any
  resolved item below is recoverable via `git log -- CLAUDE.md` if ever needed — don't re-inflate
  this file by copying it back in.

## Business context — why this project exists

AI Presentation Studio replaces an unmanaged practice: e& employees currently generate decks using
whatever external consumer AI tool they personally prefer (including Claude directly). This creates two
problems the business cares about: (1) internal e& content — strategy documents, financial figures,
customer data — leaves the organization through third-party tools with no record of what was sent or by
whom, and (2) output is inconsistent in quality, structure, and branding across users and tools.

**Hard constraint: data must stay on-premises / within e&'s controlled boundary.** This is why the LLM
provider is Azure OpenAI inside an e&-contracted Microsoft tenant, not a consumer API — model inference
must never route through a hosted service outside that boundary. Before adding or enabling any external
integration (a new search provider, image source, cloud proxy, third-party API, etc.), check whether it
sends user content off-host — if so, it needs to be off by default and explicitly called out, not silently
enabled.

**Success is measured on three things: accuracy, security, cost.** Security means content stays inside
the tenant and access is authenticated/attributable; accuracy means generated decks are faithful to the
user's source material with minimal manual rework; cost means this stays cheaper than the tools it
replaces. None of the three is currently instrumented in production — no eval harness, no audit trail,
no token/cost accounting — so features that make one of these measurable are high-value even when they
don't ship user-visible functionality.

`docs/ARCHITECTURE.md` is current and should be read first for anything architectural. (The old
standalone-era solution-design audit, `SDD-AI-Presentation-Studio_v1.0.md`, was deleted in the 2026-09
cleanup; it is in git history if ever needed.)

## Working with this user

The user is an MIS (Management Information Systems) student with some coding ability but limited
background in software engineering, APIs, and LLMs — and wants to actually learn these concepts over
time, not just get them hidden. When explaining technical concepts, findings, or decisions, keep it plain
and systematic — one or two sentences per point rather than long technical prose — but still introduce
and briefly explain the relevant term or concept rather than skipping it entirely.

## Origin and current architecture

This repo started as a fork of the open-source presentation generator **presenton.ai**; much of the
module naming (e.g. `presenton_` cookie/temp names) still traces back to it. In September 2026 it was cut
down to **only the backend the GenAI Workspace uses** (see `docs/ARCHITECTURE.md` §1 for what was
removed): no Next.js UI, no Docker/nginx stack, no TemplateV2 "standard" decks, no local login, Azure
OpenAI only, config from env only.

**This repo is the backend behind a feature inside GenAI-Workspace.** Users reach every Studio screen
(new deck, outline, editor, export, dashboard) through the Workspace UI (`GenAI-Workspace-UI` repo,
`src/features/studio`), which calls this FastAPI directly. `tests/unit/test_route_contract.py` pins the
exact route list the Workspace calls: adding or removing a route means updating that list and the
Workspace client together.

Current working branch: `feature/workspace-identity`, a worktree of this repo (checked out at
`studio-dev` alongside the main clone). Studio backend changes push to the `Dev-Backend` branch of
`github.com/BasselMahrousseh/AI-Presentation-Studio`. No PRs unless the user asks.

Run this worktree's backend with `./run_studio.sh` from the GenAI-Workspace folder (FastAPI :8011, no
auto-reload), run the Workspace with `GenAI-Workspace-Dev/venv/bin/python run_all.py`, and test in the
Workspace UI at http://localhost:3000. The GenAI-Workspace folder's own `CLAUDE.md` has the folder map
and full commands. Backend config (Azure OpenAI, `STUDIO_SERVICE_API_KEY`) is committed in
`servers/fastapi/.env` at the owner's request.

## Genuinely open / unresolved

- **Exported pie/donut legend swatches- **Exported pie/donut legend swatches can show blank white squares** for categories distinguished by a
  hollow/border-only bullet (`border-4 border-[color]`, no fill) rather than a solid color — likely the
  same permanent closed-source-converter limitation documented for other per-element styling loss on
  export (see `presentation-export/py/convert-*`, no available source). Workaround is prompt-level (avoid
  hollow swatches, use solid tinted colors), not yet added.
- **Area-chart data labels sit at the wrong height in exported PPTX** (roughly the vertical midpoint of
  the point, not the point itself) — this is PowerPoint's own default behavior for area-series labels with
  no `dLblPos` set. No safe `dLblPos` value has been found for area charts: both `outEnd`-family and `ctr`
  (Microsoft's own documented "universally safe" value) corrupted the file in real PowerPoint testing.
  Currently unset/default is the only confirmed-safe state; treat any future `dLblPos` change for area
  charts as needing a real PowerPoint open to verify, not python-pptx success or vendor docs.
- **AI click-to-edit** (in-editor chat rewriting raw Smart HTML) is fully wired but its header toggle
  button is commented out in `PresentationHeader.tsx` — currently undiscoverable.
- **The Workspace editor does not mount the deck chat.** Only the outline page mounts `<Chat>`; the
  Smart deck chat endpoints (`/chat/*` with `presentation_type=smart`) are reachable only through the
  API today. Decide whether to mount it in the editor or drop Smart chat.

## Durable lessons
## Durable lessons

- **Smart generation repairs a failing slide on its own; it never retries the whole deck for one bad
  slide.** One streamed call writes the deck. A slide that fails validation is regenerated by a small
  single-slide call running alongside, while later slides are validated and held so everything is still
  emitted and saved in order (resume depends on that contiguous prefix). A whole-deck continuation only
  happens when a slide's 3 repairs are exhausted or the stream stops more than 3 slides short. Measured
  on real outlines with identical injected failures: 15 slides 139-147s -> 88-105s, 30 slides 262s ->
  126s. Don't reintroduce "abort the stream on the first bad slide" - that discarded every slide drafted
  behind it and re-sent the whole prompt.
- **The outline limit and the Smart generation limit are the same constant (`MAX_NUMBER_OF_SLIDES`,
  40 content slides; e&'s cover and thank-you come on top).** They used to differ (outline 50,
  generation 20), which silently dropped the tail of an approved outline. Keep them equal, including the
  Workspace UI copy in `GenAI-Workspace-UI-Dev-A/src/features/studio/utils/presentationLimits.ts`. Only a
  count the model picks itself (no outline) stays capped at 20.
- **Outline-driven decks over 20 slides are generated in parallel 10-slide chunks.** One long response
  rations effort (slides 10-30% lighter at 40, later slides leaving the bottom third empty); a density
  instruction alone raised word counts but did not fix the empty area. Chunking did: chunk 1 streams
  first and sets the style, the rest run in parallel (up to 4) anchored to its first 2 slides plus a
  `_style_digest`. Measured at 40 slides: 10-slide chunks took 92s (single stream 136-189s, 5-slide
  chunks 114-140s) at 86-88 words/slide (single stream 53-59, short decks ~72), with consistent style.
  Cost vs one stream: ~2-4x input tokens (each chunk re-sends the rules and outline) and ~1.6x output.
  Decks of 20 or fewer, and decks without a per-slide outline, still use one stream (with a density
  instruction above 20).

- **`servers/fastapi/.venv` is a symlink to the main checkout's venv, which has that checkout's
  backend installed in editable mode.** Any module missing from `studio-dev` silently imports from
  `AI-Presentation-Studio` instead of failing, so deleted code can look alive in tests and in the running
  server. `run_studio.sh` drops that import hook before starting; when checking removals, strip it too
  (drop `editable` finders from `sys.meta_path`/`sys.path_hooks`) or run tests in a clean
  `uv sync --locked` venv. A clean venv also caught a dependency (PyJWT) that only arrived transitively.
- **python-pptx performs no OOXML schema validation.**- **python-pptx performs no OOXML schema validation.** It will silently accept a value real PowerPoint
  rejects outright ("needs repair," and PowerPoint's own recovery can drop the entire affected slide).
  Neither python-pptx accepting a value nor Microsoft's own documentation has proven reliable for this
  file format in this codebase's history (a `dLblPos` value documented by Microsoft as universally safe
  still corrupted a real file). The only check that has ever caught this class of bug is a human opening
  the real exported file in real PowerPoint — budget for that explicitly before shipping any OOXML
  element change, especially anything chart-type-restricted like `dLblPos`.
- **The PPTX converter gives each bordered box one outline (one width, one color for all four sides).**
  Verified by real exports: sides with different border colors lose every border on that box, and a box
  bordered all the way round with one thicker accent side (`border-l-[6px] ... border border-black`)
  gets the thick width on all four sides. A uniform border, or 1-3 same-colored sides alone (dividers,
  a lone rail), export faithfully. Guarded two ways: guidance in `SMART_PPTX_EXPORT_FIDELITY_PROMPT`
  and a static check (`_find_pptx_border_export_risks` in `utils/smart_slide_layout.py`) that sends an
  offending slide to per-slide repair. The accent-rail-as-its-own-element pattern (a `w-[6px]` child in
  a uniformly bordered flex card) exports correctly.
- **A backgrounded shell process "succeeding" doesn't mean it bound the port.** `nohup cmd &` returning
  cleanly only means the shell backgrounded it. Before trusting a dev-server restart for verification,
  confirm the new PID is actually listening (`lsof -i :PORT -sTCP:LISTEN`) and that its own startup log
  shows a clean bind, not "address already in use" further down the same log.
- **Next.js/Turbopack dev mode can serve a stale compiled bundle on the very first request after a
  restart**, then correct itself on the very next request with zero code changes in between. Always
  discard-and-retry once when live-verifying a fix right after restarting dev servers.
- **A bare investigation script bypasses `load_dotenv()`.** Config loaded only via `api/main.py`'s own
  `load_dotenv()` call (e.g. `NEXT_PUBLIC_FAST_API`) is invisible to a standalone script that doesn't
  import that module — such a script can silently run against different effective config than the real
  app, producing a plausible-looking but wrong finding. Reproduce the real app's own config-loading path
  before trusting an anomaly found this way.
- **A live re-render/re-render-and-inspect beats static reading for layout bugs.** A CSS Grid/Flexbox
  child's `min-width: auto` default (stealing space from siblings) has been mistaken, from static reading
  alone, for a totally different bug (an uncompiled Tailwind arbitrary-value class) — the fix built for
  the wrong diagnosis was still valid and shipped, but would have been reported as "the whole fix" if a
  live reproduction (computed styles, not source HTML) hadn't caught the real cause too.
- **Get the actual broken artifact before spending time on speculative reproduction.** A PPTX corruption
  bug resisted diagnosis across an earlier session's exhaustive synthetic testing; getting the user's real
  pre-repair file found the exact broken element in under a minute.

## Where to go deeper

- `docs/ARCHITECTURE.md` — current, standalone architecture reference; read this first.
- `BUG_REPORT_has_explicit_slide_structure_idempotency.md` — standalone write-up of a fixed idempotency
  bug, still cited from `docs/ARCHITECTURE.md`, this file's own git history, and two backend files'
  comments/docstrings explaining a non-obvious behavior.
- `STUDIO_IN_WORKSPACE_STATUS.md` (`GenAI-Workspace` repo root, one level up) — live status of the
  Workspace migration referenced in `docs/ARCHITECTURE.md` §8.
