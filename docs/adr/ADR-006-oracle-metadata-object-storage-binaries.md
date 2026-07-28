# ADR-006: Store Metadata in Oracle and Binaries in Object Storage

**Status:** Accepted

## Decision
Store project, job, version, specification and audit metadata in Oracle 23ai. Store source files, PPTX, PDF, images and renders in enterprise object storage.

## Consequences
Database queries remain efficient, binary lifecycle is scalable and artefact retention can be managed independently.
