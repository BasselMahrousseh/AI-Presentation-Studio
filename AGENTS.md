# Studio agent instructions

## Read before execution

Before running setup, dependency installation, builds, tests, services, migrations
or deployment commands, or changing code/configuration, read:

1. [README](README.md) and the [Workspace documentation index](../GenAI-Workspace/docs/README.md).
2. [System architecture](../GenAI-Workspace/docs/architecture.md) and
   [Studio architecture](docs/ARCHITECTURE.md).
3. [Database and migrations](../GenAI-Workspace/docs/database.md) and
   [configuration](../GenAI-Workspace/docs/configuration.md).
4. The relevant identity, API, security or deployment guide linked from that index.

Initial read-only inspection of files and Git status is allowed. Use the sibling
checkout layout and resolve the documented prerequisites before execution.

## Implementation rules

- Apply [CLAUDE.md](CLAUDE.md) for generation, ownership and export constraints.
- Studio is integrated into Workspace. All its application and migration-tracker
  tables use `GENAI_WORKSPACE_`; do not introduce `GENAI_PRESENT_` here.
- Studio owns its schema and migrations. On-prem uses a separate Studio schema
  in the same Oracle platform/PDB; never merge it into the Workspace schema or
  treat a shared prefix as a shared ORM/transaction. Use the central Oracle
  installation package linked from the database guide for both services.
- Maintain actual direct-launch settings in `servers/fastapi/.env`; integrated
  development uses the deliberately selected Workspace profile. Use the shared
  configuration key reference and keep credential values out of reports.
- Preserve databases, files, ownership and Alembic history. Renaming existing
  tables requires the documented migration; `create_all` is not an upgrade.
- Keep Azure text inference inside the approved tenant. External content services
  must be explicitly configured and approved by the user's task; never enable
  them silently as a fallback.
- Update source contracts, matching UI consumers, tests and the owning guide
  together. Use synthetic fixtures and temporary storage for verification.
