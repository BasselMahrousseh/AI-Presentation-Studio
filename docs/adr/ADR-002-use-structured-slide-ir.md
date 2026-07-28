# ADR-002: Use a Structured Slide Intermediate Representation

**Status:** Accepted

## Decision
Models produce schema-valid `DeckBrief`, `DeckPlan`, `SlideSpec` and `QAReport` objects. Deterministic services translate the IR into PPTX objects.

## Consequences
Model output cannot directly modify OOXML. Stable object IDs enable minimal repair, versioning and testing.
