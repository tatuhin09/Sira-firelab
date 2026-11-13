# NASA Space Apps Challenge Alignment

Challenge: **Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data**

Official challenge page: https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/

## Challenge objective

The challenge asks for an interactive SI-powered dashboard that summarizes, ranks, and interprets microgravity combustion findings to provide foundational fire-safety insights for human space exploration.

SIRA FireLab addresses this through NASA investigation explorers, source-backed experimental records, reproducible summaries, bounded rankings, evidence-linked interpretation, research planning, and claim verification.

## Challenge-to-implementation mapping

| Challenge objective | Existing SIRA FireLab implementation |
|---|---|
| Interactive dashboard | Multi-view research workspace with Ask SIRA, investigation, data, research, and methods views. |
| Find and inspect combustion research | Separate NASA FLEX and BASS-II explorers and scholarly reference workflow. |
| Summarize findings | Registered descriptive summaries, paired analyses, record counts, and quality reporting. |
| Rank findings | Bounded outcome and within-metric cohort rankings with declared denominators and exclusions. |
| Interpret evidence | Research planning, Claim Ledger, source-linked synthesis, and scientific verifier. |
| Preserve scientific traceability | Release identifiers, source hashes, stable record keys, lineage checks, and caveats. |
| Support human-spaceflight research | Exposes descriptive evidence and open research questions without operational safety claims. |

## Scientific scope

FireLab provides a research evidence workspace. It does not claim operational flammability prediction, spacecraft fire-control recommendations, certified fire-safety limits, or universal material safety rankings.

## NASA challenge Resources requirement

The NASA GO Team states that Global Awards eligibility requires using at least one NASA data source included in the selected challenge's official Resources. All sources and tools used must be listed in the project submission, including open-source or freely available code, text, and images.

The PSI-69 and PSI-25 NASA PSI investigation pages and DOIs are documented in `DATA_SOURCES.md`. Before submission, verify the exact corresponding item in the live Flame in Freefall challenge Resources tab and copy its displayed title and URL into the designated NASA Data and References field. This document does not claim an unverified Resources-tab match.

## Submission contents

The GO Team's submission clarification identifies the project title, high-level summary, demo link, final project link, detailed description, NASA and other data resources, AI/SI tools used, and agreement to the Participant Terms and Conditions. The official 2026 event page currently states that project submission opens on 14 November 2026 at 09:00 and closes on 15 November 2026 at 23:59, in the registered event's local time.

The GO Team has said the Project Submission Guide will be posted on 13 November 2026. Use `PROJECT_SUBMISSION_DRAFT.md` as the content draft and `RELEASE_CHECKLIST.md` before the live form is submitted. Check the guide and live form when available.

## AI/SI disclosure

OpenAI ChatGPT and Anthropic Claude assisted software development. Their roles are documented in `AI_USAGE.md` and `project_metadata.json`. NASA experimental data were not AI-generated; the PSI-25 synthesis artifact records `llm_used: false`.

## Branding and attribution

Follow the official Space Apps Brand Guide. Do not use NASA insignia, seal, logotype, or mission identifiers in a way that implies endorsement or certification. Cite all source data and resources in the online submission.

<!-- SIRA_FIRELAB_RELEASE_BASELINE_V1 -->
## Dataset provenance and challenge-resource status

The current candidate uses PSI-69 FLEX Version 5 (274 retained records; DOI 10.60555/mbq8-0451) and PSI-25 BASS-II Version 4 (129 records; DOI 10.60555/4qc4-de67). The team reports that these datasets were supplied through its local-event activities/materials; the underlying scientific records are from NASA's Physical Sciences Informatics repository.

This documentation does **not** assert that either identifier has been matched to the challenge-specific *Flame in Freefall* Resources list. That exact list-to-dataset comparison remains a post-publication verification item. Any later adjustment must preserve provenance and be recorded as a new update.

Do not imply NASA sponsorship, endorsement, certification, or operational approval. This is a research/analysis dashboard, not an operational spacecraft fire-response system.

<!-- SIRA_LOCAL_EVENT_INSTRUCTION_CONTEXT_V1 -->
## Local-event dataset instruction and judging context

**Team-reported context:** the local-event teachers/mentors supplied the PSI-69 FLEX Version 5 and PSI-25 BASS-II Version 4 data packages and instructed the team to use these datasets for local judging. The team selected and used these exact snapshots in line with that local-event instruction. The scientific source records remain attributed to NASA's Physical Sciences Informatics repository.

This local-event instruction is distinct from the international challenge's challenge-specific Resources list. The current snapshots remain the team's frozen baseline. Once the official *Flame in Freefall* Resources list is published, the team will compare the listed identifiers with these exact datasets. If they match, no dataset replacement is needed; if they do not, any additional challenge-resource integration will be documented as a separate explicit update while preserving this local-event baseline.
