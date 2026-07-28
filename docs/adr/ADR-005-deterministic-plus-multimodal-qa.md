# ADR-005: Combine Deterministic and Multimodal Quality Validation

**Status:** Accepted

## Decision
Run schema, geometry, package, font and data validation before multimodal visual inspection. Limit automated repair to bounded minimal patches.

## Consequences
Quality is repeatable and diagnosable; the visual model cannot directly rewrite a deck.
