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

**These are the two AI development tools used by the team.** This is a project-level disclosure, not an attribution of every individual change to a particular contributor.

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

## 6. Demo video, images, and audio

The team's demo video is being prepared with a mixed-media format:

| Component | Actual production method | Disclosure |
|---|---|---|
| Selected visual segments | AI-generated visuals/video | Must have a visible, readable watermark stating **AI-GENERATED** on the generated portions, as required by the NASA GO Team. |
| NASA footage | Excerpts from NASA video material | Credit NASA and identify the exact source clip title and official URL in the video's end credits or description. Verify that the selected clip does not contain separately copyrighted third-party footage or music requiring permission. |
| Product demonstration | Real screen recordings of the running SIRA FireLab application | These are actual recordings of the implemented product, not AI-generated interface mockups. |
| Narration | Recorded in Sadia's own voice | Human-recorded narration; no AI-generated voice or narration is being used. |

**Before publication:** place a visible **AI-GENERATED** watermark over every AI-generated visual/video segment. The label should remain on screen for the entire generated segment and be clear enough to read. Do not put NASA logos, insignia, flags, mission identifiers, or other NASA branding into AI-generated content. Do not edit AI-generated footage to make it appear to be authentic NASA footage, a real spaceflight recording, or actual experimental evidence.

The exact NASA clip titles and official source URLs have not yet been entered in this repository. Add them to the final video credits/description and to the submission's references before uploading. A general NASA acknowledgment is not a substitute for identifying the actual clips used.

The NASA GO Team's AI-use clarification states that:
- AI-generated images and videos must carry a visible watermark identifying them as AI-generated.
- AI-generated audio must be acknowledged in descriptive text and metadata.
- AI-generated code and data must be acknowledged in descriptive text and metadata.
- AI-generated content must not use, contain, or modify NASA branding or design elements such as NASA logos, flags, or mission identifiers.

NASA's own media guidance says NASA media should be acknowledged and must not be used to imply NASA endorsement. NASA-hosted audiovisual material can sometimes include third-party copyrighted footage or music; NASA's publication of such material does not automatically grant reuse rights for those third-party elements. Check the selected clip's own markings, credits, and usage notes.

## 7. Short disclosure for the submission form

> SIRA FireLab's development was assisted by OpenAI ChatGPT and Anthropic Claude for planning, architecture discussions, task specification, code drafting/refinement, debugging, test design/review, technical review, and documentation. AI-assisted code is included in the public repository and was reviewed and tested by the project team. The demo video includes selected AI-generated visual segments, NASA video excerpts, and real screen recordings of the running application. AI-generated visual segments are visibly watermarked as AI-generated. The narration is recorded by a team member in her own voice; no AI-generated voice is used. NASA footage sources are credited in the video. The deployed Ask SIRA feature does not call generative models: it is a model-free, server-side evidence assistant using registered deterministic analyses. NASA experimental data were not AI-generated or altered, and scientific numerical outputs and PSI-25 evidence-synthesis artifacts are produced deterministically (`llm_used: false`). Exact model-version identifiers were not consistently recorded.

## 8. Sources and responsibility

- NASA Space Apps Challenge 2026 — Flame in Freefall: https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/
- NASA GO Team, AI-tool disclosure and challenge Resources guidance, Discussion #1849: https://github.com/nasa/spaceapps/discussions/1849
- NASA GO Team, Submission format and branding, Discussion #1858 (9 November 2026): https://github.com/nasa/spaceapps/discussions/1858
- NASA Images and Media Usage Guidelines: https://www.nasa.gov/nasa-brand-center/images-and-media/
- 2026 NASA Space Apps Participant Terms and Conditions: https://www.spaceappschallenge.org/legal/

The project team is responsible for verifying every factual statement, dataset citation, license, AI-use disclosure, video watermark, NASA footage credit, and final submission field.

## 7. Short disclosure for the submission form

> SIRA FireLab's development was assisted by OpenAI ChatGPT and Anthropic Claude for planning, architecture discussions, task specification, code drafting/refinement, debugging, test design/review, technical review, and documentation. AI-assisted code is included in the public repository and was reviewed and tested by the project team. The deployed Ask SIRA feature does not call these models: it is a model-free, server-side evidence assistant using registered deterministic analyses. NASA experimental data were not AI-generated or altered, and scientific numerical outputs and PSI-25 evidence-synthesis artifacts are produced deterministically (`llm_used: false`). Exact model-version identifiers were not consistently recorded.

## 8. Sources and responsibility

- NASA Space Apps Challenge 2026 — Flame in Freefall: https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/
- NASA GO Team, AI-tool disclosure and challenge Resources guidance, Discussion #1849: https://github.com/nasa/spaceapps/discussions/1849
- NASA GO Team, Submission format and branding, Discussion #1858 (9 November 2026): https://github.com/nasa/spaceapps/discussions/1858
- 2026 NASA Space Apps Participant Terms and Conditions: https://www.spaceappschallenge.org/legal/

The project team is responsible for verifying every factual statement, dataset citation, license, AI-use disclosure, and final submission field.
