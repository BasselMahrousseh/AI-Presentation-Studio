from typing import List, Optional

from llmai import get_client
from llmai.shared import JSONSchemaResponse, Message, SystemMessage, UserMessage

from models.document_facts import AtomicFact, ExtractedFactsResponse
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.llm_config import get_llm_config
from utils.llm_provider import get_model
from utils.llm_utils import DisconnectChecker, generate_structured_with_schema_retries
from utils.schema_utils import prepare_schema_for_validation

# A document below this length has nothing worth running an extra LLM call
# over - the whole raw text is already short enough to hand the outline
# generator directly, and a near-empty document produces near-empty facts.
MIN_TEXT_LENGTH_FOR_FACT_EXTRACTION = 200

FACT_EXTRACTION_SYSTEM_PROMPT = """
You extract atomic, self-contained facts from a source document so they can be
compared and deduplicated against facts extracted from OTHER documents about
the same subject.

# Steps
1. Read the source text.
2. Identify individual factual statements - specific numbers, findings, claims,
   or comparisons. Ignore document chrome (headers, page numbers, table of
   contents entries, boilerplate captions) and any content that carries no
   real information on its own.
3. Split compound statements into separate atomic facts when they cover
   different topics, but do not split a single number away from the label or
   unit that makes it meaningful.
4. Preserve exact figures, units, dates, and names verbatim - never round,
   convert units, or paraphrase away precision.
5. Give each fact a short topic label so related facts can be grouped.

# Rules
- Output only facts that are actually present in the text. Never invent or
  infer a number that is not stated.
- Do not editorialize or add commentary not present in the source.
- Keep each fact to one sentence.
"""

FACT_EXTRACTION_USER_PROMPT = """
# SOURCE TEXT: START
{text}
# SOURCE TEXT: END
"""


def get_messages(text: str) -> List[Message]:
    return [
        SystemMessage(content=FACT_EXTRACTION_SYSTEM_PROMPT),
        UserMessage(content=FACT_EXTRACTION_USER_PROMPT.format(text=text)),
    ]


async def extract_atomic_facts_from_text(
    text: str,
    source_file: str,
    *,
    disconnect_checker: Optional[DisconnectChecker] = None,
) -> List[AtomicFact]:
    """Extract atomic, source-attributed facts from one document's raw text
    via a schema-constrained LLM call. Returns an empty list for text too
    short to be worth a call, or if the model returns nothing usable - never
    raises just because extraction came back empty, since the caller always
    has the original raw text to fall back on."""

    stripped = (text or "").strip()
    if len(stripped) < MIN_TEXT_LENGTH_FOR_FACT_EXTRACTION:
        return []

    client = get_client(config=get_llm_config())
    model = get_model()

    try:
        response_schema = prepare_schema_for_validation(
            ExtractedFactsResponse.model_json_schema(),
            strict=False,
        )
        response_format = JSONSchemaResponse(
            name="response",
            json_schema=response_schema,
            strict=False,
        )
        result = await generate_structured_with_schema_retries(
            client,
            model,
            messages=get_messages(stripped),
            response_format=response_format,
            json_schema=response_schema,
            strict=False,
            validate_schema=True,
            disconnect_checker=disconnect_checker,
        )
    except Exception as e:
        raise handle_llm_client_exceptions(e)

    parsed = ExtractedFactsResponse.model_validate(result)
    return [
        AtomicFact(
            source_file=source_file,
            fact_text=fact.fact_text.strip(),
            topic=fact.topic.strip(),
            priority="prose",
        )
        for fact in parsed.facts
        if fact.fact_text and fact.fact_text.strip()
    ]
