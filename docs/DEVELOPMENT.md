# Development and Testing

## Requirements

- Python 3.10 or later.
- Python standard library for application runtime.
- pytest for Python tests.
- Node.js for JavaScript syntax checks, JavaScript tests, and the golden-fixture generator.

## Run offline

```bash
python3 tools/run_firelab_m2.py --offline
```

## Regenerate golden fixture

```bash
node tools/firelab_make_golden.js
```

Review changes to `tests/fixtures/firelab_golden.json` before accepting them.

## Python regression

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -q -p no:cacheprovider tests
```

## JavaScript syntax

```bash
for file in firelab_site/*.js; do node --check "$file" || exit 1; done
```

## JavaScript tests

```bash
node tests/test_firelab_condition_analysis.js
node tests/test_firelab_outcome_ranking.js
node tests/test_firelab_source_label.js
```

## Recorded isolated regression

The 12 November 2026 isolated no-Core candidate regression reported 563 Python tests passed, 3,639 Python subtests passed, all five application JavaScript files passed syntax checks, all three JavaScript test files passed, and the regenerated golden fixture was byte-identical to the source baseline.

This is a recorded result for the tested snapshot. Rerun all checks after any package modification.
