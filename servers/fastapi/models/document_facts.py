from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# Higher priority always wins as the canonical fact within a cluster of
# near-duplicates. Chart data is a real, structured number pulled straight
# from a source file's own embedded data (see models/pptx_chart_data.py) and
# must never be displaced by an LLM's own prose paraphrase of the same fact.
FactPriority = Literal["chart_data", "prose"]

_PRIORITY_RANK: dict = {"chart_data": 1, "prose": 0}


class AtomicFact(BaseModel):
    source_file: str
    fact_text: str
    topic: str = ""
    priority: FactPriority = "prose"

    # Populated only for priority="chart_data" facts, from the shape of the
    # fact's *source chart* (not the one series this fact itself holds) -
    # how many series and categories the chart as a whole has. This lets
    # clustering apply a hard structural pre-filter: two charts with
    # meaningfully different shapes (e.g. 6 series vs. ~20 series) can never
    # be the same underlying measurement restated, no matter how similar
    # their rendered text looks (same country name, same month labels,
    # similar-magnitude numbers). See document_fact_dedup_service.py's
    # _chart_shape_compatible - this is what actually fixed the real
    # over-merging bug found on the Ookla pptx (a 6-series country-average
    # chart vs. a ~20-series per-ISP chart, both covering the same six
    # countries and months, embedding as near-duplicates of each other).
    chart_series_count: Optional[int] = None
    chart_category_count: Optional[int] = None


class AtomicFactLLM(BaseModel):
    """Schema for one fact as returned by the extraction LLM call - no
    source_file/priority fields, since those are attached by the caller
    (the LLM only ever sees one document at a time and has no reason to
    guess at values the caller already knows authoritatively)."""

    fact_text: str = Field(
        ...,
        description=(
            "One self-contained factual statement from the source text - a single "
            "number, claim, or finding. Keep the original wording's precision "
            "(exact figures, units, dates) rather than summarizing it away."
        ),
    )
    topic: str = Field(
        default="",
        description="A short topic label (2-5 words) grouping related facts, e.g. 'fixed broadband speed'.",
    )


class ExtractedFactsResponse(BaseModel):
    facts: List[AtomicFactLLM] = []


def fact_priority_rank(priority: FactPriority) -> int:
    return _PRIORITY_RANK.get(priority, 0)
