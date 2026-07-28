# ADR-001: Extend the Existing GenAI Workspace

**Status:** Accepted

## Decision
Implement Presentation Studio as a module of the existing GenAI Workspace and reuse its identity, navigation, quotas, audit and UI standards.

## Consequences
Presentation-specific long-running work remains in dedicated backend services; no authoritative state is stored only in the browser.
