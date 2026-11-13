# Data Sources and Provenance

This document identifies the source investigations and scholarly-reference resources used by SIRA FireLab.

## Challenge-listed NASA repository resource

**PSI Data Repository: Combustion Science**  
Challenge Resources URL: https://psi.nasa.gov/physci/repo/search?q=combustion

The challenge list names the repository-level source. The exact investigation datasets bundled by this project are:

## NASA PSI-69 — Flame Extinguishment Experiment (FLEX)

- Release: Version 5.
- DOI: 10.60555/mbq8-0451.
- Official PSI record: https://psi.nasa.gov/physci/repo/data/investigations/PSI-69
- NASA technical report: NASA/TP-2015-216046, NTRS record 20150023456: https://ntrs.nasa.gov/citations/20150023456
- Investigation metadata license: CC0-1.0.
- Bundled experimental records: 274.

The PSI-69 Version 5 CSV contains 274 experimental records. The NASA portal's 275-item table count includes the header; FireLab does not treat it as a 275th experiment. Source CSV, parsed records, quality report, manifest, and SHA-256 checks are retained.

### FLEX limitations

- The PSI CSV labels a composition field CO; the corresponding NASA report field is labelled CO2. The source label is preserved. A partial cross-source check covered 31 tests across eight fields (248 comparisons, zero mismatches); this is not full release-wide reconciliation.
- The report describes the first 284 tests while the PSI-69 Version 5 CSV contains 274 records. The scope difference remains unresolved.
- The source CSV labels burning rate with mm; the report documents an average burning-rate constant in mm²/s. The source label is preserved.
- Test #114 reports a source pressure value of zero; it remains preserved and flagged.
- Approximate, missing, and invalid measurement states remain distinct. Mixture fractions are not silently normalized.

## NASA PSI-25 — Burning and Suppression of Solids II (BASS-II)

- Release: Study Version 4.
- DOI: 10.60555/4qc4-de67.
- Official PSI record: https://psi.nasa.gov/physci/repo/data/investigations/PSI-25
- Investigation metadata license: CC0-1.0.
- Bundled experimental records: 129.

The CSV contains 130 non-empty logical records: one header and 129 experimental data records. Four source files and their NASA identifiers, source keys, versions, sizes, SHA-256 checksums, retrieval metadata, and validation information are retained in provenance.json.

### PSI-25 license scope and derived evidence

The recorded CC0-1.0 license is investigation-level repository metadata, not an independent file-by-file legal review. The verified release includes canonical records, quality reporting, paired-measurement analysis, eligibility audits, rankings, and deterministic synthesis artifacts (54 insight cards and 146 research questions). The synthesis manifest records llm_used: false.

## Repository-to-challenge mapping precision

The challenge Resources entry names PSI Data Repository: Combustion Science. PSI-69 and PSI-25 are individual investigation records hosted by that repository; their identifiers are not separately named in the challenge entry. In the submission, cite the repository entry as the challenge-listed resource and cite both investigation pages and DOIs as the exact data used.

## Scholarly reference discovery

The workflow supports metadata discovery through Crossref, OpenAlex, Semantic Scholar, and arXiv. These providers supply scholarly metadata; they are not substitutes for NASA experimental records and do not independently validate NASA measurements.

## Provenance, use, and licensing boundaries

The team reports that local-event teachers/organizers supplied the PSI-69 FLEX Version 5 and PSI-25 BASS-II Version 4 packages and instructed the team to use them for local judging. Underlying scientific records are attributed to NASA PSI. NASA datasets and third-party materials retain their applicable terms. Apache-2.0 applies only to original FireLab software.

List all data, code, text, images, video, and other resources actually used in the submission, including open-source and freely available materials. Do not list a resource as used if it was merely reviewed and not incorporated.
