# Security and Deployment

## Standalone operation

Run the integrated workspace in offline mode:

```bash
python3 tools/run_firelab_m2.py --offline
```

The integrated server is intended for loopback use. Offline mode uses the bundled evidence and disables scholarly-paper worker execution.

## Request and browser boundaries

The HTTP application applies request-schema validation, request-size limits, host/origin and fetch-metadata checks, and a process-local session token for protected requests. Static assets are restricted by an explicit allowlist.

The session token is a local request-protection measure. It is not user identity, account authentication, or multi-user authorization.

## Research-provider boundary

Live scholarly-paper retrieval requires a separately configured research-worker/provider environment. Offline operation does not execute that worker or make external provider requests. Paid-provider access is not enabled by the offline workflow.

## Runtime state and secrets

Do not publish `.env` files, API credentials, local SQLite databases, caches, logs, temporary files, backups, installers, or private machine paths. The candidate ignore rules exclude common local runtime artifacts.

## Deployment limitations

This package is an offline-ready research prototype, not a hardened public multi-user service or production identity system. Do not expose its loopback server directly to the public internet.
