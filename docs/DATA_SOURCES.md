# Data Sources and Provenance

This document identifies the source investigations and scholarly-reference resources used by SIRA FireLab.

## NASA PSI-69 — Flame Extinguishment Experiment (FLEX)

- Investigation: NASA PSI-69.
- Release: Version 5.
- DOI: `10.60555/mbq8-0451`.
- Official PSI record: https://psi.nasa.gov/physci/repo/data/investigations/PSI-69
- NASA technical report: NASA/TP-2015-216046, NTRS record `20150023456`.
- Report: https://ntrs.nasa.gov/citations/20150023456
- Investigation metadata license: CC0-1.0.
- Bundled experimental records: 274.

The source CSV, parsed records, quality report, and manifest are retained. The loader verifies the source CSV, records JSON, and quality JSON using SHA-256 hashes and checks the declared record count.

The PSI-69 Version 5 CSV contains 274 experimental records. The NASA portal's 275-item table count is consistent with counting the header row; FireLab does not treat it as a 275th experiment.

### FLEX limitations

- The PSI CSV labels a composition field `CO`; the corresponding NASA report field is labelled `CO2`. The source label is preserved. A partial cross-source check covered 31 tests across eight fields (248 comparisons, zero mismatches); this does not establish full release-wide reconciliation.
- The report describes the first 284 tests while the PSI-69 Version 5 CSV contains 274 records. The scope difference remains unresolved and is not filled with invented records.
- The source CSV labels burning rate with `mm`; the report documents an average burning-rate constant in `mm²/s`. The source label is preserved and the report definition is documented.
- Test #114 reports a source pressure value of zero. It remains preserved and flagged.
- Approximate, missing, and invalid measurement states remain distinct.
- Mixture fractions are not silently normalized.

## NASA PSI-25 — Burning and Suppression of Solids II (BASS-II)

- Investigation: NASA PSI-25.
- Release: Study Version 4.
- DOI: `10.60555/4qc4-de67`.
- Official PSI record: https://psi.nasa.gov/physci/repo/data/investigations/PSI-25
- Investigation metadata license: CC0-1.0.
- Bundled experimental records: 129.

The CSV contains 130 non-empty logical records: one header and 129 experimental data records. The canonical dataset therefore contains 129 experiments. The table count is not interpreted as 130 experimental records.

The source provenance retains four files: the BASS-II experimental table, Test Matrices workbook, ReadMe document, and Fan Calibration workbook. Their NASA file identifiers, source keys, versions, byte sizes, SHA-256 checksums, retrieval metadata, and validation information are retained in `provenance.json`.

### PSI-25 license scope

The recorded CC0-1.0 license is investigation-level NASA repository metadata. The provenance explicitly states that it is not an independent file-level legal review. The recorded NASA metadata marks the four files as not access-restricted; this project does not claim to have obtained a separate legal opinion for each file.

### PSI-25 derived evidence

The verified release includes canonical records, a quality report, paired-measurement analysis, record-level eligibility audits, findings rankings, and deterministic evidence-synthesis artifacts. The synthesis contains 54 insight cards and 146 research questions. It records `llm_used: false`.

Record reuse indicators, exclusions, measurement caveats, and descriptive-only interpretation restrictions are retained.

## Scholarly reference discovery

The research-reference workflow supports metadata discovery through Crossref, OpenAlex, Semantic Scholar, and arXiv. These providers supply scholarly reference metadata; they are not substitutes for NASA experimental records and do not independently validate NASA measurements.

## Challenge Resources-tab cross-check

The final NASA submission must list the exact NASA data resource entry used from the official Flame in Freefall challenge Resources tab. The PSI investigation records above are cited as the sources of the bundled experimental data. Before submission, open the official challenge Resources tab, confirm the matching resource entry, and copy its exact displayed title and URL into the NASA submission form. Do not substitute a third-party suggested list for the official Resources tab.

Official challenge page: https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/

All data, code, text, images, and other resources actually used in the project must be included in the submission's resource/reference fields, even when freely available.

<!-- SIRA_FIRELAB_RELEASE_BASELINE_V1 -->
## Frozen dataset baseline — 12 November 2026

This public candidate freezes the following two scientific data snapshots:

| Investigation | Dataset snapshot | Records used | DOI | Repository license metadata |
|---|---|---:|---|---|
| PSI-69 FLEX | Version 5 | 274 | [10.60555/mbq8-0451](https://doi.org/10.60555/mbq8-0451) | CC0-1.0 |
| PSI-25 BASS-II | Version 4 | 129 | [10.60555/4qc4-de67](https://doi.org/10.60555/4qc4-de67) | CC0-1.0 at the investigation-metadata level |

**How the team obtained/selected these data:** the team reports that its local-event teachers/organizers provided these data packages and instructed the team to use them for local-event judging. The underlying dataset records identify NASA's Physical Sciences Informatics (PSI) repository as the scientific data source. The release preserves the selected source snapshots and their provenance; it does not claim that either dataset has been verified as an entry in the *Flame in Freefall* challenge-specific Resources tab.

**License scope:** PSI-25's CC0-1.0 value is investigation-level license metadata. It is not presented as a separate legal review of every individual file. See [LICENSE_STATUS.md](LICENSE_STATUS.md).

**Resource-list alignment:** the exact challenge Resources list has not yet been checked against these dataset identifiers for this release. If the published list identifies an additional or more specific resource, any change will be recorded as a subsequent, explicit data/documentation update. This frozen baseline will not be silently rewritten.

<!-- SIRA_LOCAL_EVENT_INSTRUCTION_CONTEXT_V1 -->
## Local-event dataset instruction and judging context

**Team-reported context:** the local-event teachers/mentors supplied the PSI-69 FLEX Version 5 and PSI-25 BASS-II Version 4 data packages and instructed the team to use these datasets for local judging. The team selected and used these exact snapshots in line with that local-event instruction. The scientific source records remain attributed to NASA's Physical Sciences Informatics repository.

This local-event instruction is distinct from the international challenge's challenge-specific Resources list. The current snapshots remain the team's frozen baseline. Once the official *Flame in Freefall* Resources list is published, the team will compare the listed identifiers with these exact datasets. If they match, no dataset replacement is needed; if they do not, any additional challenge-resource integration will be documented as a separate explicit update while preserving this local-event baseline.
