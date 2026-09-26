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

`SDD-AI-Presentation-Studio_v1.0.md` is a full solution-design audit (architecture, data model, security
posture, risk register). It predates the Workspace JWT auth bridge, favorites, and feedback tables
described below (written before that work started) — useful for legacy standalone-Studio internals, but
not authoritative for current auth/identity/data-handling decisions. `docs/ARCHITECTURE.md` is current
and should be read first for anything architectural.

## Working with this user

The user is an MIS (Management Information Systems) student with some coding ability but limited
background in software engineering, APIs, and LLMs — and wants to actually learn these concepts over
time, not just get them hidden. When explaining technical concepts, findings, or decisions, keep it plain
and systematic — one or two sentences per point rather than long technical prose — but still introduce
and briefly explain the relevant term or concept rather than skipping it entirely.

## Origin and current architecture

This repo is a fork of the open-source presentation generator from **presenton.ai** — the Next.js
`package.json` name is still `presenton`, and much of the generic branding/module naming traces back to
that upstream project. The team layers custom features and branding (an "e&"/Etisalat-branded smart-deck
mode, UI reskins, etc.) on top of that inherited base. When something looks orphaned, duplicated, or
inconsistently named, check whether it's inherited upstream functionality before assuming it's a local
bug — a lot of reachable-looking code in this repo is unreferenced upstream Presenton code; grep for a
route's literal path string before trusting a `page.tsx`/endpoint found by name search.

**This repo is no longer a standalone product** — it's the generation engine behind a feature inside
GenAI-Workspace. End users reach Studio's generation/outline/editor screens through Workspace's own
shell/theme/login (`GenAI-Workspace-UI` repo), not this repo's `servers/nextjs` directly. Full current
architecture, the two-server layout, the Smart HTML content model, and the full Studio⇄Workspace
integration detail (phases, auth bridge, what's ported vs. not) live in `docs/ARCHITECTURE.md` — read
that first, this file is for durable working notes and open items only.

Current working branch: `feature/workspace-identity`, a worktree of this repo (checked out at
`studio-dev` alongside the main clone). Studio backend changes push to the `Dev-Backend` branch of
`github.com/BasselMahrousseh/AI-Presentation-Studio`. No PRs unless the user asks.

## Genuinely open / unresolved

- **Smart-mode charts can render blank in the live editor during a fast multi-slide streaming burst.**
  Root cause identified: no viewport culling on Smart-mode iframes (`enableViewportCulling` is accepted
  by `SlideScale` but never forwarded to the `SmartHtmlSlide` branch), so many iframes can mount at once,
  each cold-loading ~490KB of render-blocking script before its inline chart-init code can run. Self-heals
  once script parsing catches up. Fix not yet built — forward `enableViewportCulling` into the Smart-slide
  branch of `PresentationRender.tsx` and warm `loadChartBrowserRuntime()` during streaming.
- **Exported pie/donut legend swatches can show blank white squares** for categories distinguished by a
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
- **`/generation`'s "Generate Standard" button label is misleading** — it's still Smart HTML (no e&
  branding), not the legacy TemplateV2 path. Cosmetic, open.
- **Next.js persistent build cache does not reliably survive a Docker container recreate** — a recreate
  can force a fully cold recompile (~28s for one route) despite `development`'s bind mount, which risks
  hitting webpack's ~120s chunk-load timeout on the first real request after a recreate. Not root-caused.
  Follow-up investigation prompt (still actionable, run this to pick the thread back up):

  > Investigate why `servers/nextjs/.next`'s persistent webpack build cache does not survive a recreate
  > of the `development` Docker container. Confirm live (don't assume from config alone) whether the
  > cache is ever written inside the container at all, whether it's written but not visible on the host
  > bind mount (check Docker Desktop's file-sharing implementation — VirtioFS vs. gRPC-FUSE), or whether
  > something in `next.config.mjs` / `docker-compose.yml`'s env vars disables persistent caching. Verify
  > any fix by recreating the container twice and confirming the second recreate's first compile is
  > measurably faster than the first, not just "no error observed."
- **An intermittent, unexplained Next.js dev-server restart** (`Next.js exited cleanly; restarting it for
  development.`) has been observed twice with no clear trigger. One confirmed cause exists (a Docker
  Desktop OOM kill — check `docker events --filter type=oom` / `docker inspect --format
  '{{.State.OOMKilled}}'`, invisible to application logs), but it is not confirmed to be the only trigger.
  If it recurs with no OOM event at the same timestamp, treat it as a separate, still-open cause.

## Durable lessons

- **`docker-compose.yml`'s `KEY=${KEY:-}` pattern makes "unset" a real, present empty string**, which
  beats a `.env` file's real value under `load_dotenv(..., override=False)` (present-but-empty always
  wins over "not yet set"). If a var works locally but silently breaks under `docker compose up
  development`, check whether it's declared this way in `docker-compose.yml`'s `environment:` block —
  don't assume fixing one variable's precedence means the rest of the ~80-var list is safe.
- **python-pptx performs no OOXML schema validation.** It will silently accept a value real PowerPoint
  rejects outright ("needs repair," and PowerPoint's own recovery can drop the entire affected slide).
  Neither python-pptx accepting a value nor Microsoft's own documentation has proven reliable for this
  file format in this codebase's history (a `dLblPos` value documented by Microsoft as universally safe
  still corrupted a real file). The only check that has ever caught this class of bug is a human opening
  the real exported file in real PowerPoint — budget for that explicitly before shipping any OOXML
  element change, especially anything chart-type-restricted like `dLblPos`.
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
- `SDD-AI-Presentation-Studio_v1.0.md` — full solution-design audit (predates the Workspace integration;
  see the Business Context section above).
- `BUG_REPORT_has_explicit_slide_structure_idempotency.md` — standalone write-up of a fixed idempotency
  bug, still cited from `docs/ARCHITECTURE.md`, this file's own git history, and two backend files'
  comments/docstrings explaining a non-obvious behavior.
- `STUDIO_IN_WORKSPACE_STATUS.md` (`GenAI-Workspace` repo root, one level up) — live status of the
  Workspace migration referenced in `docs/ARCHITECTURE.md` §8.
