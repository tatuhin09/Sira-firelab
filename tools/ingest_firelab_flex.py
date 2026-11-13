"""Build an offline, provenance-preserving bundle from the NASA PSI-69 FLEX CSV."""
import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from tools.firelab.parser import parse_csv


SOURCE_URL = "https://psi.nasa.gov/physci/repo/data/investigations/PSI-69"
REPORT_URL = "https://ntrs.nasa.gov/citations/20150023456"
DOI = "10.60555/mbq8-0451"
LICENSE = "CC0-1.0"

NUMERIC_FIELDS = {
    "Ambient pressure; mmHg": ("ambientPressureMmHg", "Ambient pressure", "mmHg"),
    "O initial ambient composition; mole fraction": ("oxygenMoleFraction", "O₂ fraction", "mole fraction"),
    "N initial ambient composition; mole fraction": ("nitrogenMoleFraction", "N₂ fraction", "mole fraction"),
    "CO initial ambient composition; mole fraction": ("coSourceMoleFraction", "CO / CO₂ source field", "mole fraction"),
    "He initial ambient composition; mole fraction": ("heliumMoleFraction", "He fraction", "mole fraction"),
    "Droplet initial diameter; mm": ("initialDropletDiameterMm", "Initial droplet diameter", "mm"),
    "Visible flame extinction diameter; mm": ("visibleFlameExtinctionDiameterMm", "Visible-flame extinction diameter", "mm"),
    "Burning rate; mm": ("burningRateMm2PerSec", "Average burning-rate constant", "mm²/s"),
    "Burn time; s": ("burnTimeSeconds", "Burn time", "s"),
}

SOURCE_NOTES = ['The PSI CSV labels this composition field CO; NASA/TP-2015-216046 defines its CO₂ field as '
 'ambient carbon-dioxide mole fraction. The first 31 PSI tests match NASA Table IX across eight '
 'checked fields (248 comparisons, zero mismatches); the PSI label is preserved and full '
 'row-by-row reconciliation remains outstanding.',
 'The NASA report record states that it presents the first 284 tests; the PSI Version 5 CSV has '
 '274 rows. The 10-test scope difference is unresolved and does not by itself identify missing or '
 'additional records.',
 'The PSI CSV header abbreviates burning-rate units as mm; NASA/TP-2015-216046 documents the '
 'average burning-rate constant in mm²/s from a linear fit of droplet diameter squared versus '
 'time, shortly after ignition through extinction. The PSI header is preserved.',
 'Blank and en-dash values are missing measurements. Tilde-prefixed values are approximate and are '
 'excluded from exact-value summaries.',
 'Test 114 reports ambient pressure as 0 mmHg in both source records; this published value is '
 'preserved and flagged, not silently changed or interpreted as a valid pressure condition.',
 'Mixture fractions are preserved as reported. No normalization is applied; deviations from unity '
 'are shown as a quality check.']


def _json_bytes(value):
    """Serialize bundle JSON exactly as write_bundle stores it on disk."""
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_bundle(source, *, source_name, retrieved_at):
    numeric_columns = tuple(NUMERIC_FIELDS)
    parsed = parse_csv(
        source,
        id_column="FLEX Test #",
        numeric_columns=numeric_columns,
        required_columns=("FLEX Identifier", "Test Date", "Fuel", "Test end"),
    )
    source_hash = parsed["report"]["source_sha256"]
    records = []
    dates_with_errors = 0
    for row in parsed["rows"]:
        source_row_number = row["_source_row"]
        try:
            test_number = int(row["FLEX Test #"])
        except (TypeError, ValueError):
            raise ValueError(f"Invalid FLEX Test # at source row {source_row_number}")
        date_text = row.get("Test Date", "")
        try:
            date_iso = datetime.strptime(date_text, "%m/%d/%Y").date().isoformat()
        except ValueError:
            date_iso = None
            dates_with_errors += 1

        values = {target: row.get(source_column) for source_column, (target, _, _) in NUMERIC_FIELDS.items()}
        quality = {target: row.get("_quality", {}).get(source_column, "missing")
                   for source_column, (target, _, _) in NUMERIC_FIELDS.items()}
        flags = []
        pressure = values["ambientPressureMmHg"]
        if pressure == 0:
            flags.append("zero_pressure_source_value")
        fractions = [values[key] for key in (
            "oxygenMoleFraction", "nitrogenMoleFraction", "coSourceMoleFraction", "heliumMoleFraction"
        )]
        if all(isinstance(value, (int, float)) for value in fractions):
            if abs(sum(fractions) - 1.0) > 0.01:
                flags.append("mixture_fraction_sum_outside_1_percent")
        records.append({
            "testNumber": test_number,
            "identifier": row.get("FLEX Identifier"),
            "testDate": date_iso,
            "sourceTestDate": date_text,
            "testTimeGmt": row.get("Test GMT") or None,
            "fuel": row.get("Fuel"),
            **values,
            "testEnd": row.get("Test end"),
            "quality": quality,
            "flags": flags,
            "sourceRow": source_row_number,
            "sourceValues": row.get("_raw", {}),
        })

    test_numbers = [record["testNumber"] for record in records]
    identifier_counts = Counter(record["identifier"] for record in records)
    repeated_identifiers = {key: count for key, count in identifier_counts.items() if count > 1}
    quality = {
        "recordCount": len(records),
        "inputRows": parsed["report"]["input_rows"],
        "acceptedRows": parsed["report"]["accepted_rows"],
        "excludedRows": parsed["report"]["input_rows"] - parsed["report"]["accepted_rows"],
        "testNumberCheck": {
            "unique": len(set(test_numbers)),
            "sequentialFromOne": sorted(test_numbers) == list(range(1, len(test_numbers) + 1)),
        },
        "identifierChecks": {
            "FLEX Test #": {"unique": len(set(test_numbers)), "duplicateRows": len(test_numbers) - len(set(test_numbers))},
            "FLEX Identifier": {
                "unique": len(identifier_counts),
                "duplicateRows": sum(count - 1 for count in repeated_identifiers.values()),
                "reusedValues": repeated_identifiers,
                "note": "Repeated hardware identifiers are retained; FLEX Test # is the record key.",
            },
        },
        "fuelCounts": dict(sorted(Counter(record["fuel"] for record in records).items())),
        "testEndCounts": dict(sorted(Counter(record["testEnd"] for record in records).items())),
        "measurementQuality": {
            target: {
                "label": label,
                "unit": unit,
                **parsed["report"]["field_quality"][source_column],
                "sourceHeader": source_column,
            }
            for source_column, (target, label, unit) in NUMERIC_FIELDS.items()
        },
        "missingTimeRows": sum(not record["testTimeGmt"] for record in records),
        "dateParseErrors": dates_with_errors,
        "zeroPressureTestNumbers": [record["testNumber"] for record in records if record["ambientPressureMmHg"] == 0],
        "compositionCheck": {
            "outsideOnePercent": sum("mixture_fraction_sum_outside_1_percent" in record["flags"] for record in records),
            "policy": "source values retained; not normalized",
        },
        "sourceSha256": source_hash,
        "sourceNotes": SOURCE_NOTES,
    }
    manifest = {
        "schemaVersion": 2,
        "shortName": "FLEX",
        "title": "Flame Extinguishment Experiment",
        "source": "NASA Physical Sciences Informatics PSI-69",
        "sourceUrl": SOURCE_URL,
        "reportUrl": REPORT_URL,
        "doi": DOI,
        "license": LICENSE,
        "sourceVersion": "PSI-69 Version 5",
        "sourceFile": source_name,
        "sourceSha256": source_hash,
        "retrievedAt": retrieved_at,
        "statusLabel": f"Source loaded · {len(records)} tests · review flags shown",
        "validatedRows": len(records),
        "recordCount": len(records),
        "qualityFile": "quality.json",
        "recordsFile": "records.json",
        "notes": "Schema and record keys checked; this does not imply every measurement is present or every source value is scientifically resolved.",
    }
    manifest["qualitySha256"] = hashlib.sha256(_json_bytes(quality)).hexdigest()
    manifest["recordsSha256"] = hashlib.sha256(_json_bytes(records)).hexdigest()
    return {"manifest": manifest, "quality": quality, "records": records}


def write_bundle(source_path, site_path, *, retrieved_at=None):
    source_path = Path(source_path)
    site_path = Path(site_path)
    data_path = site_path / "data"
    source_dir = data_path / "source"
    data_path.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    raw = source_path.read_bytes()
    retrieved_at = retrieved_at or date.today().isoformat()
    bundle = build_bundle(raw, source_name=source_path.name, retrieved_at=retrieved_at)
    source_copy = source_dir / source_path.name
    if source_path.resolve() != source_copy.resolve():
        shutil.copyfile(source_path, source_copy)
    for filename, key in (("manifest.json", "manifest"), ("quality.json", "quality"), ("records.json", "records")):
        (data_path / filename).write_bytes(_json_bytes(bundle[key]))
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_csv", help="Path to the NASA PSI-69 experimental table CSV")
    parser.add_argument("--site", default="firelab_site", help="FireLab static-site directory")
    parser.add_argument("--retrieved-at", help="ISO date the source file was downloaded")
    args = parser.parse_args()
    bundle = write_bundle(args.source_csv, args.site, retrieved_at=args.retrieved_at)
    print(f"Loaded {bundle['manifest']['recordCount']} tests")
    print(f"Source SHA-256: {bundle['manifest']['sourceSha256']}")
    print(f"Quality report: {Path(args.site) / 'data' / 'quality.json'}")


if __name__ == "__main__":
    main()
