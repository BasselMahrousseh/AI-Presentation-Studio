import asyncio
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from llmai.shared import ReasoningConfig, ReasoningEffortValue, UserMessage
from PIL import Image

import utils.llm_calls.generate_smart_presentation as smart_generation

from enums.llm_provider import LLMProvider
from services.community_presentations import (
    CommunityPresentationReference,
    build_community_design_context,
    list_community_presentations,
    merge_reference_fonts,
    normalize_community_ids,
)
from utils.llm_calls.generate_smart_presentation import (
    SMART_DECK_SYSTEM_PROMPT,
    SmartSlideStreamParser,
    _stream_deck_response,
    determine_smart_slide_count,
    get_smart_messages,
    get_smart_reasoning_config,
    normalize_smart_deck,
    normalize_smart_slide_html,
    parse_smart_presentation_html,
    resolve_smart_slide_count,
)


def _smart_slide_html(title="Slide", slide_type="content", body="Content"):
    return (
        f'<section data-slide-type="{slide_type}" data-slide-title="{title}" '
        'class="relative h-[720px] w-[1280px] overflow-hidden">'
        f"{body}</section>"
    )


def test_smart_slide_stream_parser_emits_delimited_slides_incrementally():
    parser = SmartSlideStreamParser()
    second_slide = _smart_slide_html("Two")

    assert parser.feed("<!-- PRESENTATION_TITLE: Deck --><!-- SLIDE_STA") == []
    slides = parser.feed(
        "RT -->"
        + _smart_slide_html("One")
        + "<!-- SLIDE_END --><!-- SLIDE_START -->"
        + second_slide[:80]
    )
    assert [slide["title"] for slide in slides] == ["One"]
    assert slides[0]["speaker_note"] == ""

    slides = parser.feed(second_slide[80:] + "<!-- SLIDE_END -->")
    assert [slide["title"] for slide in slides] == ["Two"]


def test_smart_deck_parser_uses_cloud_delimiters_and_validates_count():
    response = (
        "<!-- PRESENTATION_TITLE: Deck -->"
        "<!-- SLIDE_START -->"
        + _smart_slide_html("Cover", "title")
        + "<!-- SLIDE_END -->"
        "<!-- SLIDE_START -->"
        + _smart_slide_html("Agenda", "toc")
        + "<!-- SLIDE_END -->"
    )

    title, slides = parse_smart_presentation_html(
        response,
        expected_slide_count=2,
        include_title_slide=True,
        include_table_of_contents=True,
    )

    assert title == "Deck"
    assert [slide["title"] for slide in slides] == ["Cover", "Agenda"]
    with pytest.raises(HTTPException):
        parse_smart_presentation_html(
            response,
            expected_slide_count=3,
            include_title_slide=True,
            include_table_of_contents=True,
        )


def test_smart_prompt_matches_cloud_one_shot_method_without_speaker_notes():
    messages = get_smart_messages(
        content="Build an investor update",
        n_slides=6,
        language="English",
        tone=None,
        verbosity=None,
        instructions=None,
        include_title_slide=True,
        include_table_of_contents=False,
        source_context="Revenue grew.",
        community_design_context="Use editorial spacing.",
        fonts={"Inter": "inter.css"},
    )
    prompt = str(messages[1].content)

    assert messages[0].content == SMART_DECK_SYSTEM_PROMPT
    assert "<!-- SLIDE_START -->" in prompt
    assert "Generate exactly 6 total slides" in prompt
    assert 'Available fonts: ["Inter"]' in prompt
    assert "speaker_note" not in prompt
    assert "Speaker note" not in prompt
    assert "Overflow prevention is a hard requirement" in prompt
    assert "Never use `overflow-auto`" in prompt
    assert "normal-flow flex/grid" in prompt
    assert "text-led slides may use" in prompt
    assert "do not silently discard" in prompt
    # Pie/donut chart-sizing guidance (added after a real generation got
    # stuck repeatedly failing the canvas-overflow check on a pie slide).
    assert "pie or donut chart is a frequent overflow source" in prompt
    assert "380-420px" in prompt


def test_smart_retry_prompt_includes_layout_validation_feedback():
    messages = get_smart_messages(
        content="Build an investor update",
        n_slides=2,
        language="English",
        tone=None,
        verbosity=None,
        instructions=None,
        include_title_slide=True,
        include_table_of_contents=False,
        source_context="",
        community_design_context="",
        retry_error="Slide content uses overflow-y-auto",
    )

    prompt = str(messages[1].content)
    assert "prior response failed validation" in prompt
    assert "Slide content uses overflow-y-auto" in prompt


def test_smart_prompt_uses_the_eand_brand_contract_without_embedding_the_shell():
    messages = get_smart_messages(
        content="Build a strategy deck",
        n_slides=2,
        language="English",
        tone=None,
        verbosity=None,
        instructions=None,
        include_title_slide=True,
        include_table_of_contents=False,
        source_context="",
        community_design_context="",
        smart_template="eand",
    )

    prompt = str(messages[1].content)
    assert "e& BRAND TEMPLATE CONTRACT" in prompt
    assert "y=640 to y=720" in prompt
    assert "eand-footer-bar.png" not in prompt
    # Pie/donut chart-sizing guidance, e&-specific version (added after a
    # real e& generation got stuck repeatedly failing the canvas-overflow
    # check on a pie slide - see CLAUDE.md).
    assert "pie or donut chart is a frequent source of overflow" in prompt
    assert "380-420px" in prompt


def test_smart_reasoning_uses_low_effort_for_openai(monkeypatch):
    monkeypatch.setattr(
        "utils.llm_calls.generate_smart_presentation.disable_thinking",
        lambda: False,
    )
    monkeypatch.setattr(
        "utils.llm_calls.generate_smart_presentation.get_llm_provider",
        lambda: LLMProvider.OPENAI,
    )
    monkeypatch.setattr(
        "utils.llm_calls.generate_smart_presentation.llmai.supports_thinking",
        lambda model, provider=None: True,
    )

    reasoning, supports_thinking = get_smart_reasoning_config("gpt-5")

    assert supports_thinking is True
    assert reasoning is not None
    assert reasoning.enabled is True
    assert reasoning.effort == ReasoningEffortValue.LOW


def test_smart_reasoning_respects_disable_thinking(monkeypatch):
    monkeypatch.setattr(
        "utils.llm_calls.generate_smart_presentation.disable_thinking",
        lambda: True,
    )

    reasoning, supports_thinking = get_smart_reasoning_config("gpt-5")

    assert reasoning is None
    assert supports_thinking is False


def test_smart_stream_separates_thinking_and_reports_exact_usage(monkeypatch):
    reasoning = ReasoningConfig(enabled=True)
    captured_kwargs = {}

    async def fake_stream_generate_events(_client, **kwargs):
        captured_kwargs.update(kwargs)
        yield SimpleNamespace(type="thinking", chunk="private planning")
        yield SimpleNamespace(type="content", chunk="visible deck")
        yield SimpleNamespace(
            type="completion",
            content=None,
            usage=SimpleNamespace(
                input_tokens=12,
                output_tokens=8,
                total_tokens=20,
                reasoning=SimpleNamespace(
                    billed_tokens=5,
                    billed_estimated=False,
                ),
            ),
            duration_seconds=2.0,
        )

    monkeypatch.setattr(
        "utils.llm_calls.generate_smart_presentation.stream_generate_events",
        fake_stream_generate_events,
    )
    monkeypatch.setattr("utils.llm_utils.get_extra_body", lambda **_kwargs: None)
    content_chunks = []
    thinking_chunks = []

    async def on_chunk(chunk):
        content_chunks.append(chunk)

    async def on_thinking_chunk(chunk):
        thinking_chunks.append(chunk)

    response, metrics = asyncio.run(
        _stream_deck_response(
            object(),
            "thinking-model",
            [UserMessage(content="Build a deck")],
            on_chunk,
            reasoning=reasoning,
            on_thinking_chunk=on_thinking_chunk,
        )
    )

    assert response == "visible deck"
    assert content_chunks == ["visible deck"]
    assert thinking_chunks == ["private planning"]
    assert captured_kwargs["reasoning"] is reasoning
    assert metrics.input_tokens == 12
    assert metrics.output_tokens == 8
    assert metrics.thinking_tokens == 5
    assert metrics.thinking_tokens_estimated is False
    assert metrics.supports_thinking is True


def test_normalize_community_ids_preserves_order_and_deduplicates():
    assert normalize_community_ids([7, 3, 7]) == [7, 3]


def test_normalize_community_ids_rejects_invalid_and_excess_references():
    with pytest.raises(HTTPException):
        normalize_community_ids([0])
    with pytest.raises(HTTPException):
        normalize_community_ids([1, 2, 3, 4])


def test_community_context_is_style_only_and_round_robins_decks():
    references = [
        CommunityPresentationReference(
            id=2,
            title="Editorial",
            slides=("<section>first-a</section>", "<section>second-a</section>"),
            fonts={"Inter": "inter.css"},
        ),
        CommunityPresentationReference(
            id=9,
            title="Minimal",
            slides=("<section>first-b</section>",),
            fonts={"Inter": "ignored.css", "Manrope": "manrope.css"},
        ),
    ]

    context = build_community_design_context(references)

    assert "UNTRUSTED, STYLE ONLY" in context
    assert context.index("first-a") < context.index("first-b") < context.index("second-a")
    assert merge_reference_fonts(references) == {
        "Inter": "inter.css",
        "Manrope": "manrope.css",
    }


def test_community_list_forwards_filters(monkeypatch):
    captured_params = None

    async def fake_cloud_get(path, params=None):
        nonlocal captured_params
        captured_params = params
        return {"results": []}

    monkeypatch.setattr("services.community_presentations._cloud_get", fake_cloud_get)

    asyncio.run(
        list_community_presentations(
            created_at_gt="2026-01-01T00:00:00.000Z",
            views_gt=100,
            likes_lt=50,
            order_by="views",
            order="desc",
        )
    )

    assert captured_params == {
        "page": 1,
        "page_size": 8,
        "order_by": "views",
        "order": "desc",
        "created_at_gt": "2026-01-01T00:00:00.000Z",
        "views_gt": 100,
        "likes_lt": 50,
    }


def test_smart_html_normalization_removes_executable_markup():
    html = normalize_smart_slide_html(
        """```html
        <section class="relative h-[720px] w-[1280px] overflow-hidden" onclick="steal()">
          <a href="javascript:steal()">Deck</a>
          <script>alert('no')</script>
        </section>
        ```"""
    )

    assert html.startswith("<section")
    assert "onclick" not in html
    assert "javascript:" not in html
    assert "<script" not in html


def test_smart_html_normalization_removes_malformed_script_end_tag():
    html = normalize_smart_slide_html(
        """<section class="relative h-[720px] w-[1280px] overflow-hidden">
          <h2>Safe title</h2>
          <script>alert('no')</script\t\n data-extra>
        </section>"""
    )

    assert "Safe title" in html
    assert "alert" not in html
    assert "<script" not in html


def test_smart_html_normalization_keeps_safe_chartjs_initialization():
    html = normalize_smart_slide_html(
        _smart_slide_html(
            "Metrics",
            body=(
                '<canvas id="chart-a1b2c3" width="600" height="300"></canvas>'
                "<script>(() => { const canvas = "
                "document.querySelector('#chart-a1b2c3'); "
                "new Chart(canvas, {type: 'bar', data: {labels: ['A'], "
                "datasets: [{data: [1]}]}, options: {responsive: false, "
                "animation: false}}); })();</script>"
            ),
        )
    )

    assert "new Chart" in html
    assert "<script" in html


def test_smart_html_normalization_keeps_chartjs_formatter_callbacks():
    html = normalize_smart_slide_html(
        _smart_slide_html(
            "Regional metrics",
            body=(
                '<canvas id="chart-c4d5e6" width="600" height="300"></canvas>'
                "<script>(() => { const canvas = "
                "document.querySelector('#chart-c4d5e6'); "
                "new Chart(canvas, {type: 'bar', data: {labels: ['Location', 'Top'], "
                "datasets: [{data: [42, 51]}]}, options: {responsive: false, "
                "animation: false, plugins: {datalabels: {formatter: "
                "function(value) { return value + '%'; }}}}}); })();</script>"
            ),
        )
    )

    assert "<script" in html
    assert "function(value)" in html
    assert "Location" in html
    assert "Top" in html


def test_smart_html_normalization_rejects_chart_canvas_without_initializer():
    with pytest.raises(HTTPException, match="missing its inline Chart.js"):
        normalize_smart_slide_html(
            _smart_slide_html(
                "Incomplete chart",
                body=(
                    '<canvas id="chart-a1b2c3" width="600" height="300">'
                    "</canvas>"
                ),
            )
        )


def test_smart_html_normalization_rejects_chart_scripts_with_network_access():
    with pytest.raises(HTTPException, match="missing its inline Chart.js"):
        normalize_smart_slide_html(
            _smart_slide_html(
                "Unsafe chart",
                body=(
                    '<canvas id="chart-a1b2c3" width="600" height="300">'
                    "</canvas><script>(() => { fetch('/private'); "
                    "new Chart(document.querySelector('#chart-a1b2c3'), "
                    "{type: 'bar', data: {labels: [], datasets: []}}); "
                    "})();</script>"
                ),
            )
        )


def test_smart_api_parser_returns_complete_chart_html():
    chart_slide = _smart_slide_html(
        "Metrics",
        body=(
            '<canvas id="chart-d4e5f6" width="600" height="300"></canvas>'
            "<script>(() => { const canvas = "
            "document.querySelector('#chart-d4e5f6'); "
            "new Chart(canvas, {type: 'line', data: {labels: ['Q1'], "
            "datasets: [{data: [10]}]}, options: {responsive: false, "
            "animation: false}}); })();</script>"
        ),
    )
    response = (
        "<!-- PRESENTATION_TITLE: Metrics -->"
        "<!-- SLIDE_START -->"
        + chart_slide
        + "<!-- SLIDE_END -->"
    )

    _, slides = parse_smart_presentation_html(
        response,
        expected_slide_count=1,
        include_title_slide=False,
        include_table_of_contents=False,
    )

    assert "<canvas" in slides[0]["html"]
    assert "<script" in slides[0]["html"]
    assert "new Chart" in slides[0]["html"]


@pytest.mark.parametrize(
    "unsafe_layout",
    (
        '<div class="h-[200px] overflow-y-auto">Long copy</div>',
        '<p class="line-clamp-3">Hidden copy</p>',
        '<div style="overflow: scroll">Scrollable copy</div>',
    ),
)
def test_smart_html_normalization_rejects_overflow_hiding_patterns(unsafe_layout):
    with pytest.raises(HTTPException, match="scrolling or text clipping"):
        normalize_smart_slide_html(
            _smart_slide_html("Unsafe layout", body=unsafe_layout)
        )


def test_smart_html_normalization_rejects_text_density_that_cannot_fit():
    dense_copy = " ".join(["overflowing"] * 221)

    with pytest.raises(HTTPException, match="too text-dense"):
        normalize_smart_slide_html(
            _smart_slide_html("Dense layout", body=f"<p>{dense_copy}</p>")
        )


def test_smart_html_normalization_allows_richer_text_led_slide():
    rich_copy = " ".join(["strategy"] * 170)

    html = normalize_smart_slide_html(
        _smart_slide_html(
            "Detailed strategy",
            body=f'<div class="grid grid-cols-2 gap-8"><p>{rich_copy}</p></div>',
        )
    )

    assert rich_copy in html


def test_smart_html_normalization_keeps_visual_slides_more_concise():
    rich_copy = " ".join(["evidence"] * 161)

    with pytest.raises(HTTPException, match="too text-dense"):
        normalize_smart_slide_html(
            _smart_slide_html(
                "Visual evidence",
                body=(
                    '<img src="https://example.com/evidence.png" '
                    'alt="Evidence" class="h-[320px] w-[480px]">'
                    f"<p>{rich_copy}</p>"
                ),
            )
        )


def test_smart_html_normalization_rejects_nested_text_clipping():
    with pytest.raises(HTTPException, match="nested container hides text"):
        normalize_smart_slide_html(
            _smart_slide_html(
                "Clipped card",
                body='<div class="h-[80px] overflow-hidden">Visible text</div>',
            )
        )


def test_smart_html_normalization_rejects_unbounded_absolute_text():
    with pytest.raises(HTTPException, match="missing a complete pixel box"):
        normalize_smart_slide_html(
            _smart_slide_html(
                "Floating text",
                body='<div class="absolute left-8 top-8">Floating content</div>',
            )
        )


def test_smart_html_normalization_rejects_negative_content_offsets():
    with pytest.raises(HTTPException, match="negative margin or translation"):
        normalize_smart_slide_html(
            _smart_slide_html(
                "Colliding content",
                body='<div class="-mt-8">Pulled over the heading</div>',
            )
        )


def test_smart_html_normalization_rejects_off_canvas_positioned_content():
    with pytest.raises(HTTPException, match="right slide/container boundary"):
        normalize_smart_slide_html(
            _smart_slide_html(
                "Off canvas",
                body=(
                    '<div class="absolute left-[1100px] top-[40px] '
                    'w-[300px] h-[80px]">Outside</div>'
                ),
            )
        )


def test_smart_html_normalization_rejects_overlapping_positioned_siblings():
    with pytest.raises(HTTPException, match="sibling content boxes overlap"):
        normalize_smart_slide_html(
            _smart_slide_html(
                "Overlap",
                body=(
                    '<div class="absolute left-[64px] top-[120px] '
                    'w-[420px] h-[180px]">First</div>'
                    '<div class="absolute left-[360px] top-[160px] '
                    'w-[420px] h-[180px]">Second</div>'
                ),
            )
        )


def test_smart_html_normalization_accepts_separated_positioned_content():
    html = normalize_smart_slide_html(
        _smart_slide_html(
            "Separated",
            body=(
                '<div class="absolute left-[64px] top-[120px] '
                'w-[420px] h-[180px]">First</div>'
                '<div class="absolute left-[560px] top-[120px] '
                'w-[420px] h-[180px]">Second</div>'
                '<div aria-hidden="true" data-decorative="true" '
                'class="absolute -translate-x-1/2">Decoration</div>'
            ),
        )
    )

    assert "First" in html
    assert "Second" in html


def test_smart_deck_requires_exact_slide_count_and_omits_speaker_notes():
    valid_slide = {
        "title": "One",
        "html": _smart_slide_html("One"),
        "speaker_note": "This must be discarded",
    }
    deck = normalize_smart_deck(
        {"title": "Deck", "slides": [valid_slide, {**valid_slide, "title": "Two"}]},
        2,
    )
    assert deck["title"] == "Deck"
    assert len(deck["slides"]) == 2
    assert all(slide["speaker_note"] == "" for slide in deck["slides"])

    with pytest.raises(HTTPException):
        normalize_smart_deck({"title": "Deck", "slides": [valid_slide]}, 2)
    with pytest.raises(HTTPException):
        normalize_smart_slide_html("<div>Not a slide</div>")


def test_explicit_smart_slide_count_is_bounded():
    assert resolve_smart_slide_count(8) == 8
    assert resolve_smart_slide_count(200) == 20


def test_smart_slide_count_is_chosen_by_llm(monkeypatch):
    captured = {}

    async def fake_generate_structured(_client, _model, **kwargs):
        captured.update(kwargs)
        return {"n_slides": 12}

    monkeypatch.setattr(
        smart_generation, "generate_structured_with_schema_retries", fake_generate_structured
    )
    monkeypatch.setattr(smart_generation, "get_llm_config", lambda **_kwargs: {})
    monkeypatch.setattr(smart_generation, "get_client", lambda **_kwargs: object())
    monkeypatch.setattr(smart_generation, "get_model", lambda: "test-model")

    count = asyncio.run(
        determine_smart_slide_count(
            content="Explain renewable-energy adoption trends",
            instructions="Include risks and recommendations",
            source_context="Reference material",
            include_title_slide=True,
            include_table_of_contents=False,
        )
    )

    assert count == 12
    assert "renewable-energy" in captured["messages"][1].content
    assert captured["json_schema"]["properties"]["n_slides"]["maximum"] == 20


def test_eand_explicit_content_plan_keeps_every_supplied_section():
    # The count returned is content slides only; the caller adds the fixed
    # cover/thank-you slides on top to get the deck's true total.
    count = asyncio.run(
        determine_smart_slide_count(
            content="""
Slide 1 — Overview
Slide 2 — Options
Slide 3 — Recommendation
Slide 4 — Rollout
""",
            instructions=None,
            source_context="",
            include_title_slide=True,
            include_table_of_contents=False,
            minimum_slide_count=1,
            fixed_slide_count=2,
        )
    )

    assert count == 4


def test_eand_colon_delimited_outline_keeps_every_supplied_section():
    count = asyncio.run(
        determine_smart_slide_count(
            content="""
Slide: 1
Overview
Slide: 2
Options
Slide: 3
Recommendation
Slide: 4
Rollout
""",
            instructions=None,
            source_context="",
            include_title_slide=True,
            include_table_of_contents=False,
            minimum_slide_count=1,
            fixed_slide_count=2,
        )
    )

    assert count == 4


def test_eand_slide_count_is_capped_so_total_with_fixed_slides_fits(monkeypatch):
    captured = {}

    async def fake_generate_structured(_client, _model, **kwargs):
        captured.update(kwargs)
        return {"n_slides": kwargs["json_schema"]["properties"]["n_slides"]["maximum"]}

    monkeypatch.setattr(
        smart_generation, "generate_structured_with_schema_retries", fake_generate_structured
    )
    monkeypatch.setattr(smart_generation, "get_llm_config", lambda **_kwargs: {})
    monkeypatch.setattr(smart_generation, "get_client", lambda **_kwargs: object())
    monkeypatch.setattr(smart_generation, "get_model", lambda: "test-model")

    count = asyncio.run(
        determine_smart_slide_count(
            content="A topic with no explicit slide plan",
            instructions=None,
            source_context="",
            include_title_slide=True,
            include_table_of_contents=False,
            minimum_slide_count=1,
            fixed_slide_count=2,
        )
    )

    assert captured["json_schema"]["properties"]["n_slides"]["maximum"] == 18
    assert count + 2 <= smart_generation.MAX_SMART_SLIDE_COUNT


def test_slide_html_without_canvas_clip_removes_only_overflow_hidden():
    html = (
        '<section data-slide-type="content" '
        'class="relative h-[720px] w-[1280px] overflow-hidden bg-slate-950">'
        '<div class="rounded-2xl overflow-hidden">Card</div></section>'
    )

    result = smart_generation._slide_html_without_canvas_clip(html)

    root_open_tag = result.split(">", 1)[0]
    # h-[720px] must stay intact - it's what keeps every descendant's
    # h-full/flex/grid sizing identical to the real render. Only the clip
    # itself is lifted.
    assert "h-[720px]" in root_open_tag
    assert "overflow-hidden" not in root_open_tag
    assert "w-[1280px]" in root_open_tag
    assert "relative" in root_open_tag
    # A nested element's own overflow-hidden (e.g. a rounded card clipping its
    # own children) must be left untouched - only the root canvas is unclipped.
    assert 'class="rounded-2xl overflow-hidden"' in result


# ---------------------------------------------------------------------------
# _check_smart_slide_eand_footer_safe_area - previously had zero coverage
# ---------------------------------------------------------------------------


def test_generation_waives_render_checks_after_repeated_stalls_at_one_slide(monkeypatch):
    """A slide the model cannot get under the overflow threshold must not be
    able to consume the entire retry budget and take the whole deck down with
    it. Reproduces the real production failure: an e& deck where slide 7 was
    rejected over and over, ending with "N valid slides were retained" and no
    usable presentation. After SMART_MAX_CONSECUTIVE_SLIDE_FAILURES stalls at
    one position, the render-based quality gate steps aside for that slide so
    generation can finish."""
    n_slides = 3
    stall_marker = 'data-slide-title="STALLS"'
    overflow_calls = {"count": 0}

    async def fake_layout_check(html, *, check_eand_footer=False):
        if stall_marker in html:
            overflow_calls["count"] += 1
            raise HTTPException(status_code=400, detail="content is too tall")

    monkeypatch.setattr(
        smart_generation, "_check_smart_slide_layout", fake_layout_check
    )

    async def fake_stream(client, model, messages, on_chunk, **kwargs):
        prompt = str(messages[1].content)
        match = re.search(r"Generate exactly (\d+)", prompt)
        remaining = int(match.group(1))
        start = n_slides - remaining
        response = "<!-- PRESENTATION_TITLE: Deck -->"
        for offset in range(remaining):
            # The second slide of the deck always trips the overflow check.
            title = "STALLS" if start + offset == 1 else f"Slide {start + offset}"
            response += (
                "<!-- SLIDE_START -->"
                + _smart_slide_html(title=title)
                + "<!-- SLIDE_END -->"
            )
        await on_chunk(response)
        return response, SimpleNamespace(model=model, input_tokens=1, output_tokens=1)

    monkeypatch.setattr(smart_generation, "_stream_deck_response", fake_stream)
    monkeypatch.setattr(smart_generation, "get_llm_config", lambda **_kwargs: {})
    monkeypatch.setattr(smart_generation, "get_client", lambda **_kwargs: object())
    monkeypatch.setattr(smart_generation, "get_model", lambda: "test-model")
    monkeypatch.setattr(
        smart_generation, "get_smart_reasoning_config", lambda model: (None, False)
    )

    result = asyncio.run(
        smart_generation.generate_smart_presentation(
            content="Chart deck",
            n_slides=n_slides,
            language="English",
            tone=None,
            verbosity=None,
            instructions=None,
            include_title_slide=False,
            include_table_of_contents=False,
        )
    )

    # The deck completed instead of dying at the stubborn slide.
    assert len(result["slides"]) == n_slides
    assert result["slides"][1]["title"] == "STALLS"
    # The gate really did run and reject repeatedly before being waived, rather
    # than the slide simply passing - otherwise this test would prove nothing.
    assert overflow_calls["count"] >= smart_generation.SMART_MAX_CONSECUTIVE_SLIDE_FAILURES


def test_generation_still_fails_when_no_progress_is_ever_made(monkeypatch):
    """The waiver is scoped to one stuck position, not a blanket disable: a
    response that never yields a usable slide at all must still fail rather
    than silently returning a short deck."""

    async def fake_stream(client, model, messages, on_chunk, **kwargs):
        await on_chunk("<!-- PRESENTATION_TITLE: Deck -->not a slide at all")
        return "junk", SimpleNamespace(model=model, input_tokens=1, output_tokens=1)

    monkeypatch.setattr(smart_generation, "_stream_deck_response", fake_stream)
    monkeypatch.setattr(smart_generation, "get_llm_config", lambda **_kwargs: {})
    monkeypatch.setattr(smart_generation, "get_client", lambda **_kwargs: object())
    monkeypatch.setattr(smart_generation, "get_model", lambda: "test-model")
    monkeypatch.setattr(
        smart_generation, "get_smart_reasoning_config", lambda model: (None, False)
    )

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            smart_generation.generate_smart_presentation(
                content="Chart deck",
                n_slides=3,
                language="English",
                tone=None,
                verbosity=None,
                instructions=None,
                include_title_slide=False,
                include_table_of_contents=False,
            )
        )
    assert "Failed to generate the complete Smart presentation" in excinfo.value.detail


def _layout_probe_image(tmp_path, *, overflow=False, footer=False, name="probe.png"):
    """A 1280x1440 render stand-in: the slide's own 720px box is white (as e&
    requires), everything below it is the sentinel page colour."""
    width = smart_generation.SMART_OVERFLOW_SAFE_AREA_WIDTH
    height = smart_generation.SMART_OVERFLOW_MEASURE_HEIGHT
    canvas_h = smart_generation.SMART_SLIDE_CANVAS_HEIGHT
    image = Image.new("RGB", (width, height), smart_generation._SMART_OVERFLOW_SENTINEL_RGB)
    for x in range(width):
        for y in range(canvas_h):
            image.putpixel((x, y), smart_generation._EAND_FOOTER_BACKGROUND_RGB)
    if footer:
        for x in range(width):
            for y in range(smart_generation.EAND_FOOTER_RESERVED_TOP_Y, canvas_h):
                image.putpixel((x, y), (10, 20, 30))
    if overflow:
        for x in range(width):
            for y in range(canvas_h, canvas_h + 60):
                image.putpixel((x, y), (10, 20, 30))
    path = tmp_path / name
    image.save(path)
    return str(path)


def _patch_render(monkeypatch, image_path, counter):
    async def fake_render(_html, _w, _h):
        counter["n"] += 1
        return SimpleNamespace(path=image_path)

    monkeypatch.setattr(
        smart_generation.EXPORT_TASK_SERVICE, "render_html_to_image", fake_render
    )


def test_layout_check_uses_a_single_render_for_both_bands(monkeypatch, tmp_path):
    """e& slides used to pay two full cold-Chromium renders per slide to
    measure the same page. Both checks now share one render."""
    counter = {"n": 0}
    _patch_render(monkeypatch, _layout_probe_image(tmp_path), counter)

    asyncio.run(
        smart_generation._check_smart_slide_layout(
            _smart_slide_html(), check_eand_footer=True
        )
    )
    assert counter["n"] == 1


def test_layout_check_detects_canvas_overflow(monkeypatch, tmp_path):
    counter = {"n": 0}
    _patch_render(
        monkeypatch, _layout_probe_image(tmp_path, overflow=True), counter
    )

    # 60px of overflow past the 720px canvas: the content is 780px tall, so
    # it is scaled to 720/780 to fit rather than clipped or regenerated.
    fit_scale = asyncio.run(
        smart_generation._check_smart_slide_layout(
            _smart_slide_html(), check_eand_footer=False
        )
    )
    assert fit_scale == pytest.approx(720 / 780, abs=1e-4)


def test_layout_check_detects_eand_footer_intrusion_only_when_asked(
    monkeypatch, tmp_path
):
    counter = {"n": 0}
    # A fresh image per call: the check deletes the render once it's measured.
    _patch_render(
        monkeypatch,
        _layout_probe_image(tmp_path, footer=True, name="footer_a.png"),
        counter,
    )

    # Non-e& decks have no reserved footer band, so this must pass.
    asyncio.run(
        smart_generation._check_smart_slide_layout(
            _smart_slide_html(), check_eand_footer=False
        )
    )

    _patch_render(
        monkeypatch,
        _layout_probe_image(tmp_path, footer=True, name="footer_b.png"),
        counter,
    )
    # e& content reaching y=720 must clear the reserved band at y=630, so the
    # scale is driven by the tighter footer constraint, not the canvas.
    fit_scale = asyncio.run(
        smart_generation._check_smart_slide_layout(
            _smart_slide_html(), check_eand_footer=True
        )
    )
    assert fit_scale == pytest.approx(630 / 720, abs=1e-4)


def test_layout_check_accepts_a_clean_slide(monkeypatch, tmp_path):
    counter = {"n": 0}
    _patch_render(monkeypatch, _layout_probe_image(tmp_path), counter)

    assert (
        asyncio.run(
            smart_generation._check_smart_slide_layout(
                _smart_slide_html(), check_eand_footer=True
            )
        )
        is None
    )


def test_layout_check_fails_open_on_render_http_exception(monkeypatch):
    """Infra failures (render timeout/crash, which surface as HTTPException
    from EXPORT_TASK_SERVICE) must not be mistaken for layout failures - they
    would burn a retry attempt on something the model cannot correct."""

    async def fake_render(_html, _w, _h):
        raise HTTPException(
            status_code=500, detail="Export task timed out after 300 seconds"
        )

    monkeypatch.setattr(
        smart_generation.EXPORT_TASK_SERVICE, "render_html_to_image", fake_render
    )

    asyncio.run(
        smart_generation._check_smart_slide_layout(
            _smart_slide_html(), check_eand_footer=True
        )
    )


def test_layout_check_fails_open_on_generic_render_error(monkeypatch):
    """Non-HTTP infra errors (e.g. a crashed Puppeteer child) must also fail
    open rather than being reported as a layout problem."""

    async def fake_render(_html, _w, _h):
        raise RuntimeError("puppeteer crashed")

    monkeypatch.setattr(
        smart_generation.EXPORT_TASK_SERVICE, "render_html_to_image", fake_render
    )

    asyncio.run(
        smart_generation._check_smart_slide_layout(
            _smart_slide_html(), check_eand_footer=True
        )
    )


# ---------------------------------------------------------------------------
# Retry-loop instrumentation: the permanent per-attempt failure log, and the
# opt-in salvage probe used to measure how much generated work each failure
# throws away (see SMART_SALVAGE_PROBE_ENV).
# ---------------------------------------------------------------------------


def _stalling_deck_stream(n_slides, fail_at_index, monkeypatch):
    """A model that always emits the full remaining deck, with one slide at
    `fail_at_index` that never passes the render-based layout check."""

    async def fake_layout_check(html, *, check_eand_footer=False):
        if 'data-slide-title="BAD"' in html:
            raise HTTPException(status_code=400, detail="content is too tall")

    async def fake_stream(client, model, messages, on_chunk, **kwargs):
        prompt = str(messages[1].content)
        remaining = int(re.search(r"Generate exactly (\d+)", prompt).group(1))
        start = n_slides - remaining
        response = "<!-- PRESENTATION_TITLE: Deck -->"
        for offset in range(remaining):
            index = start + offset
            title = "BAD" if index == fail_at_index else f"Slide {index}"
            response += (
                "<!-- SLIDE_START -->"
                + _smart_slide_html(title=title)
                + "<!-- SLIDE_END -->"
            )
        await on_chunk(response)
        return response, SimpleNamespace(model=model, input_tokens=1, output_tokens=1)

    monkeypatch.setattr(
        smart_generation, "_check_smart_slide_layout", fake_layout_check
    )
    monkeypatch.setattr(smart_generation, "_stream_deck_response", fake_stream)
    monkeypatch.setattr(smart_generation, "get_llm_config", lambda **_kwargs: {})
    monkeypatch.setattr(smart_generation, "get_client", lambda **_kwargs: object())
    monkeypatch.setattr(smart_generation, "get_model", lambda: "test-model")
    monkeypatch.setattr(
        smart_generation, "get_smart_reasoning_config", lambda model: (None, False)
    )


def _generate(n_slides):
    return asyncio.run(
        smart_generation.generate_smart_presentation(
            content="Chart deck",
            n_slides=n_slides,
            language="English",
            tone=None,
            verbosity=None,
            instructions=None,
            include_title_slide=False,
            include_table_of_contents=False,
        )
    )


def test_failed_attempt_logs_the_slide_position_it_died_at(monkeypatch, caplog):
    """Without this line there is no way to tell a wasted attempt that died at
    slide 1 from one that kept 12 of 14 slides - the distinction that decides
    whether salvaging the discarded tail is worth anything."""
    _stalling_deck_stream(8, fail_at_index=5, monkeypatch=monkeypatch)
    monkeypatch.delenv(smart_generation.SMART_SALVAGE_PROBE_ENV, raising=False)

    with caplog.at_level("INFO", logger=smart_generation.LOGGER.name):
        _generate(8)

    failures = [r for r in caplog.records if "attempt_failed" in r.getMessage()]
    assert failures, "a failing attempt must log where it died"
    first = failures[0].getMessage()
    # Slide 6 (1-based) is index 5, and the 5 slides before it were kept.
    assert "died_at_slide=6" in first
    assert "of=8" in first
    assert "new_slides_this_attempt=5" in first


def test_salvage_probe_counts_the_discarded_tail_without_changing_the_deck(
    monkeypatch,
):
    """The probe must measure what a failure throws away while leaving the
    generated deck byte-for-byte identical - otherwise it would be changing the
    very behaviour it is supposed to measure."""
    _stalling_deck_stream(8, fail_at_index=2, monkeypatch=monkeypatch)

    monkeypatch.delenv(smart_generation.SMART_SALVAGE_PROBE_ENV, raising=False)
    without_probe = [slide["title"] for slide in _generate(8)["slides"]]

    monkeypatch.setenv(smart_generation.SMART_SALVAGE_PROBE_ENV, "1")
    with_probe = [slide["title"] for slide in _generate(8)["slides"]]

    assert with_probe == without_probe


def test_salvage_probe_reports_the_valid_slides_behind_the_failure(
    monkeypatch, caplog
):
    """Slide 3 of 8 fails, so slides 4-8 arrive behind it and are all valid:
    5 downstream slides that the retry currently discards."""
    _stalling_deck_stream(8, fail_at_index=2, monkeypatch=monkeypatch)
    monkeypatch.setenv(smart_generation.SMART_SALVAGE_PROBE_ENV, "1")

    with caplog.at_level("INFO", logger=smart_generation.LOGGER.name):
        _generate(8)

    probes = [r.getMessage() for r in caplog.records if "salvage-probe" in r.getMessage()]
    assert probes, "the probe must report what the failed attempt discarded"
    assert "failed_slide=3" in probes[0]
    assert "downstream_slides=5" in probes[0]
    assert "downstream_valid=5" in probes[0]


def test_salvage_probe_is_off_unless_explicitly_enabled(monkeypatch):
    """It costs a real render per discarded slide, so it must never run by
    accident in normal generation."""
    monkeypatch.delenv(smart_generation.SMART_SALVAGE_PROBE_ENV, raising=False)
    assert smart_generation._salvage_probe_enabled() is False
    monkeypatch.setenv(smart_generation.SMART_SALVAGE_PROBE_ENV, "0")
    assert smart_generation._salvage_probe_enabled() is False
    monkeypatch.setenv(smart_generation.SMART_SALVAGE_PROBE_ENV, "1")
    assert smart_generation._salvage_probe_enabled() is True


def test_prompts_state_the_usable_content_height_not_just_coordinates():
    """Measured failure mode: three real e& generations died repeatedly at a
    constant *exactly 48px* overflow. Reproduced synthetically - a content
    block sized for the full 720px canvas and then placed after the 48px top
    offset ends at y=768, overflowing by precisely the offset. The prompts gave
    the content area only as coordinates (y=48 to y=630), never as a usable
    height, so the model honoured the offset and still sized for 720px."""
    common = dict(
        content="Build a strategy deck",
        n_slides=2,
        language="English",
        tone=None,
        verbosity=None,
        instructions=None,
        include_title_slide=True,
        include_table_of_contents=False,
        source_context="",
        community_design_context="",
    )

    eand_prompt = str(get_smart_messages(**common, smart_template="eand")[1].content)
    assert "582px of" in eand_prompt
    assert "NOT the full 720px" in eand_prompt
    assert "h-[720px]" in eand_prompt

    general_prompt = str(get_smart_messages(**common)[1].content)
    assert "subtracted from the canvas, not added to it" in general_prompt
    assert "672px" in general_prompt
    assert "h-screen" in general_prompt


# ---------------------------------------------------------------------------
# Scale-to-fit: overflow is made impossible rather than judged. The render that
# already measures the overflow also gives the exact content height, so the
# scale that makes it fit is known for free - no extra render, no extra LLM
# call, and (unlike the waiver path) nothing is clipped away.
# ---------------------------------------------------------------------------


def test_deep_overflow_still_raises_instead_of_shrinking_illegibly(
    monkeypatch, tmp_path
):
    """Scaling is for near-misses. Content far too tall would have to shrink
    enough to hurt legibility, so below SMART_MIN_FIT_SCALE it stays the
    model's problem and goes through the normal retry path."""
    width = smart_generation.SMART_OVERFLOW_SAFE_AREA_WIDTH
    canvas = smart_generation.SMART_SLIDE_CANVAS_HEIGHT
    image = Image.new(
        "RGB",
        (width, smart_generation.SMART_OVERFLOW_MEASURE_HEIGHT),
        smart_generation._SMART_OVERFLOW_SENTINEL_RGB,
    )
    for x in range(width):
        for y in range(canvas):
            image.putpixel((x, y), smart_generation._EAND_FOOTER_BACKGROUND_RGB)
    # 300px past the canvas -> needs 720/1020 = 0.71, well under the floor.
    for x in range(width):
        for y in range(canvas, canvas + 300):
            image.putpixel((x, y), (10, 20, 30))
    path = tmp_path / "deep_overflow.png"
    image.save(path)
    _patch_render(monkeypatch, str(path), {"n": 0})

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            smart_generation._check_smart_slide_layout(
                _smart_slide_html(), check_eand_footer=False
            )
        )
    assert "taller than the fixed" in excinfo.value.detail


def test_scaled_slide_wrapper_preserves_the_absolute_positioning_context():
    """A transformed element becomes the containing block for its
    absolutely-positioned descendants, so the wrapper must mirror the root
    section's box exactly - otherwise every `absolute`/`bottom-*` element in
    the slide silently re-anchors to a different rectangle."""
    html = _smart_slide_html(body='<div class="absolute bottom-0">Footer</div>')

    scaled = smart_generation._slide_html_scaled_to_fit(html, 0.9)

    assert 'transform:scale(0.9000)' in scaled
    assert "transform-origin:top center" in scaled
    # Same box as the section it sits inside.
    assert "position:relative" in scaled
    assert f"width:{smart_generation.SMART_OVERFLOW_SAFE_AREA_WIDTH}px" in scaled
    assert f"height:{smart_generation.SMART_SLIDE_CANVAS_HEIGHT}px" in scaled
    # The slide's own content survives, and the root section is still the root.
    assert '<div class="absolute bottom-0">Footer</div>' in scaled
    assert scaled.startswith("<section")
    assert scaled.rstrip().endswith("</section>")
    # The root's own fixed height and clip are untouched - transforms do not
    # affect layout, so the canvas box must stay exactly as it was.
    root_open = scaled.split(">", 1)[0]
    assert "h-[720px]" in root_open
    assert "overflow-hidden" in root_open


def test_scaled_slide_html_is_what_gets_accepted(monkeypatch):
    """The scale must reach the persisted slide - measuring it and then keeping
    the original HTML would fix nothing."""

    async def fake_layout_check(html, *, check_eand_footer=False):
        return 0.9 if "data-smart-fit-scale" not in html else None

    monkeypatch.setattr(
        smart_generation, "_check_smart_slide_layout", fake_layout_check
    )
    _stalling_deck_stream(3, fail_at_index=None, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        smart_generation, "_check_smart_slide_layout", fake_layout_check
    )
    monkeypatch.delenv(smart_generation.SMART_SALVAGE_PROBE_ENV, raising=False)

    result = _generate(3)

    assert len(result["slides"]) == 3
    for slide in result["slides"]:
        assert 'data-smart-fit-scale="0.9000"' in slide["html"]


def test_prompt_warns_against_outside_anchored_pie_donut_labels_that_clip():
    """Root cause of a real reported bug: pie/donut slice labels rendered
    partially or fully off the edge of the canvas (e.g. "Organic" showing as
    "Orga\\n45%") because the only Chart.js datalabels example in this prompt
    used anchor:'end'/align:'end' - correct for a bar chart's outside-the-
    axis label, but unsafe for a pie/donut slice, which can point straight at
    the canvas edge in any direction. A canvas clips at its own pixel
    boundary with no overflow to fall back on, so an outside label there is
    silently gone, not just crowded - worse still when the formatter also
    concatenates the category name onto the value, since a slide's existing
    legend/list already shows that name."""
    messages = get_smart_messages(
        content="Build a marketing report",
        n_slides=4,
        language="English",
        tone=None,
        verbosity=None,
        instructions=None,
        include_title_slide=True,
        include_table_of_contents=False,
        source_context="",
        community_design_context="",
    )
    prompt = str(messages[1].content)

    assert "DIFFERENT datalabel setup than bar charts" in prompt
    assert "clipped by the canvas boundary" in prompt
    assert "keep the on-slice datalabel to the value alone" in prompt
    assert "anchor: 'center'" in prompt
    assert "align: 'center'" in prompt


def test_prompt_forbids_conditionally_blanking_pie_donut_slice_labels():
    """Real reported bug: a pie chart's own generated formatter,
    `(v) => v >= 10 ? v + '%' : ''`, silently deleted the smallest slice's
    on-chart label (5% of 5) while every other slice kept its label -
    confirmed by live reproduction on the exact deck that surfaced it, not
    just a static reading. The model added this threshold on its own; the
    prior pie/donut guidance never asked for it and never forbade it."""
    messages = get_smart_messages(
        content="Build a marketing report",
        n_slides=4,
        language="English",
        tone=None,
        verbosity=None,
        instructions=None,
        include_title_slide=True,
        include_table_of_contents=False,
        source_context="",
        community_design_context="",
    )
    prompt = str(messages[1].content)

    assert "empty string for" in prompt
    assert "small values" in prompt
    assert "unconditionally" in prompt


def test_prompt_forbids_fixed_height_title_header_rows():
    """Real reported bug: a slide's own title/subtitle header row had a
    hard-coded `h-[72px]`. The title text was long enough to wrap to two
    lines at its actual rendered width, and the fixed height had no room for
    the second line plus the subtitle - they visually overlapped instead of
    the row growing taller. Confirmed by live reproduction on the exact
    reported slide, matching the screenshot pixel-for-pixel."""
    messages = get_smart_messages(
        content="Build a marketing report",
        n_slides=4,
        language="English",
        tone=None,
        verbosity=None,
        instructions=None,
        include_title_slide=True,
        include_table_of_contents=False,
        source_context="",
        community_design_context="",
    )
    prompt = str(messages[1].content)

    assert "title/header row" in prompt
    assert "can wrap to two lines" in prompt
    assert "never give that row a fixed pixel height" in prompt
