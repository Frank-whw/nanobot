# Tenant Runtime (Single Process)

This document describes the tenant runtime extension for single-process multi-user isolation.

## What It Solves

- Per-conversation serial execution using `isolationKey`.
- Global concurrency limits to protect the process.
- Per-tenant/user/project storage buckets for:
  - workspace
  - sessions
  - cron store
  - memory (inside workspace)

## Ingress Contract

Inbound metadata supports these fields:

- Required in production:
  - `tenantId` (or `tenant_id`)
  - `userId` (or `user_id`)
  - `projectId` (or `project_id`)
  - `threadId` (or `thread_id`)
  - `requestId` (or `request_id`)
  - `timestamp` (ISO8601 recommended)
- Optional:
  - `metadata`
  - `media`

If missing, defaults are applied:

- `tenant_id = "default"`
- `project_id = "default"`
- `user_id = sender_id`
- `thread_id = chat_id`

## Isolation Key

`isolationKey = tenantId:userId:channel:threadId`

Runtime bucket key:

`runtimeKey = tenantId:userId:projectId`

## Storage Layout

Root directory (default):

`~/.nanobot/tenants`

Per project:

- `~/.nanobot/tenants/{tenant}/users/{user}/projects/{project}/workspace`
- `~/.nanobot/tenants/{tenant}/users/{user}/projects/{project}/sessions`
- `~/.nanobot/tenants/{tenant}/users/{user}/projects/{project}/cron/jobs.json`

## Enable

Set environment variables before starting `nanobot gateway`:

```bash
export NANOBOT_TENANT_RUNTIME_ENABLED=true
export NANOBOT_TENANT_ROOT="$HOME/.nanobot/tenants"
export NANOBOT_TENANT_MAX_GLOBAL=8
export NANOBOT_TENANT_PER_KEY_LIMIT=50
export NANOBOT_TENANT_TASK_TIMEOUT_S=60
export NANOBOT_TENANT_IDLE_TTL_S=300
```

## Rollback

Immediate rollback path:

```bash
export NANOBOT_TENANT_RUNTIME_ENABLED=false
```

Then restart `nanobot gateway`.

When disabled, gateway returns to the original single-tenant flow and ignores tenant runtime modules.
