# Azure Container Apps Deployment (Public Demo)

This deployment runs the existing FireLab application behind a narrow HTTPS gateway.
The original `firelab_service.http_app` remains loopback-only and is not exposed
on the public listener. The gateway accepts one exact Azure Container Apps FQDN,
requires Azure's overwritten `X-Forwarded-Proto: https` header, enforces same-origin
POSTs with the existing FireLab session token, limits request bodies to 2 KiB,
limits POST volume to 90 requests per rolling minute per app instance, and caps
concurrent gateway requests at eight.

## Runtime boundary

- Python standard library only; `requirements-dev.txt` is not installed in the image.
- `tools/run_firelab_azure.py` starts the unchanged FireLab server on `127.0.0.1:8765`
  in `--offline` mode and starts the public gateway on `0.0.0.0:$PORT`.
- The gateway forwards only the exact static allowlist, `GET /api/session`, and the
  three existing POST endpoints. Raw PSI source files and unknown routes are not served.
- `FIRELAB_PUBLIC_HOSTNAME` must be one canonical DNS hostname with no scheme, port,
  wildcard, path, or whitespace. It may be left unset for the first ACA provisioning
  step; in that state all non-health routes fail closed with 503.
- After creating the Container App, read its assigned FQDN and set
  `FIRELAB_PUBLIC_HOSTNAME` to that exact value before public testing.
- No API keys, private SIRA Core package, user secrets, or paid provider credentials
  are required. Scholarly paper search is cache-only in this public build.
- Runtime SQLite/cache state is ephemeral. The static, hash-verified datasets and
  derived research artifacts are bundled with the application.
- This is an open research demo with no user accounts or production multi-user
  authentication. Do not enter private or sensitive information.

## Continuous-integration release gate

Every relevant pull request and `main` update first runs the complete Python suite
on Python 3.12 (matching the container runtime), the JavaScript regression suite,
JavaScript syntax checks, Python compilation, and a tracked-file privacy gate.
GHCR publishing is a separate job that depends on all checks passing. Pull requests
never publish images; manual publishing is permitted only from `main`. The public
source gate rejects environment files, private-key material, runtime databases,
and any tracked content under `src/` other than `src/.gitkeep` so the private SIRA
Core cannot enter this public repository or container build.

## Build

GitHub Actions builds the image and publishes it to GHCR using the repository's
`GITHUB_TOKEN`. The expected image name is `ghcr.io/<owner>/<repository>:latest`.
Make the GHCR package public if GitHub initially creates it as private; no registry
secret is required for a public image pull.

## Azure resource plan (manual, after the image is public)

The recommended starting configuration is a Consumption-only Container Apps
environment, Southeast Asia region, `--logs-destination none`, HTTP ingress with
`allowInsecure` left false, target port 8080, 0.25 vCPU, 0.5 GiB memory, minimum
replicas 0, maximum replicas 1. Do not create Azure Container Registry, Log Analytics,
Postgres, Redis, storage, VNet, or paid add-ons for this first demo.

Suggested names:

- Resource group: `rg-sira-firelab`
- Container Apps environment: `cae-sira-firelab`
- Container app: `sira-firelab`

Create resources only after reviewing the current Azure cost estimate and the
subscription's Student spending limit. The Consumption free grant is shared across
the subscription; usage beyond the monthly grant consumes student credit. Keep the
subscription spending limit On and do not upgrade to Pay-as-you-go.

## First deployment sequence

1. Create the new public GitHub repository `tatuhin09/sira-firelab` from this clean
   deployment worktree. Do not use or overwrite any existing SIRA repository.
2. Push the reviewed source to `main`; wait for the GHCR publishing workflow.
3. Confirm the image is public and tagged `latest`.
4. Create the resource group and Consumption-only environment in `southeastasia`
   with logs destination `none`.
5. Create the app with external HTTPS ingress, target port 8080, min replicas 0,
   max replicas 1, CPU 0.25 and memory 0.5Gi. Do not set `allow-insecure`.
6. Initially leave `FIRELAB_PUBLIC_HOSTNAME` empty. After creation, obtain the FQDN:
   `az containerapp show -n sira-firelab -g rg-sira-firelab --query properties.configuration.ingress.fqdn -o tsv`
7. Update the app environment variable to the exact FQDN. Then test HTTPS, hostile Host,
   HTTP-forwarded protocol rejection, session bootstrap, POST origin checks, raw-source
   404, and all six UI views.

No Azure resource creation is performed by the preparation installer.
