# AI and Super-Intelligence (SI) Usage Disclosure

**Project:** SIRA FireLab  
**Challenge:** Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data  
**Disclosure reviewed:** 13 November 2026

## 1. Meaning of AI/SI in this challenge

The challenge title uses **SI** to refer to **super intelligence** and calls for an SI-powered research experience. The NASA Space Apps submission guidance also asks teams to disclose AI/SI tools used.

SIRA FireLab follows the challenge's research-intelligence objective. It does **not** claim to be artificial superintelligence, artificial general intelligence, or a superhuman autonomous system. Its released research functions are bounded by registered investigations, deterministic calculations, evidence contracts, and explicit scientific limitations.

## 2. AI tools used during development

The project used the following AI assistants during development:

| Provider | Tool | Development uses | Model/version |
|---|---|---|---|
| OpenAI | ChatGPT | Project planning, architecture discussions, task and prompt specification, code drafting/refinement, debugging, test design/review, technical review, and documentation. | Exact model identifiers were not consistently recorded. |
| Anthropic | Claude | Planning, architecture discussions, code drafting/refinement, debugging, test design/review, verification support, and documentation. | Exact model identifiers were not consistently recorded. |

**These are the two AI development tools used by the team. Gemini was not used and is intentionally not listed.** This is a project-level disclosure, not an attribution of every individual change to a particular contributor.

## 3. How AI assistance was used

ChatGPT and Claude supported parts of the engineering workflow, including:

- Breaking challenge and engineering goals into implementation tasks.
- Discussing architecture, data contracts, application boundaries, and documentation structure.
- Drafting or refining portions of code and tests, and helping investigate bugs.
- Reviewing implementation plans, test results, error reports, and technical explanations.
- Drafting and editing project documentation and submission wording.

AI assistance does not replace the team's responsibility for code, scientific decisions, test results, source attribution, or final submission. AI-assisted code is included in the public repository and is disclosed here. The team reviewed and tested changes before accepting them into the project.

## 4. AI use in the deployed application

The public SIRA FireLab release does **not** invoke ChatGPT, Claude, or another generative LLM to answer user questions or calculate scientific results.

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

No AI-generated image, video, or audio asset is identified in the checked public repository snapshot. Any separately prepared slides, screen recordings, voice-over, music, or other submission materials must be reviewed by the team.

The NASA GO Team's AI-use clarification states that:
- AI-generated images and videos must carry a visible watermark identifying them as AI-generated.
- AI-generated audio must be acknowledged in descriptive text and metadata.
- AI-generated code and data must be acknowledged in descriptive text and metadata.
- AI-generated content must not use, contain, or modify NASA branding or design elements such as NASA logos, flags, or mission identifiers.

If AI-generated media is added, disclose it and follow those requirements. Do not imply that AI-generated media is human-recorded or original photography.

## 7. Short disclosure for the submission form

> SIRA FireLab's development was assisted by OpenAI ChatGPT and Anthropic Claude for planning, architecture discussions, task specification, code drafting/refinement, debugging, test design/review, technical review, and documentation. AI-assisted code is included in the public repository and was reviewed and tested by the project team. The deployed Ask SIRA feature does not call these models: it is a model-free, server-side evidence assistant using registered deterministic analyses. NASA experimental data were not AI-generated or altered, and scientific numerical outputs and PSI-25 evidence-synthesis artifacts are produced deterministically (`llm_used: false`). Exact model-version identifiers were not consistently recorded.

## 8. Sources and responsibility

- NASA Space Apps Challenge 2026 — Flame in Freefall: https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/
- NASA GO Team, AI-tool disclosure and challenge Resources guidance, Discussion #1849: https://github.com/nasa/spaceapps/discussions/1849
- NASA GO Team, Submission format and branding, Discussion #1858 (9 November 2026): https://github.com/nasa/spaceapps/discussions/1858
- 2026 NASA Space Apps Participant Terms and Conditions: https://www.spaceappschallenge.org/legal/

The project team is responsible for verifying every factual statement, dataset citation, license, AI-use disclosure, and final submission field.
