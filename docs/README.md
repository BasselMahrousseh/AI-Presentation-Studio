# e& AI Presentation Studio - Engineering Documentation

**Version:** 1.0 - Internal Engineering Baseline  
**Baseline date:** 27 July 2026  
**Status:** Engineering design and implementation baseline

This pack is the implementation source of truth for the e& AI Presentation Studio. The solution is developed and operated by the internal engineering team. It contains only engineering, implementation, security, quality and operational content.

## Authoritative order

1. Approved ADRs in `adr/`.
2. `project_spec.yaml`.
3. `api/openapi.yaml` and `schemas/`.
4. Numbered engineering documents.
5. `AGENTS.md`.
6. Tests.
7. Implementation.

A conflict must be resolved through an explicit specification update or ADR.

## Documents

| File | Purpose |
|---|---|
| `01_System_Requirements_and_Engineering_Scope.md` | Engineering scope, requirements, workflows and acceptance gates |
| `02_Solution_Architecture.md` | Components, service boundaries, runtime and technology baseline |
| `03_AI_Pipeline_and_Model_Strategy.md` | Model roles, prompts, structured output, grounding and QA |
| `04_Data_Model_and_Storage.md` | Oracle metadata, object storage, lineage, versioning and retention |
| `05_API_and_Event_Contracts.md` | REST, SSE, errors, idempotency and internal interfaces |
| `06_Template_and_PPTX_Engineering.md` | Internal template and PPTX composition engine design |
| `07_Security_Governance_and_Compliance.md` | Threat model, controls, audit and secure development |
| `08_Deployment_Operations_and_Observability.md` | Kubernetes, scaling, SLOs, monitoring and runbooks |
| `09_Testing_Quality_and_Acceptance.md` | Test pyramid, golden decks, visual regression and gates |
| `10_Implementation_Plan_and_Backlog.md` | Internal delivery phases, epics, team and risks |
| `AGENTS.md` | Unified instructions for all AI coding agents |

## Core implementation baseline

- Existing e& GenAI Workspace for UI, authentication and governance.
- FastAPI presentation API and durable orchestration workers.
- Internal TypeScript/Node.js PPTX composer using PptxGenJS behind internal contracts.
- Internal OOXML patch modules for reviewed feature gaps.
- Enterprise model gateway for reasoning, image, embedding and multimodal QA.
- Oracle 23ai for metadata and enterprise object storage for binaries.
- Redis or approved broker for ephemeral events and work queues.
- LibreOffice headless for automated rendering, validated against PowerPoint.

## Working rules

- Native editable PPTX is the primary output.
- Model output is never trusted until schema validation.
- Uploaded files are untrusted and processed in sandboxes.
- Deterministic checks run before multimodal review.
- Every mutation creates an immutable version and audit record.
- No public AI endpoint or unapproved network egress is allowed.
