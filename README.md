# SIRA FireLab

**An evidence-grounded research intelligence workspace for microgravity combustion and human-spaceflight fire-safety research.**

SIRA FireLab is the integrated SIRA solution developed by **Team SIRA Earth Intelligence** for the NASA Space Apps Challenge 2026 challenge **Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data**.

It brings together NASA combustion research records, reproducible scientific analysis, evidence ranking, research planning, and claim-level verification in one interactive workspace. It is designed to make experimental findings easier to discover, compare, and interpret while retaining source provenance, measurement quality, and scientific limitations.

## Research workspace

The current application navigation, extracted from the shipped interface, is:

- Ask SIRA
- Overview
- Data Explorer
- BASS-II Explorer (PSI-25)
- Research Lab
- Methods & Sources

## NASA investigations

| NASA investigation | Release | Bundled experimental records | DOI |
|---|---|---:|---|
| PSI-69 — Flame Extinguishment Experiment (FLEX) | Version 5 | 274 | `10.60555/mbq8-0451` |
| PSI-25 — Burning and Suppression of Solids II (BASS-II) | Study Version 4 | 129 | `10.60555/4qc4-de67` |

Each investigation retains its own source identity, release, record keys, provenance, analysis scope, and limitations. Their records are not pooled into a common experimental dataset.

## What the system does

- Explore NASA experimental records and their reported conditions.
- Preserve exact, approximate, missing, and invalid measurement states.
- Run registered, deterministic descriptive analyses.
- Compare explicitly bounded cohorts and display sample sizes and exclusions.
- Rank findings within their stated metric and cohort scope.
- Trace findings to supporting and excluded experiment records.
- Maintain a claim ledger and run scientific consistency verification.
- Expose research questions and evidence gaps for further investigation.
- Present dataset versions, DOI references, file hashes, methods, and caveats.

## Run the offline research workspace

Requirements: Python 3.10 or later.

From the candidate repository root:

```bash
python3 tools/run_firelab_m2.py --offline
```

Open the loopback URL printed by the server (default port `8765`). Offline mode uses the locally bundled evidence and does not execute the scholarly-paper retrieval worker or contact external providers. A paper query can therefore return an explicit offline cache miss.

Live scholarly-reference retrieval requires the separately configured research-worker/provider environment. It is not part of the standalone offline operation described above.

## Scientific boundaries

SIRA FireLab is a research and evidence-exploration system. It is not a certified spacecraft fire-safety model, spacecraft fire-control system, operational firefighting tool, or source of operational safety instructions.

Descriptive cohort differences are not causal effects. Record counts are not automatically counts of independent physical samples. Rankings are restricted to their declared metric, cohort, and release; they are not universal safest-fuel or safest-material rankings. Missing values are not silently imputed, and unresolved source differences remain visible.

## Documentation

- [NASA challenge alignment and submission requirements](docs/NASA_COMPLIANCE.md)
- [NASA data sources and provenance](docs/DATA_SOURCES.md)
- [Methods and scientific limitations](docs/METHODS.md)
- [AI usage disclosure](docs/AI_USAGE.md)
- [Security and deployment](docs/SECURITY.md)
- [Development and testing](docs/DEVELOPMENT.md)
- [Project submission draft](docs/PROJECT_SUBMISSION_DRAFT.md)
- [References](docs/REFERENCES.md)
- [Software license status](docs/LICENSE_STATUS.md)
- [Final release checklist](docs/RELEASE_CHECKLIST.md)

## Software license

Original SIRA FireLab project software is licensed under the Apache License 2.0. See [LICENSE](LICENSE).

This project license does not replace the separate licenses or terms applicable to NASA datasets and other third-party materials. See [Software and Dataset License Status](docs/LICENSE_STATUS.md) and [Data Sources](docs/DATA_SOURCES.md).

## Attribution and independence

SIRA FireLab is an independently developed participant project using cited NASA source data. It is not a NASA product and does not imply NASA endorsement, sponsorship, or certification. NASA source material and the original project software have separate licensing terms.

<!-- SIRA_FIRELAB_RELEASE_BASELINE_V1 -->
## Dataset baseline

This release candidate freezes NASA PSI investigation data snapshots selected
through the team's local-event materials: **PSI-69 FLEX Version 5 (274 records)**
and **PSI-25 BASS-II Version 4 (129 records)**. Their DOIs, provenance, license
metadata scope, and source-selection note are documented in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

The team does not claim that either dataset has been matched to the challenge-
specific Resources list until the exact published list is checked. See
[`docs/NASA_COMPLIANCE.md`](docs/NASA_COMPLIANCE.md) for the status and update
rule. This candidate keeps the current data snapshot fixed; any later source
alignment will be recorded as an explicit subsequent update.

<!-- SIRA_LOCAL_EVENT_INSTRUCTION_CONTEXT_V1 -->
## Local-event dataset instruction and judging context

**Team-reported context:** the local-event teachers/mentors supplied the PSI-69 FLEX Version 5 and PSI-25 BASS-II Version 4 data packages and instructed the team to use these datasets for local judging. The team selected and used these exact snapshots in line with that local-event instruction. The scientific source records remain attributed to NASA's Physical Sciences Informatics repository.

This local-event instruction is distinct from the international challenge's challenge-specific Resources list. The current snapshots remain the team's frozen baseline. Once the official *Flame in Freefall* Resources list is published, the team will compare the listed identifiers with these exact datasets. If they match, no dataset replacement is needed; if they do not, any additional challenge-resource integration will be documented as a separate explicit update while preserving this local-event baseline.
