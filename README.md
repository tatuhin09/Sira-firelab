# SIRA FireLab

**An evidence-grounded research intelligence workspace for microgravity combustion and human-spaceflight fire-safety research.**

SIRA FireLab is the integrated SIRA research workspace developed by **Team SIRA Earth Intelligence** for the NASA Space Apps Challenge 2026 challenge **Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data**.

The workspace brings NASA combustion investigation data, reproducible scientific analysis, evidence ranking, research planning, and claim-level verification into one interactive interface. It is designed to make experimental findings easier to discover, inspect, compare, and interpret while preserving source provenance, measurement quality, and scientific limitations.

## Live project

- **Public demo:** https://sira-firelab.nicesmoke-f799e021.malaysiawest.azurecontainerapps.io/
- **Public source repository:** https://github.com/tatuhin09/Sira-firelab

The hosted demo is an offline-ready research prototype. It may scale to zero while idle and may take time to wake for a new visitor. It is not a hardened multi-user production service.

## Research workspace

The current application navigation, checked against the shipped interface, is:

- Ask SIRA
- Overview
- Data Explorer
- BASS-II Explorer (PSI-25)
- Research Lab
- Methods & Sources

## NASA challenge-listed data resource

The official Flame in Freefall Challenge Resources list names **PSI Data Repository: Combustion Science**:

https://psi.nasa.gov/physci/repo/search?q=combustion

SIRA FireLab uses two investigation datasets hosted by that NASA Physical Sciences Informatics repository:

| Investigation | Release | Bundled experimental records | DOI | NASA PSI record |
|---|---|---:|---|---|
| PSI-69 FLEX | Version 5 | 274 | `10.60555/mbq8-0451` | https://psi.nasa.gov/physci/repo/data/investigations/PSI-69 |
| PSI-25 BASS-II | Study Version 4 | 129 | `10.60555/4qc4-de67` | https://psi.nasa.gov/physci/repo/data/investigations/PSI-25 |

**Attribution precision:** the challenge Resources entry names the PSI repository at repository level; it does not separately enumerate the PSI-69 or PSI-25 identifiers. The NASA investigation pages and DOIs above identify the exact dataset releases bundled by this project. The two investigations remain separate and are not pooled.

## What the system does

- Explore NASA experimental records and their reported conditions.
- Preserve exact, approximate, missing, censored, and invalid measurement states.
- Run registered, deterministic descriptive analyses.
- Compare explicitly bounded cohorts and display sample sizes and exclusions.
- Rank findings only within their declared metric, cohort, and investigation scope.
- Trace findings to supporting and excluded experiment records.
- Maintain a claim ledger and run scientific consistency verification.
- Expose research questions and evidence gaps for further investigation.
- Present dataset versions, DOI references, file hashes, methods, and caveats.

## SI terminology and AI transparency

The challenge uses **SI** to mean **super intelligence**. SIRA FireLab follows the challenge's research-intelligence objective, but does not claim to be artificial superintelligence or artificial general intelligence.

OpenAI ChatGPT and Anthropic Claude assisted development. Their roles are disclosed in [AI Usage Disclosure](docs/AI_USAGE.md). Importantly, the public **Ask SIRA** runtime is model-free: it uses bounded question classification, server-side evidence retrieval, and registered deterministic calculations. Generative explanations are not enabled in this release. The deployed application does not call ChatGPT or Claude.

NASA experimental records and scientific numeric outputs are not AI-generated. The PSI-25 evidence-synthesis build is deterministic and its manifest records `llm_used: false`. The team's demo video combines selected AI-generated visual segments, NASA video excerpts, real application screen recordings, and human-recorded narration; see [AI Usage Disclosure](docs/AI_USAGE.md) for watermark and source-credit requirements.

## Run the offline research workspace

Requirements: Python 3.10 or later.

From the repository root:

```bash
python3 tools/run_firelab_m2.py --offline
```

Open the loopback URL printed by the server (default port `8765`). Offline mode uses locally bundled evidence and does not execute the scholarly-paper retrieval worker or contact external providers. A paper query can therefore return an explicit offline cache miss.

Live scholarly-reference retrieval requires the separately configured research-worker/provider environment. It is not part of the standalone offline operation described above.

## Scientific boundaries

SIRA FireLab is a research and evidence-exploration system. It is not a certified spacecraft fire-safety model, spacecraft fire-control system, operational firefighting tool, or source of operational safety instructions.

Descriptive cohort differences are not causal effects. Record counts are not automatically counts of independent physical samples. Rankings are restricted to their declared metric, cohort, and release; they are not universal safest-fuel or safest-material rankings. Missing values are not silently imputed, and unresolved source differences remain visible.

## Documentation

- [NASA challenge alignment and submission requirements](docs/NASA_COMPLIANCE.md)
- [NASA data sources and provenance](docs/DATA_SOURCES.md)
- [Methods and scientific limitations](docs/METHODS.md)
- [AI and SI usage disclosure](docs/AI_USAGE.md)
- [Security and deployment](docs/SECURITY.md)
- [Development and testing](docs/DEVELOPMENT.md)
- [Project submission draft](docs/PROJECT_SUBMISSION_DRAFT.md)
- [References](docs/REFERENCES.md)
- [Software license status](docs/LICENSE_STATUS.md)
- [Final release checklist](docs/RELEASE_CHECKLIST.md)

## Software license

Original SIRA FireLab project software is licensed under the Apache License 2.0. See [LICENSE](LICENSE).

The Apache-2.0 project license does not replace the separate licenses or terms applicable to NASA datasets and other third-party materials. See [Software and Dataset License Status](docs/LICENSE_STATUS.md) and [Data Sources](docs/DATA_SOURCES.md).

## NASA attribution, branding, and independence

SIRA FireLab is an independently developed participant project using cited NASA source data. It is not a NASA product and does not imply NASA endorsement, sponsorship, certification, or operational approval. NASA source material and original project software have separate licensing terms.

The public repository does not include NASA insignia, seal, or logotype assets. For any separate presentation, slide, or video, follow the current [NASA Space Apps Brand Guide](https://www.spaceappschallenge.org/brand/); do not modify the official Space Apps mark or use NASA identifiers in a way that implies endorsement.

The released dataset snapshot and its source-selection record are documented in [Data Sources](docs/DATA_SOURCES.md). Any later source alignment or dataset addition must be documented as a separate explicit update rather than silently replacing the released baseline.
