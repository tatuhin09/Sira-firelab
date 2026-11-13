# AI and Super-Intelligence (SI) Usage Disclosure

**Project:** SIRA FireLab  
**Challenge:** Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data  
**Disclosure reviewed:** 13 November 2026

## 1. Meaning of AI/SI in this challenge

The official challenge description uses **SI** to mean **super intelligence** and asks for an interactive, SI-powered dashboard. The NASA Space Apps submission clarification separately asks teams to disclose any **AI/SI tools** used.

SIRA FireLab uses the challenge terminology to describe its evidence-oriented research-intelligence objective. This project does **not** claim to be artificial superintelligence, artificial general intelligence, or a superhuman autonomous system. Its released research functions are bounded by registered investigations, deterministic calculations, evidence contracts, and explicit scientific limitations.

## 2. AI tools used during development

The following AI assistants were used in the project-development workflow:

| Provider | Tool | Disclosed development uses | Model/version |
|---|---|---|---|
| OpenAI | ChatGPT | Project planning, architecture discussion, task and prompt specification, code drafting/refinement, debugging, test design/review, technical review, and documentation. | Exact model identifiers were not consistently recorded. |
| Anthropic | Claude | Planning, architecture discussion, code drafting/refinement, debugging, test design/review, verification support, and documentation. | Exact model identifiers were not consistently recorded. |
| Google | Gemini | Development masterplans, task decomposition, implementation guidance, and iterative development coordination. | Exact model identifiers were not consistently recorded. |

This is a project-level disclosure, not an attribution of every individual AI-assisted change to a particular teammate. The project history and existing project records support the tools listed above. Each contributor must still confirm whether they used any additional AI/SI tools and add them before the final submission. Do not list a tool that no contributor actually used.

## 3. How AI assistance was used

AI assistants supported parts of the engineering workflow, including:

- Breaking the challenge and engineering goals into implementation tasks.
- Discussing architecture, data contracts, application boundaries, and documentation structure.
- Drafting or refining portions of code and tests, and helping investigate bugs.
- Reviewing implementation plans, test results, error reports, and technical explanations.
- Drafting and editing project documentation and submission wording.

AI assistance does not replace the team's responsibility for the code, scientific decisions, test results, source attribution, or final submission. AI-assisted code is included in the public repository and is disclosed here. The team reviewed and tested changes before accepting them into the project.

## 4. AI use in the deployed application

The public SIRA FireLab release does **not** invoke ChatGPT, Claude, Gemini, or another generative LLM to answer user questions or calculate scientific results.

The deployed **Ask SIRA** feature is a model-free, server-side evidence assistant. It classifies supported questions against a bounded set of approved intents, loads registered NASA evidence, and runs reviewed deterministic analysis functions. Unsupported or safety-prescriptive questions can be declined rather than answered with an invented conclusion.

The user interface explicitly states that generative explanations are not enabled in this release. The public runtime does not need an external generative-model API key to run the evidence assistant.

The optional scholarly-reference workflow may retrieve bibliographic metadata from services such as Crossref, OpenAlex, Semantic Scholar, and arXiv. Such retrieval is metadata discovery, not generative-AI inference and not independent validation of NASA measurements.

## 5. Experimental data, calculations, and generated research artifacts

- The PSI-69 FLEX Version 5 and PSI-25 BASS-II Study Version 4 experimental records originate from the cited NASA Physical Sciences Informatics releases.
- AI tools were not used to invent, alter, or fill in NASA measurements, source identifiers, record identities, record counts, sample sizes, or deterministic numerical results.
- Parsing, source validation, registered calculations, cohort summaries, measurement-quality counts, and rankings are produced by the project's deterministic software.
- The PSI-25 evidence-synthesis artifacts (54 insight cards and 146 research questions) are produced by a deterministic rule-based build. Their manifest records `llm_used: false`; the payload records `generated_with_llm: false`.
- Missing, approximate, censored, and invalid values remain subject to the documented source and analysis rules; the project does not silently impute missing measurements.
- AI-assisted software code and documentation are disclosed, but they must not be confused with AI-generated experimental evidence.

## 6. Images, video, and audio

No AI-generated image, video, or audio asset is identified as part of the checked public repository snapshot. The team must separately review any slides, screen recordings, voice-over, music, or other materials added outside this repository for the Local Event or Global submission.

The NASA GO Team's AI-use clarification states that:
- AI-generated images and videos must carry a visible watermark identifying them as AI-generated.
- AI-generated audio must be acknowledged in descriptive text and metadata.
- AI-generated code and data must be acknowledged in descriptive text and metadata.
- AI-generated content must not use, contain, or modify NASA branding or design elements such as NASA logos, flags, or mission identifiers.

If any AI-generated media is added later, disclose it and follow those requirements. Do not imply that AI-generated media is human-recorded or original photography.

## 7. Short disclosure for the submission form

> SIRA FireLab's development was assisted by OpenAI ChatGPT, Anthropic Claude, and Google Gemini for planning, architecture and task decomposition, implementation guidance, code drafting/refinement, debugging, test design/review, and documentation. AI-assisted code is included in the public repository and was reviewed and tested by the project team. The deployed Ask SIRA feature does not call these models: it is a model-free, server-side evidence assistant using registered deterministic analyses. NASA experimental data were not AI-generated or altered, and scientific numerical outputs and PSI-25 evidence-synthesis artifacts are produced deterministically (`llm_used: false`). Exact model-version identifiers were not consistently recorded. Any additional tools used by a contributor must be added to this disclosure.

## 8. Sources and responsibility

- NASA Space Apps Challenge 2026 — Flame in Freefall: https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/
- NASA GO Team, About Resources, Discussion #1849 (6 November 2026): https://github.com/nasa/spaceapps/discussions/1849
- NASA GO Team, Submission format and branding, Discussion #1858 (9 November 2026): https://github.com/nasa/spaceapps/discussions/1858
- 2026 NASA Space Apps Participant Terms and Conditions: https://www.spaceappschallenge.org/legal/

The project team is responsible for verifying every factual statement, dataset citation, license, AI-use disclosure, and final submission field. This document records the tools and uses known from the project-development history; it is not a substitute for each contributor's final confirmation.
