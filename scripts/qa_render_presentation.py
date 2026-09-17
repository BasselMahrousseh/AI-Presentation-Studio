#!/usr/bin/env python3
"""
Visual QA sweep for a generated Smart-mode presentation: re-runs the same
render-based layout check every slide already passed during generation
(`_check_smart_slide_layout`) against every slide's *currently persisted*
HTML, and reports which ones would be rejected or scaled-to-fit if checked
right now, plus optionally saves each slide as a PNG for a human to eyeball.

Why this exists: added per this project's own decision to run a visual QA
pass over a freshly generated deck before calling it "done," rather than
trusting "the generation logs showed no errors" alone. See CLAUDE.md's "Real
end-to-end test of the original business use case" entry for the full story,
including a self-correction worth reading before trusting this script's own
history: an early version of this investigation, run as a bare script, saw
every slide's render come back completely unstyled (Tailwind never loaded)
and measured wildly wrong overflow numbers as a result - not a real app bug.
`_build_slide_preview_html()`'s Tailwind/Chart.js <script src> is only made
absolute when NEXT_PUBLIC_FAST_API is set; the real running app has it (via
servers/fastapi/.env, loaded by api/main.py's own load_dotenv() call), but
ANY bare script that doesn't import api.main - this one included - never
triggers that load, so the env var reads as unset and the script src stays a
bare path that the render runtime's page.setContent() (no real navigation,
so no origin to resolve a relative URL against) cannot load. Fixed below by
setting it explicitly before anything else runs. If you copy this pattern
into a new script, keep this line - dropping it silently reintroduces the
exact same false-positive failure mode this file's own investigation hit.

Usage (run inside the FastAPI container, or a host env with
EXPORT_TASK_SERVICE's Puppeteer runtime available):

    python3 scripts/qa_render_presentation.py <presentation_id> \\
        [--db /path/to/fastapi.db] [--out-dir /tmp/qa_renders] [--eand]

Exit code is non-zero if any slide fails the check, so this is safe to wire
into a CI-style gate later if desired - not done yet, since it needs a real
render runtime (Puppeteer/Chromium), which isn't available in the plain unit
test environment.
"""
import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FASTAPI_DIR = REPO_ROOT / "servers" / "fastapi"
sys.path.insert(0, str(FASTAPI_DIR))

# _build_slide_preview_html() only emits an ABSOLUTE Tailwind/Chart.js
# <script src> when NEXT_PUBLIC_FAST_API is set - otherwise it emits a
# path-only src ("/static/vendor/..."), which is fine for a real browser
# page navigated to a same-origin URL but silently fails to resolve at all
# under the render runtime's page.setContent() (no real navigation, so the
# page has no origin to resolve a relative URL against). Confirmed directly:
# with this unset, the check's own render comes back completely unstyled
# (plain block text, no Tailwind applied at all), making every measured
# height/width meaningless. Force an absolute, in-container-reachable base
# before importing anything that reads this at import or call time.
os.environ.setdefault("NEXT_PUBLIC_FAST_API", "http://127.0.0.1:8000")


def _load_slides(db_path: str, presentation_id: str):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            'SELECT "index", html_content FROM slides '
            'WHERE presentation = ? ORDER BY "index"',
            (presentation_id,),
        ).fetchall()
    finally:
        conn.close()
    return list(rows)


def _slide_title(html: str) -> str:
    marker = 'data-slide-title="'
    start = html.find(marker)
    if start == -1:
        return "(untitled)"
    start += len(marker)
    end = html.find('"', start)
    return html[start:end] if end != -1 else "(untitled)"


async def _qa_one_slide(sg, index: int, html: str, *, check_eand_footer: bool):
    try:
        fit_scale = await sg._check_smart_slide_layout(
            html, check_eand_footer=check_eand_footer
        )
    except Exception as exc:  # noqa: BLE001 - reporting, not handling
        return "REJECTED", str(exc)
    if fit_scale is not None:
        return "SCALED", f"would be scaled to fit_scale={fit_scale:.4f}"
    return "OK", ""


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("presentation_id")
    parser.add_argument(
        "--db",
        default=str(REPO_ROOT / "app_data" / "fastapi.db"),
        help="Path to fastapi.db (default: app_data/fastapi.db at the repo root)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="If set, save each slide's rendered PNG here for visual inspection",
    )
    parser.add_argument(
        "--eand",
        action="store_true",
        help="Also check the e& footer safe-area constraint",
    )
    args = parser.parse_args()

    os.chdir(FASTAPI_DIR)
    import utils.llm_calls.generate_smart_presentation as sg  # noqa: E402

    slides = _load_slides(args.db, args.presentation_id.replace("-", ""))
    if not slides:
        print(f"No slides found for presentation_id={args.presentation_id}")
        sys.exit(2)

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)

    failures = 0
    for index, html in slides:
        title = _slide_title(html)
        status, detail = await _qa_one_slide(
            sg, index, html, check_eand_footer=args.eand
        )
        marker = "PASS" if status == "OK" else ("WARN" if status == "SCALED" else "FAIL")
        print(f"[{marker}] slide {index:>2} {title!r}: {status} {detail}")
        if status == "REJECTED":
            failures += 1

        if args.out_dir:
            preview_html = sg._build_slide_preview_html(
                html,
                font_css="",
                width=1280,
                height=720,
            )
            try:
                result = await sg.EXPORT_TASK_SERVICE.render_html_to_image(
                    preview_html, 1280, 720
                )
                dest = os.path.join(args.out_dir, f"slide_{index:02d}.png")
                os.replace(result.path, dest)
            except Exception as exc:  # noqa: BLE001
                print(f"    (could not save preview PNG: {exc})")

    print(f"\n{len(slides)} slides checked, {failures} rejected.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
