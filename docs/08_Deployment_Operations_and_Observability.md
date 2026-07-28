# 8. Deployment, Operations and Observability

## 8.1 Environments

| Environment | Purpose | Data |
|---|---|---|
| Local developer | Unit tests, adapters and schemas | Synthetic only |
| Integration | Service integration and contract testing | Synthetic and approved test documents |
| PoC | Real representative decks with controlled users | Approved internal data |
| Pilot | Selected business teams and production-like operations | Classified according to policy |
| Production | Enterprise service | Full governed workload |

No production data is copied to lower environments without approved masking and transfer controls.

## 8.2 Kubernetes workloads

- `presentation-api`
- `presentation-orchestrator`
- `worker-ingestion`
- `worker-planning`
- `worker-composition`
- `worker-assets`
- `worker-rendering`
- `worker-qa`
- `worker-export`
- `pptx-composer`
- `workspace-slide-editor` optional production phase

Each workload has independent resource requests, limits, autoscaling and network policy.

## 8.3 Queue design

Recommended logical queues:

- `aips.ingestion`
- `aips.planning`
- `aips.composition`
- `aips.image`
- `aips.render`
- `aips.qa`
- `aips.export`
- `aips.deadletter`

Queue messages contain IDs and references, not large source content. Durable state remains in Oracle.

## 8.4 Scaling

- API scales by request rate and latency.
- Composition/QA workers scale by queue depth and model concurrency quota.
- Rendering workers scale by CPU/memory and active job count.
- Image-generation concurrency is separately capped due to GPU cost.
- Per-user and per-team quotas prevent one workload from exhausting capacity.
- Backpressure returns queued status rather than failing accepted jobs.

## 8.5 Provisional service-level objectives

| Indicator | PoC target | Production candidate |
|---|---:|---:|
| API availability | 95% | 99.5% |
| API read p95 | < 1.5 s | < 750 ms |
| Job acceptance p95 | < 2 s | < 1 s |
| 10-slide text deck p95 | < 300 s | < 240 s after optimisation |
| Visual-heavy deck p95 | < 600 s | benchmark-defined |
| Successful PPTX export | >= 95% | >= 99% |
| Event delivery gap | recoverable | recoverable through durable status |

These are engineering targets and must be adjusted using PoC measurements.

## 8.6 Observability

### Metrics

- API requests, latency, errors and authorisation failures.
- Jobs by status, stage, queue wait, duration and retry count.
- Slides generated, repaired and failed.
- QA scores and defect categories.
- Model tokens, latency, throughput, cache hits and errors.
- Image generations and safety rejections.
- Renderer duration and PPTX integrity failures.
- Object-storage volume and transfer.
- Usage by team, template and deck type.

### Tracing

A trace spans Workspace request, API, job stages, model calls, internal PPTX composer, rendering and storage. The common identifiers are:

- `correlation_id`
- `job_id`
- `project_id`
- `deck_id`
- `deck_version_id`
- `model_run_id`

### Logging

- Structured JSON logs.
- No raw confidential source content by default.
- Redact tokens, credentials, personal data and document text.
- Log prompt version/hash, schema version, model alias, latency and error metadata.

## 8.7 Health checks

- Liveness checks only process health.
- Readiness checks database, queue and essential internal dependencies with bounded timeouts.
- Deep synthetic checks run separately and generate test presentations without user traffic.
- Model health checks verify schema-constrained response and image endpoint functionality.

## 8.8 Backup and disaster recovery

- Oracle backup follows enterprise database policy.
- Object storage uses versioning and replicated durability.
- Template packages and configuration are backed up separately.
- RPO/RTO targets are agreed before pilot; proposed initial candidate is RPO <= 15 minutes and RTO <= 4 hours for metadata, with existing exported files protected by object storage durability.
- Recovery tests verify database-to-object consistency.

## 8.9 Deployment strategy

- GitOps or approved CI/CD deployment.
- Immutable signed container images.
- Schema migrations use forward-compatible expand/migrate/contract pattern.
- Canary release for API/orchestrator and model configuration.
- Prompt/model/template releases can be rolled back independently.
- Feature flags control outline approval, image generation, auto-repair and browser editing.

## 8.10 Operational runbooks

Required runbooks:

- Queue backlog and worker saturation.
- Model gateway unavailable or degraded.
- PPTX composer failure.
- Renderer crash or font mismatch.
- Corrupted PPTX output.
- Object storage unavailable.
- Oracle connectivity failure.
- Suspicious upload or malware detection.
- Accidental data exposure investigation.
- Template rollback.
- Model/prompt rollback.

Each runbook defines detection, immediate containment, diagnosis, recovery, verification and escalation owner.
