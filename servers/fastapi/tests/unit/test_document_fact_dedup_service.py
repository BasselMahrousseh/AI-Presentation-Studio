import asyncio
from typing import List, Tuple

import pytest

from models.document_facts import AtomicFact
from models.pptx_chart_data import ExtractedChart, ExtractedChartSeries, PptxStructuredData
from services import document_fact_dedup_service as dedup


# ---------------------------------------------------------------------------
# _strip_chart_data_block
# ---------------------------------------------------------------------------


def test_strip_chart_data_block_removes_appended_chart_markdown():
    text = (
        "Some real prose extracted from the slide.\n\n"
        '### Native chart data extracted from "deck.pptx" '
        "(exact values from the source file's embedded chart data — reuse verbatim, do not re-estimate)\n"
        "**Revenue** — bar\nCategories: Q1, Q2\n- Series A: 10, 20"
    )

    stripped = dedup._strip_chart_data_block(text)

    assert stripped == "Some real prose extracted from the slide."
    assert "Native chart data extracted" not in stripped


def test_strip_chart_data_block_is_a_noop_when_no_marker_present():
    text = "Just plain prose, no chart block appended."

    assert dedup._strip_chart_data_block(text) == text


# ---------------------------------------------------------------------------
# _facts_from_structured_chart_data
# ---------------------------------------------------------------------------


def test_facts_from_structured_chart_data_builds_one_fact_per_series():
    structured = PptxStructuredData(
        charts=[
            ExtractedChart(
                source_file="deck.pptx",
                chart_part="ppt/charts/chart1.xml",
                title="Regional Revenue",
                raw_ooxml_type="barChart",
                extractable=True,
                categories=["North", "South"],
                series=[
                    ExtractedChartSeries(name="2025", values=[42.0, 35.0]),
                    ExtractedChartSeries(name="2026", values=[None, 40.0]),
                ],
            ),
            ExtractedChart(
                source_file="deck.pptx",
                chart_part="ppt/charts/chart2.xml",
                raw_ooxml_type="pieChart",
                extractable=False,
                categories=["A"],
                series=[ExtractedChartSeries(name="s", values=[1.0])],
            ),
        ]
    )

    facts = dedup._facts_from_structured_chart_data("deck.pptx", structured)

    assert len(facts) == 2
    assert all(f.priority == "chart_data" for f in facts)
    assert all(f.source_file == "deck.pptx" for f in facts)
    assert "North: 42" in facts[0].fact_text and "South: 35" in facts[0].fact_text
    # The None value for "North" in the 2026 series must be omitted, not
    # fabricated as 0 or "None".
    assert "South: 40" in facts[1].fact_text
    assert "North" not in facts[1].fact_text
    # Shape metadata is the chart's own shape (2 series, 2 categories) -
    # identical on both facts, since they come from the same chart.
    assert facts[0].chart_series_count == 2 and facts[0].chart_category_count == 2
    assert facts[1].chart_series_count == 2 and facts[1].chart_category_count == 2


def test_facts_from_structured_chart_data_returns_empty_for_none():
    assert dedup._facts_from_structured_chart_data("deck.pptx", None) == []


# ---------------------------------------------------------------------------
# _UnionFind
# ---------------------------------------------------------------------------


def test_union_find_merges_transitively():
    uf = dedup._UnionFind(4)
    uf.union(0, 1)
    uf.union(1, 2)

    assert uf.find(0) == uf.find(2)
    assert uf.find(3) != uf.find(0)


# ---------------------------------------------------------------------------
# _pick_canonical_index
# ---------------------------------------------------------------------------


def test_pick_canonical_prefers_chart_data_over_prose():
    facts = [
        AtomicFact(source_file="report.pdf", fact_text="Speed is about 245 Mbps.", priority="prose"),
        AtomicFact(source_file="deck.pptx", fact_text="Speed: 245", priority="chart_data"),
    ]

    assert dedup._pick_canonical_index(facts, [0, 1]) == 1


def test_pick_canonical_prefers_longer_text_when_priority_ties():
    facts = [
        AtomicFact(source_file="a.pdf", fact_text="Short fact.", priority="prose"),
        AtomicFact(source_file="b.pptx", fact_text="A much longer, more detailed fact statement.", priority="prose"),
    ]

    assert dedup._pick_canonical_index(facts, [0, 1]) == 1


def test_pick_canonical_breaks_ties_on_first_seen_index():
    facts = [
        AtomicFact(source_file="a.pdf", fact_text="Same length!", priority="prose"),
        AtomicFact(source_file="b.pptx", fact_text="Same length!", priority="prose"),
    ]

    assert dedup._pick_canonical_index(facts, [0, 1]) == 0


# ---------------------------------------------------------------------------
# _chart_shape_compatible - the Part A over-merging fix
# ---------------------------------------------------------------------------


def test_chart_shape_compatible_blocks_charts_with_different_series_counts():
    country_average = AtomicFact(
        source_file="deck.pptx",
        fact_text="France - Jan: 388.5; Feb: 387.4",
        priority="chart_data",
        chart_series_count=6,
        chart_category_count=6,
    )
    per_isp_breakdown = AtomicFact(
        source_file="deck.pptx",
        fact_text="FranceISP2 - 5 / France / Jan: 384.7; 5 / France / Feb: 382.7",
        priority="chart_data",
        chart_series_count=21,
        chart_category_count=36,
    )

    assert dedup._chart_shape_compatible(country_average, per_isp_breakdown) is False


def test_chart_shape_compatible_blocks_charts_with_same_series_but_different_category_count():
    a = AtomicFact(
        source_file="deck.pptx", fact_text="x", priority="chart_data",
        chart_series_count=3, chart_category_count=4,
    )
    b = AtomicFact(
        source_file="deck.pptx", fact_text="y", priority="chart_data",
        chart_series_count=3, chart_category_count=12,
    )

    assert dedup._chart_shape_compatible(a, b) is False


def test_chart_shape_compatible_allows_charts_with_identical_shape():
    a = AtomicFact(
        source_file="deck.pptx", fact_text="x", priority="chart_data",
        chart_series_count=6, chart_category_count=6,
    )
    b = AtomicFact(
        source_file="report.pptx", fact_text="y", priority="chart_data",
        chart_series_count=6, chart_category_count=6,
    )

    assert dedup._chart_shape_compatible(a, b) is True


def test_chart_shape_compatible_only_gates_chart_data_vs_chart_data_pairs():
    chart_fact = AtomicFact(
        source_file="deck.pptx", fact_text="x", priority="chart_data",
        chart_series_count=6, chart_category_count=6,
    )
    prose_fact = AtomicFact(source_file="report.pdf", fact_text="y", priority="prose")

    # A chart_data fact vs. a prose fact has no comparable chart shape to
    # check - the shape gate must not block this pairing, leaving it to
    # embedding similarity alone, unchanged from before this fix.
    assert dedup._chart_shape_compatible(chart_fact, prose_fact) is True
    assert dedup._chart_shape_compatible(prose_fact, prose_fact) is True


def test_chart_shape_compatible_defaults_to_true_when_shape_metadata_is_missing():
    a = AtomicFact(source_file="deck.pptx", fact_text="x", priority="chart_data")
    b = AtomicFact(
        source_file="deck.pptx", fact_text="y", priority="chart_data",
        chart_series_count=6, chart_category_count=6,
    )

    assert dedup._chart_shape_compatible(a, b) is True


def test_cluster_facts_by_similarity_blocks_a_mismatched_shape_merge_even_at_perfect_similarity(monkeypatch):
    """Reproduces the real Ookla bug shape directly: a country-aggregate
    fact and a per-ISP fact that read as near-identical text (forced to a
    perfect 1.0 similarity score here, worse than the real ~0.95 case) must
    still never cluster once their chart shapes differ."""

    class FakeVectorstore:
        def __init__(self, *_a, **_k):
            pass

        def embed_documents(self, _docs):
            return True

        def search(self, query, _n):
            # Every fact "matches" every other fact perfectly - the shape
            # gate is the only thing standing between this and a merge.
            return [(t, 1.0) for t in texts]

    facts = [
        AtomicFact(
            source_file="deck.pptx",
            fact_text="France - Jan: 388.5",
            priority="chart_data",
            chart_series_count=6,
            chart_category_count=6,
        ),
        AtomicFact(
            source_file="deck.pptx",
            fact_text="FranceISP2 - 5 / France / Jan: 384.7",
            priority="chart_data",
            chart_series_count=21,
            chart_category_count=36,
        ),
    ]
    texts = [f.fact_text for f in facts]
    monkeypatch.setattr(dedup, "FastembedVectorstore", FakeVectorstore)

    clusters = dedup._cluster_facts_by_similarity(facts, similarity_threshold=0.90)

    assert sorted([sorted(c) for c in clusters]) == [[0], [1]]


# ---------------------------------------------------------------------------
# build_deduplicated_context
# ---------------------------------------------------------------------------


def test_build_deduplicated_context_skips_pipeline_for_a_single_source(monkeypatch):
    monkeypatch.setattr(
        dedup,
        "_cluster_facts_by_similarity",
        lambda *_a, **_k: pytest.fail("clustering should not run for a single source"),
    )

    async def fail_extract(*_a, **_k):
        pytest.fail("LLM fact extraction should not run for a single source")

    monkeypatch.setattr(dedup, "extract_atomic_facts_from_text", fail_extract)

    result = asyncio.run(
        dedup.build_deduplicated_context(["only.pdf"], ["Just one document's text."], [None])
    )

    assert result == "Just one document's text."


def test_build_deduplicated_context_skips_pipeline_when_only_one_document_is_non_empty(monkeypatch):
    monkeypatch.setattr(
        dedup,
        "_cluster_facts_by_similarity",
        lambda *_a, **_k: pytest.fail("clustering should not run"),
    )

    result = asyncio.run(
        dedup.build_deduplicated_context(
            ["a.pdf", "b.pptx"], ["The only real content.", ""], [None, None]
        )
    )

    assert result == "The only real content."


def test_build_deduplicated_context_merges_near_duplicate_facts_across_sources(monkeypatch):
    async def fake_extract(text, source_file, **_kwargs):
        if source_file == "summary.pptx":
            return [
                AtomicFact(
                    source_file=source_file,
                    fact_text="UAE median download speed is 245 Mbps.",
                    topic="speed",
                    priority="prose",
                )
            ]
        return [
            AtomicFact(
                source_file=source_file,
                fact_text="In Q2 2026, the UAE's median fixed broadband download speed reached 245 Mbps.",
                topic="speed",
                priority="prose",
            ),
            AtomicFact(
                source_file=source_file,
                fact_text="Etisalat and du are the two main fixed broadband operators.",
                topic="operators",
                priority="prose",
            ),
        ]

    def fake_cluster(facts: List[AtomicFact], *, similarity_threshold: float) -> List[List[int]]:
        # facts[0] = summary.pptx speed fact, facts[1] = report.pdf speed
        # fact (paraphrase - same cluster), facts[2] = report.pdf operators
        # fact (distinct).
        return [[0, 1], [2]]

    monkeypatch.setattr(dedup, "extract_atomic_facts_from_text", fake_extract)
    monkeypatch.setattr(dedup, "_cluster_facts_by_similarity", fake_cluster)

    result = asyncio.run(
        dedup.build_deduplicated_context(
            ["summary.pptx", "report.pdf"],
            [
                "A" * 250 + " UAE median download speed is 245 Mbps.",
                "A" * 250 + " In Q2 2026, the UAE's median fixed broadband download speed reached 245 Mbps. Etisalat and du are the two main fixed broadband operators.",
            ],
            [None, None],
        )
    )

    # The paraphrase pair collapsed into one canonical fact (the longer of
    # the two, per _pick_canonical_index), and the distinct operators fact
    # survived untouched - overlap is gone, nothing real was dropped.
    assert result.count("median") == 1
    assert "245 Mbps" in result
    assert "Etisalat and du" in result


def test_build_deduplicated_context_prefers_chart_data_over_a_prose_paraphrase(monkeypatch):
    structured = PptxStructuredData(
        charts=[
            ExtractedChart(
                source_file="deck.pptx",
                chart_part="ppt/charts/chart1.xml",
                title="Download Speed",
                raw_ooxml_type="barChart",
                extractable=True,
                categories=["UAE"],
                series=[ExtractedChartSeries(name="Mbps", values=[245.0])],
            )
        ]
    )

    async def fake_extract(text, source_file, **_kwargs):
        assert "Native chart data extracted" not in text
        if source_file == "deck.pptx":
            return []
        return [
            AtomicFact(
                source_file=source_file,
                fact_text="UAE download speed is roughly 245 Mbps.",
                priority="prose",
            )
        ]

    def fake_cluster(facts: List[AtomicFact], *, similarity_threshold: float) -> List[List[int]]:
        assert len(facts) == 2
        return [[0, 1]]

    monkeypatch.setattr(dedup, "extract_atomic_facts_from_text", fake_extract)
    monkeypatch.setattr(dedup, "_cluster_facts_by_similarity", fake_cluster)

    chart_block = (
        '### Native chart data extracted from "deck.pptx" '
        "(exact values from the source file's embedded chart data — reuse verbatim, do not re-estimate)\n"
        "**Download Speed** — bar\nCategories: UAE\n- Mbps: 245"
    )
    result = asyncio.run(
        dedup.build_deduplicated_context(
            ["deck.pptx", "report.pdf"],
            [chart_block, "A" * 250 + " UAE download speed is roughly 245 Mbps."],
            [structured, None],
        )
    )

    assert "roughly" not in result
    assert '"Download Speed" - Mbps - UAE: 245' in result


def test_build_deduplicated_context_falls_back_to_raw_text_when_nothing_is_extracted(monkeypatch):
    async def fake_extract(*_a, **_k):
        return []

    monkeypatch.setattr(dedup, "extract_atomic_facts_from_text", fake_extract)

    result = asyncio.run(
        dedup.build_deduplicated_context(
            ["a.pdf", "b.pdf"],
            ["A" * 250 + " some real content here.", "A" * 250 + " more real content here."],
            [None, None],
        )
    )

    assert "some real content here" in result
    assert "more real content here" in result


def test_build_deduplicated_context_recovers_when_extraction_raises(monkeypatch):
    async def fake_extract(text, source_file, **_kwargs):
        if source_file == "broken.pdf":
            raise RuntimeError("LLM call failed")
        return []

    monkeypatch.setattr(dedup, "extract_atomic_facts_from_text", fake_extract)

    long_text = "A" * 250 + " content that could not be extracted into facts."
    result = asyncio.run(
        dedup.build_deduplicated_context(
            ["broken.pdf", "other.pdf"],
            [long_text, "A" * 250 + " other content."],
            [None, None],
        )
    )

    # A failed extraction must fall back to the raw text, never silently
    # drop the source's content.
    assert "content that could not be extracted" in result
    assert "other content" in result


def test_cluster_facts_by_similarity_short_circuits_for_zero_or_one_facts():
    assert dedup._cluster_facts_by_similarity([], similarity_threshold=0.9) == []

    fact = AtomicFact(source_file="a.pdf", fact_text="one fact", priority="prose")
    assert dedup._cluster_facts_by_similarity([fact], similarity_threshold=0.9) == [[0]]


def test_cluster_facts_by_similarity_uses_fastembed_and_merges_above_threshold(monkeypatch):
    class FakeVectorstore:
        def __init__(self, *_args, **_kwargs):
            pass

        def embed_documents(self, _docs):
            return True

        def search(self, query, _n):
            # Fact 0 and 1 are near-duplicates of each other; fact 2 is
            # distinct from both.
            table = {
                "dup one": [("dup one", 1.0), ("dup two", 0.95), ("distinct", 0.4)],
                "dup two": [("dup two", 1.0), ("dup one", 0.95), ("distinct", 0.4)],
                "distinct": [("distinct", 1.0), ("dup one", 0.4), ("dup two", 0.4)],
            }
            return table[query]

    monkeypatch.setattr(dedup, "FastembedVectorstore", FakeVectorstore)

    facts = [
        AtomicFact(source_file="a.pdf", fact_text="dup one", priority="prose"),
        AtomicFact(source_file="b.pdf", fact_text="dup two", priority="prose"),
        AtomicFact(source_file="c.pdf", fact_text="distinct", priority="prose"),
    ]

    clusters = dedup._cluster_facts_by_similarity(facts, similarity_threshold=0.9)

    cluster_sets = sorted([sorted(c) for c in clusters])
    assert cluster_sets == [[0, 1], [2]]


def test_cluster_facts_by_similarity_treats_every_fact_as_distinct_on_embed_failure(monkeypatch):
    class FailingVectorstore:
        def __init__(self, *_args, **_kwargs):
            pass

        def embed_documents(self, _docs):
            return False

        def search(self, *_a, **_k):
            pytest.fail("search should not run after a failed embed")

    monkeypatch.setattr(dedup, "FastembedVectorstore", FailingVectorstore)

    facts = [
        AtomicFact(source_file="a.pdf", fact_text="one", priority="prose"),
        AtomicFact(source_file="b.pdf", fact_text="two", priority="prose"),
    ]

    clusters = dedup._cluster_facts_by_similarity(facts, similarity_threshold=0.9)

    assert sorted([sorted(c) for c in clusters]) == [[0], [1]]
