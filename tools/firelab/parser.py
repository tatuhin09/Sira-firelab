"""CSV validation primitives that preserve per-field data quality."""
import csv
import hashlib
import io
import math


_MISSING_MARKERS = {"", "–", "—"}


def _decode_source(source):
    if isinstance(source, str):
        return source.encode("utf-8"), source
    raw = bytes(source)
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # NASA PSI exports may contain Windows-1252 en dashes for missing data.
        decoded = raw.decode("cp1252")
    return raw, decoded


def _parse_measurement(value):
    """Return (number, quality), retaining approximations as flagged values."""
    raw = (value or "").strip()
    if raw in _MISSING_MARKERS:
        return None, "missing"
    approximate = raw.startswith("~")
    numeric_text = raw[1:].strip() if approximate else raw
    try:
        number = float(numeric_text)
    except ValueError:
        return None, "invalid"
    if not math.isfinite(number):
        return None, "invalid"
    return number, "approximate" if approximate else "exact"


def parse_csv(source, *, id_column, numeric_columns=(), required_columns=()):
    """Parse CSV bytes/text, preserving records with missing/invalid measurements.

    The chosen id column must identify an experimental record. Numeric values are
    converted to floats; blanks and dash markers become None, and '~number' values
    are retained with an approximate quality flag. Only rows without an ID,
    duplicate IDs, or missing required non-measurement values are excluded.
    """
    raw, decoded = _decode_source(source)
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    headers = reader.fieldnames or []
    needed = {id_column, *numeric_columns, *required_columns}
    missing_headers = sorted(needed - set(headers))
    if missing_headers:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing_headers)}")

    rows, seen = [], set()
    field_quality = {
        column: {"exact": 0, "approximate": 0, "missing": 0, "invalid": 0}
        for column in numeric_columns
    }
    report = {
        "input_rows": 0,
        "accepted_rows": 0,
        "missing_id_rows": 0,
        "duplicate_id_rows": 0,
        "missing_required_rows": 0,
        "missing_measurement_rows": 0,
        "invalid_numeric_rows": 0,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "field_quality": field_quality,
    }
    for source_row in reader:
        report["input_rows"] += 1
        source_row_number = report["input_rows"] + 1
        row = {
            str(key): (value.strip() if isinstance(value, str) else value)
            for key, value in source_row.items()
            if key is not None
        }
        row["_source_row"] = source_row_number
        identifier = row.get(id_column, "")
        if not identifier:
            report["missing_id_rows"] += 1
            continue
        if identifier in seen:
            report["duplicate_id_rows"] += 1
            continue
        seen.add(identifier)
        if any(not row.get(column) for column in required_columns):
            report["missing_required_rows"] += 1
            continue

        raw_values = {key: value for key, value in row.items() if key != "_source_row"}
        qualities = {}
        for column in numeric_columns:
            number, quality = _parse_measurement(row.get(column))
            row[column] = number
            qualities[column] = quality
            field_quality[column][quality] += 1
        row["_quality"] = qualities
        row["_raw"] = raw_values
        if "missing" in qualities.values():
            report["missing_measurement_rows"] += 1
        if "invalid" in qualities.values():
            report["invalid_numeric_rows"] += 1
        rows.append(row)

    report["accepted_rows"] = len(rows)
    return {"rows": rows, "report": report}
