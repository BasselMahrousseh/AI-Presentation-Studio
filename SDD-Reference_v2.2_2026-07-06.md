Solution Design Document (SDD) — Reference Standard
Version: 2.2 · Maintainer: Enterprise Architecture — AI Solutions · Scope: Enterprise AI / GenAI solutions · Last Updated: 2026-07-06 Companion: SDD-AI-Instructions_v2.2_2026-07-06.md — how an AI assistant generates an SDD. This file defines what an SDD must contain; the companion defines how to produce it. Neither restates the other. Lighter-weight alternative: if only the core technical artifacts are needed (API docs, sequence diagrams, DB schema) rather than a full SDD, use SDD-Minimal-Instructions_v1.0_2026-07-06.md instead — it is self-contained and does not require this file. Changes from v2.1: fixed the Lightweight tier so it includes Sequence Diagrams (§8); §6.2 now requires deployable DDL alongside the ERD; added the Minimal mode as an explicit fourth tier option; added cross-link to the Minimal Instructions.
Purpose
Canonical structure, content requirements, and quality bar for every SDD produced by the AI Solutions Architecture team. Any deviation from this standard is documented in the Appendix with rationale.
Document Tiers
Select the tier before writing. If criteria span tiers, take the highest matching tier. Any section may still be marked N/A with a one-line rationale.
Criterion	Minimal	Lightweight	Standard	Full
Use case	Core technical spec only, no full SDD needed	Internal team tool	Department / single LOB	Enterprise-wide or customer-facing
Data sensitivity	n/a	Public / internal	Confidential	PII or regulated data
AI autonomy	n/a	Assist — human executes	Acts with human approval	Autonomous actions
EU AI Act class	n/a	Minimal risk	Limited risk	High risk
Required sections	See SDD-Minimal-Instructions_v1.0_2026-07-06.md	1, 2, 4, 5, 8, 9, 16	1–14, 16, 17 (3 & 15 if migrating)	All 18
Minimal is not a subset of this document's section numbering — it produces a separate, shorter deliverable per its own instructions file. Use it when the requester explicitly asks for API documentation, sequence diagrams, and/or DB schema only.
Document Metadata
Every SDD begins with: Title (SDD — <Solution Name>), Version (semver), Status (Draft · In Review · Approved · Superseded), Author(s), Reviewers (+ status), Approval Authority, Classification (Public · Internal · Confidential · Restricted), Created / Last Modified (ISO 8601), Related Documents (PRD, BRD, ADRs), and a Change Log table (version, date, author, summary).
Section Reference
1. Executive Summary
Any reader — technical or executive — understands the solution in under two minutes.
Business Problem Statement — the business pain or opportunity, written from the business's perspective.
Solution Overview — one paragraph (3–5 sentences), jargon-free: what it does, which AI capabilities it uses, how it fits the enterprise landscape.
Key Stakeholders — names, roles, interest (RACI).
Expected Outcomes & Success Metrics — quantified KPIs measured post-launch.
Done when: a non-technical VP can explain what is being built, why, and how success is measured.
2. Scope and Constraints
In-Scope Capabilities — numbered list for this version.
Out-of-Scope — each item marked deferred to future phase or permanently excluded.
Assumptions — conditions the design depends on.
Regulatory Constraints — applicable regulations (GDPR, HIPAA, SOC 2, internal AI governance) and the solution's EU AI Act risk classification (prohibited / high / limited / minimal) with justification — this drives the document tier.
Technology Constraints, Data Residency, Budget Envelope, Timeline Constraints.
Done when: every constraint traces to a source (regulation, policy, or stakeholder decision).
3. Current State Assessment
Existing Systems Landscape — systems this solution interacts with or replaces (versions, ownership).
Current Process — how the business does this today; flow diagram if >3 steps.
Pain Points — specific and measurable.
Data Sources & Readiness — format, quality, volume, refresh frequency, known issues.
Infrastructure Baseline.
Greenfield: state so, and describe the target baseline instead.
Done when: grounded in actual discovery (interviews, audits, profiling) — not assumptions.
4. Solution Architecture
The primary artifact reviewers evaluate.
4.1 High-Level Solution Diagram — single diagram, C4 Container level (or UML Component): all components, data stores, external systems, entry points, network boundaries. Every box: label + responsibility + hosting environment. Legend required.
4.2 AI Component Architecture — model serving (incl. gateway/router if multi-model), orchestration layer, vector store, prompt management, fine-tuning/training infra if applicable.
4.3 Integration Architecture — synchronous (REST/gRPC + latency expectations), asynchronous (queues, events, webhooks), batch pipelines, patterns used (API Gateway, BFF, CQRS, …).
4.4 Infrastructure & Deployment Topology — regions/AZs, network layout, cluster topology, CDN/LB/DNS, managed vs. self-hosted with rationale.
4.5 Multi-Tenancy Model (if applicable) — isolation strategy, tenant configuration boundaries, data isolation guarantees.
Done when: the diagram is understandable without the surrounding text, and every component reappears in Section 7, 8, or 9.
5. AI/ML Design Details
What separates an AI SDD from a generic one. Every choice carries a rationale.
5.1 Model Selection — provider, model ID, version; selection criteria (quality, latency, cost, compliance, context window); alternatives rejected and why; provider deprecation / upgrade plan.
5.2 Prompt & Fine-Tuning Strategy — design approach (zero/few-shot, CoT, tool use); prompt storage, versioning, testing, deployment; structured-output enforcement (JSON schema, function calling); system prompt architecture; fine-tuning dataset/method/eval if applicable.
5.3 Agentic Architecture (if applicable) —
Agent topology (single, multi-agent, orchestrator–worker) and framework.
Tool inventory — each tool's purpose, permissions, and side-effect class (read / write / irreversible).
MCP servers and tool integration contracts.
Memory and state (conversation, long-term, shared between agents).
Autonomy boundaries — actions the agent takes unilaterally vs. with human approval; spend and iteration limits.
Failure containment — max iterations, timeouts, rollback of agent-initiated actions.
5.4 RAG Architecture (if applicable) — ingestion pipeline (source → chunking → embedding → indexing); chunking method/size/overlap with rationale; embedding model + dimensionality; retrieval strategy (similarity, hybrid, re-ranking); context assembly; index refresh/sync strategy.
5.5 Guardrails & Safety — input validation and prompt-injection defenses; output filtering (PII, toxicity, groundedness); content moderation layer; human-in-the-loop escalation criteria; responsible AI compliance (bias testing, fairness metrics).
5.6 Evaluation & Quality — eval datasets and benchmarks; metrics tracked; frequency (per-deploy, scheduled, continuous); regression thresholds.
5.7 Fallback & Degradation — failover model, cached responses, graceful degradation, circuit breaker configuration.
Done when: reviewable by an ML engineer who was not involved in the design; no choice without a why.
6. Data Architecture
6.1 Data Flow Diagram — source → ingestion → transformation → storage → serving → archival; PII locations and where masked/encrypted/removed clearly marked.
6.2 Data Model — a required Entity-Relationship Diagram (Crow's Foot notation): every persisted entity, its key attributes and types, primary/foreign keys, and the cardinality of each relationship. Vector store schema (metadata fields, indexing) modeled alongside or as a companion entity. Must be accompanied by deployable schema definitions (DDL) — CREATE TABLE statements (or NoSQL collection/index definitions) covering columns/types, constraints (PK, FK, unique, not-null, checks), indexes, and defaults — so the schema can be created directly from the SDD, not just visualized.
6.3 Lineage & Transformation — pipeline logic, quality checks per stage, pipeline dependency graph.
6.4 PII Handling & Classification — classification scheme, PII inventory, anonymization/pseudonymization/tokenization methods.
6.5 Retention & Archival — periods per data class, archival strategy, right-to-erasure implementation.
Done when: a data engineer can build the pipelines and create the database from this section alone.
7. Flow Diagrams
7.1 User Journey Flows — trigger to outcome, with decision points.
7.2 System Interaction Flows — component invocation order per journey.
7.3 Error & Exception Flows — timeout, model failure, invalid input, rate limit.
7.4 Admin / Operations Flows — retraining, prompt updates, data refresh, access provisioning, incident response.
Requirements: consistent notation (BPMN 2.0 or simple flowchart); defined start and end events; both branches at every decision; swimlanes when >1 actor.
Done when: happy paths plus top 3 failure paths covered; QA can derive test cases directly.
8. Sequence Diagrams
One of the three core technical artifacts (with §6.2 and §9) — required from the Lightweight tier up.
Required diagrams:
8.1 Primary User Request — the most common interaction, end to end.
8.2 Authentication & Authorization — login, token refresh, permission checks.
8.3 RAG / Retrieval Pipeline (if applicable).
8.4 Agent Tool-Use Loop (if applicable) — reasoning → tool call → result → next action, including the approval path for guarded actions.
8.5 Asynchronous Processing (if queues/events exist).
8.6 Error Handling & Retry — timeout, backoff, circuit breaker, fallback.
Requirements: UML sequence notation (Mermaid acceptable); alt/opt/loop fragments where conditional; latency annotations on sensitive calls; solid arrows sync, dashed async.
Done when: a developer can implement from the diagram alone; every participant exists in Section 4.
9. API Design and Documentation
One of the three core technical artifacts (with §6.2 and §8).
9.1 Inventory — table: method, path, summary, auth, rate limit; plus versioning strategy.
9.2 Endpoint Specifications — OpenAPI 3.1 (inline or referenced); request/response schemas with examples; required vs. optional fields, validation rules, defaults.
9.3 Error Contract — standard error schema; error code registry (code, HTTP status, description, client action).
9.4 AuthN/AuthZ — mechanism (OAuth 2.0, API key, mTLS, JWT); token lifecycle; scope model mapped to endpoints.
9.5 Rate Limiting — limits per tier, throttling behavior (429 + retry-after), burst policy.
9.6 Gateway Configuration — routing, transformations, CORS, size limits.
Done when: an integration developer can build a client without asking questions.
10. Security and Compliance
10.1 Identity & Access — IdP integration, RBAC/ABAC permission matrix, service-to-service auth.
10.2 Encryption — at rest (algorithm, key management), in transit (TLS version, cert management), in use if applicable.
10.3 Network Security — segmentation, private endpoints, WAF, DDoS, zero-trust elements.
10.4 AI-Specific Threats — map against OWASP LLM Top 10. Minimum coverage: prompt injection (direct and indirect via retrieved/tool content); data leakage through outputs; excessive agency — tool misuse by agents, scope of unattended actions; model extraction; training-data poisoning (if fine-tuning); supply chain (third-party models, MCP servers, plugins).
10.5 Audit & Logging — what is logged (access, data changes, model invocations, agent actions, admin operations), retention, immutability.
10.6 Compliance Mapping — table: each regulation/standard (incl. EU AI Act obligations for the classification in Section 2) → the specific control satisfying it.
Done when: a security architect can run a threat-model review from this section; every AI threat has a mitigation.
11. Performance and Scalability
11.1 Load Profile — concurrent users, RPS, token throughput; peak vs. steady state; 6/12-month growth.
11.2 Latency Targets — end-to-end P50/P95/P99 plus per-component budgets (gateway, orchestrator, retrieval, model).
11.3 Scalability Strategy — horizontal vs. vertical per component; auto-scaling triggers and limits; bottlenecks and mitigations.
11.4 Caching — semantic cache, response cache, embedding cache, provider-side prompt caching; invalidation strategy.
Capacity assumptions from this section feed the cost model in Section 17 — do not duplicate cost figures here.
Done when: every latency target has a corresponding load-test scenario in Section 14.
12. Observability and Operations
12.1 Logging — structured format with correlation IDs; levels; aggregation platform.
12.2 Monitoring & Alerting — infra, application, and AI metrics (token usage, model latency, cost per request, quality scores); thresholds and escalation paths.
12.3 AI Observability — drift detection, feedback-loop instrumentation, prompt-version performance, hallucination-rate monitoring, agent trajectory tracing (full tool-call chains per request).
12.4 Dashboards — list with audience and key metrics each.
12.5 SLOs / SLIs / SLAs — objectives for availability, latency, error rate; how each is measured; external commitments.
12.6 Runbooks — common failure scenarios with resolution steps; escalation matrix; on-call model.
Done when: an on-call engineer unfamiliar with the system can diagnose a production issue from this section and its dashboards alone.
13. Deployment and DevOps
13.1 CI/CD Pipeline — stages (build → test → security scan → staging → approval → production), triggers, tools.
13.2 Environments — list, parity requirements, environment-specific config.
13.3 Deployment Strategy — blue/green, canary, rolling, or flag-based; rollback triggers and procedure; zero-downtime requirements.
13.4 Infrastructure as Code — tool, module structure, state management, drift detection.
13.5 Model & Prompt Versioning — how model and prompt versions are tracked and deployed (independently of code if applicable); A/B or shadow deployment for changes.
Done when: a DevOps engineer can build the complete pipeline from this section.
14. Testing Strategy
14.1 Test Levels — unit (coverage target, mocking strategy), integration, end-to-end, contract.
14.2 AI Testing — eval dataset composition and maintenance (versioned with the code); regression benchmarks with thresholds; adversarial/red-team testing (prompt injection, jailbreaks, agent misuse scenarios); bias and fairness testing.
14.3 Performance & Load — scenarios (steady, peak, stress, soak); tools; pass/fail tied to Section 11 targets.
14.4 Security Testing — SAST, DAST, dependency scanning, pen-test schedule, AI-specific security tests.
14.5 UAT — criteria, sign-off process, environment and data requirements.
Done when: every test traces to a requirement (Section 2) or risk (Section 16).
15. Migration and Rollout Plan
15.1 Phased Rollout — pilot → limited GA → full GA; advancement criteria and rollback triggers per phase.
15.2 Feature Flags — tool, granularity (user/tenant/percentage), cleanup plan.
15.3 Data Migration (if applicable) — scripts and order, pre/post validation, rollback procedure.
15.4 Cutover — steps with owners and durations, communication plan, go/no-go checklist.
15.5 Training & Enablement — user training, support enablement, documentation delivery.
Done when: explicit rollback exists for every phase; a PM can build a project plan from this section.
16. Risks and Mitigations
Risk register table:
ID	Category	Risk	Likelihood	Impact	Severity	Mitigation	Owner	Status
Required categories: Technical (accuracy, vendor lock-in, latency, integration fragility) · Operational (cost overrun, scaling limits, on-call burden) · AI-Specific (hallucination, bias, prompt injection, excessive agency, model deprecation, regulatory change) · Data (quality, PII exposure, pipeline failure) · Organizational (staffing, skills, alignment).
Done when: every High-severity risk has a mitigation and an owner; AI risks have their own category, never lumped into "Technical."
17. Cost Estimation
17.1 Infrastructure — compute, storage, networking, managed services (monthly).
17.2 AI / Model Costs — token usage, fine-tuning, embedding generation — always a separate, visible line item.
17.3 Licensing — third-party software, SaaS.
17.4 Operational — monitoring tools, support, on-call.
17.5 TCO — 12- and 36-month horizons; sensitivity analysis at 2× and 5× projected volume.
17.6 Optimization Levers — prompt caching, batch APIs, model routing (downgrade low-complexity tasks to cheaper models), semantic caching, reserved capacity.
Done when: assumptions are explicit and the math is auditable; AI cost is never buried in "compute."
18. Appendix
Glossary · ADRs (context, options, rationale) · Open Questions (owner + target date) · Assumptions Log (with validation status) · Reference Documents · Diagram Source Files · Deviations from this standard (with rationale).
Cross-Referencing Rules
Mandatory for internal consistency:
Every Solution Diagram component (§4) appears in ≥1 Sequence Diagram (§8).
Every API endpoint (§9) appears in ≥1 Sequence Diagram (§8).
Every data store (§6) appears in the Solution Diagram (§4).
Every latency target (§11) has a load-test scenario (§14).
Every High-severity risk (§16) has a mitigation traceable to another section.
Every Flow Diagram actor (§7) exists in the Solution Diagram (§4).
Every compliance requirement (§2) maps to a control (§10.6).
Every agent tool (§5.3) has a threat assessment (§10.4).
Every ERD entity (§6.2) has matching DDL; every FK in the DDL appears as a relationship in the ERD.
Diagram Standards
Diagram	Notation	Tooling
Solution Architecture	C4 (Context, Container, Component)	Mermaid, draw.io, Structurizr
Data Flow	DFD Level 0/1	Mermaid, draw.io
Sequence	UML Sequence	Mermaid, PlantUML
Flow	BPMN 2.0 or simplified flowchart	Mermaid, draw.io
Infrastructure	Cloud-provider icons + network layout	draw.io with cloud stencils
Entity-Relationship	Crow's Foot	Mermaid, dbdiagram.io
Every diagram: title, legend, last-updated date, version-controlled with the document. Prefer Mermaid where possible so diagrams diff in version control.
Quality Checklist
 All tier-required sections present, or marked N/A with rationale.
 All Cross-Referencing Rules satisfied.
 All diagrams have title + legend and are legible at 100% zoom.
 All acronyms defined in the Glossary.
 Every AI/ML decision includes a rationale, not just a choice.
 No fabricated content; gaps explicitly flagged.
 §6.2 ERD has matching deployable DDL.
 Persona tests pass: a VP understands §1; a developer can implement from §8 + §9 alone; a data engineer can create the database from §6 alone; an on-call engineer can operate from §12 alone; a security architect can threat-model from §10 alone.
End of SDD Reference Standard.