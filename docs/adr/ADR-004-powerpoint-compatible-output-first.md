# ADR-004: Prioritise PowerPoint-Compatible Output and Structured Workspace Editing

**Status:** Accepted

## Decision
Use Microsoft PowerPoint desktop as the primary full-fidelity editor for exported files. Implement only structured edit operations in the Workspace during the initial releases.

## Consequences
A full browser authoring suite is not a dependency for the core platform. Future add-ins or editors use the same internal APIs and immutable version model.
