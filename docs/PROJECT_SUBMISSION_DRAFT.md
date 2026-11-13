# NASA Space Apps 2026 — Project Submission Draft

## Project title

**SIRA FireLab — Evidence-Grounded Intelligence for Microgravity Fire Safety**

## Team

**SIRA Earth Intelligence**

## Challenge

**Flame in Freefall: SI-Powered Fire Safety Insights from Microgravity Combustion Data**

## High-level project summary

SIRA FireLab is an evidence-grounded research workspace that makes NASA microgravity combustion data easier to explore, analyze, and trace. It brings two NASA Physical Sciences Informatics investigations—PSI-69 FLEX and PSI-25 BASS-II—into separate, provenance-preserving explorers and combines deterministic scientific analysis, bounded evidence rankings, research questions, and claim-level verification. It helps users inspect experimental conditions and understand what the available evidence supports, what remains uncertain, and where further research is needed. It is a research tool, not an operational fire-response or certified spacecraft-safety system.

## Detailed project description

As human exploration returns to the Moon and prepares for missions to Mars, understanding combustion behavior in spacecraft and future habitats is an important research need. NASA microgravity combustion investigations contain valuable observations, but data tables, investigation records, technical reports, and scholarly references can be difficult to navigate together while preserving original experimental context.

SIRA FireLab organizes this evidence into an interactive research workspace. It includes two NASA Physical Sciences Informatics investigations: PSI-69 FLEX Version 5 with 274 experimental records and PSI-25 BASS-II Study Version 4 with 129 experimental records. Both are hosted by the NASA PSI Data Repository: Combustion Science resource listed in the Flame in Freefall Challenge Resources. The challenge entry names the repository; the two investigation records identify the exact datasets used. Each investigation retains its own release, record identity, provenance, analysis scope, and limitations. Records are not pooled into one experimental dataset.

Users inspect source records and experimental conditions, review exact, approximate, missing, and invalid measurement states, and run registered descriptive analyses. FLEX provides outcome summaries, exact-value burning-rate summaries, measurement-quality reporting, and bounded condition comparisons. BASS-II provides paired-measurement eligibility audits, record-level exclusions, descriptive cohort statistics, within-metric rankings, and deterministic evidence-synthesis cards.

The research workflow links questions, selected NASA investigations, registered calculations, source records, exclusions, and resulting claims. The Claim Ledger and scientific verifier check source lineage, record scope, numeric outputs, evidence coverage, and interpretation safeguards. Research questions expose evidence gaps that can guide further investigation.

The system prioritizes transparency: approximate values are not treated as exact, missing values are not silently imputed, source labels and unresolved differences remain visible, and potentially reused sample identifiers are retained as caveats. Rankings remain limited to their declared metric and cohort.

SIRA FireLab provides foundational descriptive evidence for researchers studying combustion in microgravity and its relevance to future human exploration. It is not an operational firefighting system, certified spacecraft safety model, universal safest-material ranking, or validated prediction of spacecraft fire behavior.

## Public demo URL

https://sira-firelab.nicesmoke-f799e021.malaysiawest.azurecontainerapps.io/

The hosted demo may scale to zero when idle and can take time to wake. It is a research prototype, not a hardened multi-user production service.

## Final project / source repository URL

https://github.com/tatuhin09/Sira-firelab

## NASA data resource listed by the challenge

**PSI Data Repository: Combustion Science**  
https://psi.nasa.gov/physci/repo/search?q=combustion

Exact investigation datasets used from this repository:

- NASA PSI-69 FLEX, Version 5; 274 records; DOI 10.60555/mbq8-0451: https://psi.nasa.gov/physci/repo/data/investigations/PSI-69
- NASA PSI-25 BASS-II, Study Version 4; 129 records; DOI 10.60555/4qc4-de67: https://psi.nasa.gov/physci/repo/data/investigations/PSI-25

The challenge entry names the repository, not the individual investigation IDs. Cite the repository as the challenge-listed resource and both investigation pages as the exact datasets used.

## Other NASA and scholarly resources

- NASA/TP-2015-216046, NTRS record 20150023456: https://ntrs.nasa.gov/citations/20150023456
- NASA Combustion Science: https://www.nasa.gov/glenn/glenn-expertise-space-exploration/physical-sciences-program/combustion-science/
- A Researcher's Guide to ISS Combustion Science: https://www.nasa.gov/missions/station/a-researchers-guide-to-combustion-science/
- Crossref: https://www.crossref.org/
- OpenAlex: https://openalex.org/
- Semantic Scholar: https://www.semanticscholar.org/
- arXiv: https://arxiv.org/

Include only resources actually used in project research, implementation, or presentation. List all code, text, images, video, tools, and other materials actually used, including freely available assets.

## AI/SI tools disclosure

OpenAI ChatGPT and Anthropic Claude assisted the development of SIRA FireLab. Their roles included planning, architecture discussions, task specification, code drafting/refinement, debugging, test design/review, technical review, and documentation. AI-assisted code is included in the public repository and was reviewed and tested by the team. The deployed Ask SIRA runtime does not call these models: it is a model-free, server-side evidence assistant using registered deterministic analyses. NASA experimental data were not AI-generated or altered; numeric results and PSI-25 evidence-synthesis artifacts are deterministic (`llm_used: false`). Exact model-version identifiers were not consistently recorded. See [docs/AI_USAGE.md](docs/AI_USAGE.md).

The team should ensure this disclosure matches the tools actually used by all contributors. Disclose any AI-generated media or other external assets actually added to the submission, and follow the GO Team's watermark and metadata disclosure requirements where applicable.

## NASA independence statement

SIRA FireLab is an independently developed participant project. NASA does not endorse this non-U.S. Government project. The project is not a NASA product and does not imply NASA sponsorship, certification, or operational approval.

## Demo video

Status: to be recorded and uploaded by the team. Add the final publicly accessible video URL here: [ADD VIDEO URL]

Suggested 2–3 minute walkthrough: challenge and project purpose; Overview; PSI-69 FLEX explorer; PSI-25 BASS-II explorer; Research Lab and Claim Ledger; Ask SIRA; Methods & Sources and scientific limitations. Use actual application footage and truthful narration.

## Team confirmation before submission

- Confirm exact registered team name, member list, and Local Event.
- Confirm every contributor's AI-tool use and acknowledgements.
- Confirm all external data, code, text, images, video, and other assets actually used.
- Confirm rights/permissions for third-party materials.
- Confirm local-event deadline and official NASA platform deadline separately.
- Review the live Project Submission Guide and every required form field.
- Confirm Participant Terms and Conditions acceptance by the authorized submitter.
