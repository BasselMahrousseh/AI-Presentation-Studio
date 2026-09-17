import asyncio
import logging
import os
from typing import Dict, List, Optional, Tuple

from fastembed_vectorstore import FastembedEmbeddingModel, FastembedVectorstore

from models.document_facts import AtomicFact, fact_priority_rank
from models.pptx_chart_data import PptxStructuredData
from utils.llm_calls.extract_atomic_facts import extract_atomic_facts_from_text
from utils.llm_utils import DisconnectChecker
from utils.path_helpers import get_writable_path

LOGGER = logging.getLogger(__name__)

# Cosine similarity at/above this is treated as the same underlying fact
# restated (a paraphrase across two source documents) rather than two
# genuinely distinct facts. Calibrated against a live fastembed spike: real
# paraphrase pairs scored ~0.95-0.98, genuinely distinct facts on the same
# broad topic scored ~0.55-0.70 - 0.90 sits well clear of both clusters.
#
# KNOWN LIMITATION #1 (under-merging), measured against the real two-file
# Ookla verification run this was built for, not merely theorized: a real
# cross-document duplicate - the pptx's "du and e& have approximately 95% of
# tests using on-net servers and approximately 5% using off-net servers" vs.
# the pdf's "Both UAE ISPs use on-net servers for ~95% of tests and off-net
# servers for only ~5%" - scored only 0.547, well under this threshold, and
# so was NOT merged. Lowering the threshold to catch pairs like this would
# also start merging genuinely distinct facts, which occupy the same
# ~0.55-0.70 range for this general-purpose small model (all-MiniLM-L6-v2)
# on numeric/entity-dense sentences. Accepted trade-off: a stray unmerged
# duplicate is human-catchable on a quick read and far preferable to wrongly
# merging two real, distinct facts.
#
# KNOWN LIMITATION #2 (over-merging - the more dangerous direction, found
# and fixed via a real end-to-end generation test, not caught by unit tests
# alone): the opposite failure is not "a duplicate slips through unmerged"
# but "two genuinely DIFFERENT real facts get merged, and the wrong one is
# silently kept" - indistinguishable from correct output by looking at the
# deck alone, unlike limitation #1's visible leftover duplicate. Found on
# the real Ookla pptx: a country-level-average chart (6 series, one line per
# country, chart4.xml) and a per-ISP breakdown chart (~20 series, one line
# per named operator, chart2.xml/chart3.xml) both cover the same six
# countries and the same Jan-Jun month labels, so a specific-ISP fact like
# "FranceISP2 - 5 / France / Jan: 384.676..." and the country-aggregate fact
# "France - Jan: 388.51..." embedded as near-duplicates (both real, but
# describing different measurements) and clustered together. The canonical-
# fact tie-break (prefer the longer text among equal-priority chart_data
# facts) then deterministically favored the per-ISP fact's more verbose
# category labels every time, silently discarding the real country-average
# number in favor of a real-but-wrong-for-this-context per-ISP number - for
# 5 of 6 countries. (UAE alone survived correctly, purely by naming-
# convention accident: its local operators are branded "Etisalat"/"Du," not
# "UAEISP1"/"UAEISP2," so they never shared enough text with the "UAE"
# aggregate fact to cluster in the first place - not something this fix
# should be credited for.)
#
# Fixed via a structural pre-filter, not a threshold change or an LLM
# verification pass: two chart_data facts can now only be considered for
# clustering at all if their source charts' series count AND category count
# match exactly (_chart_shape_compatible(), applied before the embedding-
# similarity check in _cluster_facts_by_similarity). A chart with 6 series/6
# categories and a chart with ~20 series/36 categories can never be the same
# measurement restated - that's a deterministic, knowable property of the
# chart's shape, not a judgment call worth spending a probabilistic
# similarity score (or another LLM's opinion) on. Verified against the real
# pptx: re-running clustering after the fix produces zero merges between
# chart4's country-aggregate facts and chart2/3's per-ISP facts for any of
# the six countries, including UAE - which now stays separate because its
# chart shape differs (6 vs. ~20 series), not because of the naming
# coincidence above.
FACT_DEDUP_SIMILARITY_THRESHOLD = 0.90

_CHART_BLOCK_MARKER_PREFIX = '### Native chart data extracted from "'


def _fastembed_cache_directory() -> str:
    override = (os.getenv("PRESENTON_FASTEMBED_FACT_DEDUP_CACHE_DIR") or "").strip()
    if override:
        path = os.path.abspath(override)
        os.makedirs(path, exist_ok=True)
        return path
    return get_writable_path("fastembed_cache")


def _strip_chart_data_block(document_text: str) -> str:
    """Remove the "### Native chart data extracted..." block DocumentsLoader
    appends to a pptx's own text (see serialize_pptx_structured_data_for_llm)
    before running LLM fact extraction on the remaining prose. The chart's
    real numbers are ingested directly as pre-structured, highest-priority
    facts via _facts_from_structured_chart_data - re-extracting them through
    a second, lossier LLM pass would only risk a paraphrased/rounded
    duplicate competing with the real value.
    """
    marker_index = document_text.find(_CHART_BLOCK_MARKER_PREFIX)
    if marker_index == -1:
        return document_text
    return document_text[:marker_index].rstrip()


def _facts_from_structured_chart_data(
    source_file: str, structured_data: Optional[PptxStructuredData]
) -> List[AtomicFact]:
    if structured_data is None:
        return []
    facts: List[AtomicFact] = []
    for chart in structured_data.charts:
        if not chart.extractable:
            continue
        title = chart.title or "Untitled chart"
        # Shape of the chart AS A WHOLE (not this one series) - a chart with
        # 6 series/6 categories and a chart with ~20 series/36 categories
        # are never the same measurement, regardless of how similar two of
        # their individual series happen to read as text.
        series_count = len(chart.series)
        category_count = len(chart.categories)
        for series in chart.series:
            pairs = [
                f"{category}: {value}"
                for category, value in zip(chart.categories, series.values)
                if value is not None
            ]
            if not pairs:
                continue
            fact_text = f'"{title}" - {series.name} - ' + "; ".join(pairs)
            facts.append(
                AtomicFact(
                    source_file=source_file,
                    fact_text=fact_text,
                    topic=title,
                    priority="chart_data",
                    chart_series_count=series_count,
                    chart_category_count=category_count,
                )
            )
    return facts


def _chart_shape_compatible(a: AtomicFact, b: AtomicFact) -> bool:
    """Hard structural pre-filter, applied before two facts are even allowed
    to be compared by embedding similarity: two chart_data facts whose
    source charts have a different series count or category count can never
    be the same measurement restated, so they must never cluster together -
    this is a deterministic property of the chart, not a judgment call.

    Deliberately narrow: only chart_data-vs-chart_data comparisons are
    gated. A chart_data fact vs. a prose fact (or two prose facts) has no
    comparable "chart shape" to check, so those pairs fall through to
    embedding similarity alone, unchanged from before this fix. A fact
    lacking shape metadata (defensively - every chart_data fact built by
    _facts_from_structured_chart_data always sets both fields) is treated
    as compatible rather than silently blocking a real merge.
    """
    if a.priority != "chart_data" or b.priority != "chart_data":
        return True
    if a.chart_series_count is None or b.chart_series_count is None:
        return True
    if a.chart_category_count is None or b.chart_category_count is None:
        return True
    return (
        a.chart_series_count == b.chart_series_count
        and a.chart_category_count == b.chart_category_count
    )


class _UnionFind:
    def __init__(self, n: int):
        self._parent = list(range(n))

    def find(self, i: int) -> int:
        while self._parent[i] != i:
            self._parent[i] = self._parent[self._parent[i]]
            i = self._parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        root_i, root_j = self.find(i), self.find(j)
        if root_i != root_j:
            self._parent[root_j] = root_i


def _cluster_facts_by_similarity(
    facts: List[AtomicFact], *, similarity_threshold: float
) -> List[List[int]]:
    """Group fact indices whose text is near-duplicate (cosine similarity
    at/above the threshold), via a fastembed-backed embedding + search,
    merged with union-find - the same merge-first-then-group shape as the
    overlapping-image-box fix in services/documents_loader.py.

    Before two facts are allowed to merge on similarity score alone, they
    must also pass _chart_shape_compatible() - a hard, deterministic
    pre-filter that blocks two chart_data facts from ever clustering when
    their source charts have a different series/category count. Embedding
    similarity alone cannot make this distinction: a specific-ISP's monthly
    series and a country-average's monthly series can read as near-identical
    text (same country name, same month labels, similar magnitude) while
    being two genuinely different real measurements - see the historical
    note in this module's known-limitation comment on FACT_DEDUP_SIMILARITY_
    THRESHOLD for the real case this was found against.
    """
    n = len(facts)
    if n <= 1:
        return [[i] for i in range(n)]

    vectorstore = FastembedVectorstore(
        FastembedEmbeddingModel.AllMiniLML6V2,
        cache_directory=_fastembed_cache_directory(),
    )
    texts = [fact.fact_text for fact in facts]
    if not vectorstore.embed_documents(texts):
        LOGGER.warning(
            "[document_fact_dedup] embedding failed - skipping similarity "
            "clustering, treating every fact as distinct"
        )
        return [[i] for i in range(n)]

    text_to_indices: Dict[str, List[int]] = {}
    for i, text in enumerate(texts):
        text_to_indices.setdefault(text, []).append(i)

    uf = _UnionFind(n)
    for i, text in enumerate(texts):
        for match_text, score in vectorstore.search(text, n):
            if score < similarity_threshold:
                continue
            for j in text_to_indices.get(match_text, []):
                if j != i and _chart_shape_compatible(facts[i], facts[j]):
                    uf.union(i, j)

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values())


def _pick_canonical_index(facts: List[AtomicFact], indices: List[int]) -> int:
    """Prefer real chart data over a prose paraphrase of the same fact;
    among equal priority, prefer the longer (more detailed) text; ties break
    on first-seen index for determinism."""
    return max(
        indices,
        key=lambda i: (fact_priority_rank(facts[i].priority), len(facts[i].fact_text), -i),
    )


async def _process_source(
    file_path: str,
    document_text: str,
    structured_data: Optional[PptxStructuredData],
    disconnect_checker: Optional[DisconnectChecker],
) -> Tuple[List[AtomicFact], Optional[str]]:
    source_file = os.path.basename(file_path)
    chart_facts = _facts_from_structured_chart_data(source_file, structured_data)
    prose_text = _strip_chart_data_block(document_text)

    prose_facts: List[AtomicFact] = []
    if prose_text.strip():
        try:
            prose_facts = await extract_atomic_facts_from_text(
                prose_text, source_file, disconnect_checker=disconnect_checker
            )
        except Exception:
            LOGGER.exception(
                "[document_fact_dedup] fact extraction failed for source_file=%s - "
                "falling back to its raw text unmerged",
                source_file,
            )
            prose_facts = []

    fallback_text: Optional[str] = None
    if prose_text.strip() and not prose_facts and not chart_facts:
        # Nothing extracted (too short for a call, or extraction failed/
        # returned nothing) and no structured chart data either - keep the
        # raw text verbatim rather than silently dropping this source.
        fallback_text = f'### Content from "{source_file}"\n{prose_text}'

    return chart_facts + prose_facts, fallback_text


async def build_deduplicated_context(
    file_paths: List[str],
    documents: List[str],
    structured_pptx_data: List[Optional[PptxStructuredData]],
    *,
    disconnect_checker: Optional[DisconnectChecker] = None,
    similarity_threshold: float = FACT_DEDUP_SIMILARITY_THRESHOLD,
) -> str:
    """Replace blind "\\n\\n".join(documents) concatenation with a real
    cross-document merge: extract atomic, source-attributed facts from each
    document (pptx chart data is ingested directly as pre-structured,
    highest-priority facts rather than re-extracted via LLM), cluster
    near-duplicate facts across sources by embedding similarity, and keep
    one canonical version per cluster.
    """
    non_empty_count = sum(1 for doc in documents if doc)
    if non_empty_count <= 1:
        # Nothing to deduplicate against with only one (or zero) real
        # source - skip the extra LLM/embedding cost entirely for the
        # common single-file case, and behave exactly as before.
        return "\n\n".join(doc for doc in documents if doc)

    results = await asyncio.gather(
        *(
            _process_source(file_path, document_text, structured_data, disconnect_checker)
            for file_path, document_text, structured_data in zip(
                file_paths, documents, structured_pptx_data
            )
            if document_text
        )
    )

    all_facts: List[AtomicFact] = []
    fallback_texts: List[str] = []
    for facts, fallback_text in results:
        all_facts.extend(facts)
        if fallback_text:
            fallback_texts.append(fallback_text)

    if not all_facts:
        return "\n\n".join(fallback_texts) if fallback_texts else "\n\n".join(
            doc for doc in documents if doc
        )

    clusters = _cluster_facts_by_similarity(
        all_facts, similarity_threshold=similarity_threshold
    )
    canonical_facts = [
        all_facts[_pick_canonical_index(all_facts, indices)] for indices in clusters
    ]

    chart_lines = [
        f"- [{fact.source_file}] {fact.fact_text}"
        for fact in canonical_facts
        if fact.priority == "chart_data"
    ]
    prose_lines = [
        f"- [{fact.source_file}] {fact.fact_text}"
        for fact in canonical_facts
        if fact.priority != "chart_data"
    ]

    sections: List[str] = []
    if chart_lines:
        sections.append(
            "### Structured chart data merged across all sources "
            "(exact values from source files - reuse verbatim, do not re-estimate)\n"
            + "\n".join(chart_lines)
        )
    if prose_lines:
        sections.append(
            "### Facts merged across all sources (overlap between sources removed)\n"
            + "\n".join(prose_lines)
        )
    sections.extend(fallback_texts)

    LOGGER.info(
        "[document_fact_dedup] sources=%s raw_facts=%s clusters=%s chart_facts=%s "
        "prose_facts=%s fallback_sources=%s",
        non_empty_count,
        len(all_facts),
        len(clusters),
        len(chart_lines),
        len(prose_lines),
        len(fallback_texts),
    )

    return "\n\n".join(sections)
