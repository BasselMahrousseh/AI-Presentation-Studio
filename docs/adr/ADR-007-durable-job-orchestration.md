# ADR-007: Use Durable Multi-Stage Job Orchestration

**Status:** Accepted

## Decision
Represent generation as a persisted state machine with idempotent stage attempts, checkpoints, retries, cancellation and SSE progress events.

## Consequences
Generation survives process restarts and long-running work does not block API request threads.
