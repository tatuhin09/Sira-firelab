# Methods and Scientific Boundaries

## Evidence workflow

SIRA FireLab links the research question, selected investigation, source records, registered calculation, result, and supporting evidence. The workflow is:

1. Select a NASA investigation and declared release.
2. Load the source-backed evidence bundle.
3. Verify source and derived-artifact identity using SHA-256.
4. Inspect record fields, conditions, and measurement quality.
5. Execute a registered analysis with explicit scope.
6. Retain sample sizes, exclusions, record identities, and caveats.
7. Link result claims to supporting and excluded records.
8. Run scientific consistency checks before presenting the verified result.

The planning and research-synthesis workflow structures questions and evidence. Registered numerical calculations remain deterministic.

## Provenance and integrity

For PSI-69, the loader verifies the source CSV, `records.json`, and `quality.json` against the release manifest and checks record count.

For PSI-25, the evidence registry verifies the provenance manifest, original source files, canonical records, quality report, paired-analysis artifacts, findings, synthesis manifest, derived payloads, builder hashes, record-key coverage, and declared scientific safeguards.

A hash match establishes identity relative to the recorded manifest. It does not independently prove that a source measurement is scientifically correct.

## PSI-69 FLEX

The dataset contains 274 records keyed by FLEX Test number. Registered descriptive operations cover the dataset snapshot, outcomes by fuel, exact finite burning-rate summaries, measurement quality, and a bounded oxygen-cohort sensitivity comparison.

Exact-value summaries exclude approximate and missing values. The oxygen comparison uses overlapping descriptive samples under declared pressure and gas-mixture filters; it is not an adjusted causal estimate or an independent oxygen effect.

Outcome-share gaps and intervals describe selected records only. They do not establish causation, fuel safety rankings, or an operational oxygen threshold.

## PSI-25 BASS-II

The selected Version 4 table contains 129 experimental records. The paired-measurement workflow evaluates O2, CO2, and CO separately. The paired difference is final minus initial measurement. Cohorts use principal investigator, canonical material class, and flow-restrictor code.

The process includes record-level eligibility and exclusion audits, descriptive paired-change summaries, within-metric cohort findings rankings, and deterministic evidence-synthesis cards and research questions.

There are 18 cohort slots per metric, 54 insight cards in total, and 146 research questions. Eligible record counts do not automatically represent independent physical samples. Reused sample identifiers and exclusions remain explicit. The oxygen calibration caveat remains attached to oxygen evidence.

## Claim Ledger and scientific verification

The Claim Ledger associates structured claims with supporting and excluded evidence. The verifier checks source lineage, hashes, record counts and keys, registered analysis identifiers, cohort scope, numerical outputs, exclusion accounting, sample-reuse caveats, calibration caveats, and scientific-scope safeguards.

This is an evidence-contract and consistency check, not independent peer review or a new physical experiment.

## Ranking and interpretation boundaries

PSI-69 comparisons are bounded to their selected condition cohort. PSI-25 rankings are calculated within each metric and its declared cohorts; metrics are not collapsed into a universal cross-metric score.

FireLab does not claim causal effects from descriptive differences, inferential conclusions from potentially reused physical samples, pooled cross-investigation statistics, a universally safest fuel/material, a validated spacecraft fire prediction model, or operational fire-safety advice.
