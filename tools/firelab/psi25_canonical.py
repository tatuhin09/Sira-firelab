"""Deterministic, source-preserving PSI-25 BASS-II v4 canonical data builder.

This module is deliberately separate from FireLab's existing generic parser
and analysis engine. It never modifies original NASA source files.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import posixpath
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SOURCE_RELATIVE = Path(
    "firelab_site/data/source/PSI-25_BASS-II_v4_selected"
)

DEFAULT_OUTPUT = Path(
    "firelab_site/data/derived/psi25_bass_ii_v4"
)

EXPECTED_SOURCES = {
    "PSI-25_Science Documents_BASS-II_Test.Matrices.xlsx": (
        28956,
        "1a3b283dd0adec861793bbc4a454aab64d398cd32d6f37d7a1ad0f642879e686",
    ),
    "PSI-25_Science Documents_BASS-II_ReadMe.docx": (
        21538,
        "69f32647792f54ab2a561e3cdafc6c87d854564fe487aed2b09265286bd84e1d",
    ),
    "PSI-25_Reference Data_Fan calibration data.xlsx": (
        23973,
        "bc0dca3efdef44a7774d8dd37aebc0cedae8d67d7bae8c9cbde9590014a3c983",
    ),
    "PSI-25_Experimental table_BASS-II.csv": (
        16590,
        "71e792bf6b5fb5ea620c5dd70fbbac05515992e12aefcf5dff47312caa48c042",
    ),
}

EXPECTED_TOTAL_BYTES = 91057
EXPECTED_RECORDS = 129
DECIMAL_TOLERANCE = Decimal("1e-12")

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/"
    "relationships"
)
PKG_REL_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
WORD_NS = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
)

CSV_NAME = "PSI-25_Experimental table_BASS-II.csv"
MATRIX_NAME = "PSI-25_Science Documents_BASS-II_Test.Matrices.xlsx"
README_NAME = "PSI-25_Science Documents_BASS-II_ReadMe.docx"
FAN_NAME = "PSI-25_Reference Data_Fan calibration data.xlsx"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _decimal_text(value: Decimal) -> str:
    """Render a Decimal without converting it to binary float."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def _decimal(value: str) -> Decimal | None:
    try:
        number = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _strict_number(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
            value.strip(),
        )
    )


def _normal_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _comma_normalized(value: str) -> str:
    value = re.sub(r"\s*,\s*", " ", value)
    return _normal_text(value)


def _parse_csv_date(raw: str) -> date:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized source date: {raw!r}")


def _excel_serial_date(raw: str, date1904: bool) -> date | None:
    if not raw:
        return None
    try:
        serial = Decimal(raw)
        if serial != serial.to_integral_value():
            return None
        days = int(serial)
    except (InvalidOperation, ValueError, OverflowError):
        return None

    origin = (
        datetime(1904, 1, 1)
        if date1904
        else datetime(1899, 12, 30)
    )
    try:
        return (origin + timedelta(days=days)).date()
    except (OverflowError, ValueError):
        return None


def _read_source_manifest(source_dir: Path) -> dict:
    path = source_dir / "provenance.json"
    _require(path.is_file(), "Original provenance.json missing")

    manifest_bytes = path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    records = manifest.get("files")

    _require(isinstance(records, list), "Invalid source manifest")
    _require(len(records) == 4, "Expected exactly four selected source records")
    _require(
        manifest.get("total_downloaded_bytes") == EXPECTED_TOTAL_BYTES,
        "Selected source byte total mismatch",
    )

    indexed = {
        record.get("filename"): record
        for record in records
    }
    _require(len(indexed) == 4, "Duplicate source filenames in manifest")

    verified = {}

    for filename, (expected_size, expected_sha) in EXPECTED_SOURCES.items():
        file_path = source_dir / filename
        _require(file_path.is_file(), f"Source file missing: {filename}")

        data = file_path.read_bytes()
        actual_sha = _sha256_bytes(data)

        _require(len(data) == expected_size, f"Source size mismatch: {filename}")
        _require(actual_sha == expected_sha, f"Source SHA-256 mismatch: {filename}")

        record = indexed.get(filename)
        _require(record is not None, f"Manifest record missing: {filename}")
        _require(
            record.get("actual_bytes") == expected_size,
            f"Manifest byte count mismatch: {filename}",
        )
        _require(
            record.get("sha256") == expected_sha,
            f"Manifest SHA-256 mismatch: {filename}",
        )

        verified[filename] = {
            "path": str(SOURCE_RELATIVE / filename),
            "bytes": expected_size,
            "sha256": actual_sha,
        }

    return {
        "manifest": manifest,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "sources": verified,
    }


def _read_readme(source_path: Path) -> dict:
    with zipfile.ZipFile(source_path, "r") as archive:
        _require(
            "word/document.xml" in archive.namelist(),
            "ReadMe DOCX document.xml missing",
        )
        root = ET.fromstring(archive.read("word/document.xml"))

    paragraphs = []

    for paragraph in root.iter(f"{{{WORD_NS}}}p"):
        text = "".join(
            node.text or ""
            for node in paragraph.iter(f"{{{WORD_NS}}}t")
        ).strip()
        if text:
            paragraphs.append(text)

    normalized = [
        _normal_text(paragraph)
        for paragraph in paragraphs
    ]

    sibal_matches = [
        index
        for index, text in enumerate(normalized, start=1)
        if (
            "sibal" in text
            and "75/25" in text
            and "cotton" in text
            and "fiberglass" in text
        )
    ]

    sphere_matches = [
        index
        for index, text in enumerate(normalized, start=1)
        if "spherical section" in text and "pmma" in text
    ]

    or_matches = [
        index
        for index, text in enumerate(normalized, start=1)
        if (
            "1000" in text
            and "ppm" in text
            and ("over range" in text or "overrange" in text)
        )
    ]

    return {
        "paragraphs": paragraphs,
        "sibal_composition_verified": bool(sibal_matches),
        "sibal_paragraphs": sibal_matches,
        "sphere_mapping_verified": bool(sphere_matches),
        "sphere_paragraphs": sphere_matches,
        "co_or_threshold_verified": bool(or_matches),
        "co_or_threshold_paragraphs": or_matches,
    }


def _column_index(cell_reference: str) -> int:
    match = re.match(r"^([A-Z]+)", cell_reference)
    _require(match is not None, f"Invalid XLSX cell reference: {cell_reference!r}")

    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - 64
    return result - 1


def _read_matrix(source_path: Path) -> dict:
    matrix_by_key = {}
    sheet_counts = {}
    date1904 = False

    with zipfile.ZipFile(source_path, "r") as archive:
        names = set(archive.namelist())

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships_root = ET.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )

        relationships = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relationships_root.findall(
                f"{{{PKG_REL_NS}}}Relationship"
            )
        }

        properties = workbook.find(f"{{{MAIN_NS}}}workbookPr")
        if properties is not None:
            date1904 = (
                properties.attrib.get("date1904", "false").lower()
                == "true"
            )

        shared_strings = []

        if "xl/sharedStrings.xml" in names:
            shared_root = ET.fromstring(
                archive.read("xl/sharedStrings.xml")
            )
            for item in shared_root.findall(f"{{{MAIN_NS}}}si"):
                shared_strings.append(
                    "".join(
                        node.text or ""
                        for node in item.iter(f"{{{MAIN_NS}}}t")
                    )
                )

        sheets = workbook.find(f"{{{MAIN_NS}}}sheets")
        _require(sheets is not None, "XLSX workbook has no sheets")

        for sheet in sheets:
            sheet_name = sheet.attrib["name"]
            relationship_id = sheet.attrib[f"{{{DOC_REL_NS}}}id"]
            target = relationships.get(relationship_id)

            _require(target is not None, f"Missing sheet relationship: {sheet_name}")

            sheet_path = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
            _require(sheet_path in names, f"Worksheet missing: {sheet_name}")

            root = ET.fromstring(archive.read(sheet_path))
            sheet_data = root.find(f"{{{MAIN_NS}}}sheetData")
            _require(sheet_data is not None, f"Worksheet data missing: {sheet_name}")

            count = 0

            for xml_row in sheet_data.findall(f"{{{MAIN_NS}}}row"):
                row_number = int(xml_row.attrib["r"])
                if row_number == 1:
                    continue

                values = [""] * 16

                for cell in xml_row.findall(f"{{{MAIN_NS}}}c"):
                    index = _column_index(cell.attrib.get("r", ""))
                    if index >= 16:
                        continue

                    cell_type = cell.attrib.get("t")
                    node = cell.find(f"{{{MAIN_NS}}}v")
                    raw = node.text if node is not None else ""

                    if cell_type == "s" and raw:
                        string_index = int(raw)
                        _require(
                            0 <= string_index < len(shared_strings),
                            "Invalid shared string index",
                        )
                        raw = shared_strings[string_index]
                    elif cell_type == "inlineStr":
                        raw = "".join(
                            item.text or ""
                            for item in cell.iter(f"{{{MAIN_NS}}}t")
                        )

                    values[index] = raw

                test_id = values[2].strip()
                if not test_id:
                    continue

                key = (sheet_name, test_id)
                _require(key not in matrix_by_key, f"Duplicate matrix identity: {key}")

                matrix_by_key[key] = {
                    "PI": sheet_name,
                    "test_id": test_id,
                    "sample_id": values[3],
                    "material": values[4],
                    "flow_restrictor": values[5],
                    "fan_display": values[6],
                    "air_display": values[7],
                    "radiometer_gain": values[8],
                    "total_frames": values[9],
                    "initial_o2": values[10],
                    "final_o2": values[11],
                    "initial_co2": values[12],
                    "final_co2": values[13],
                    "initial_co": values[14],
                    "final_co": values[15],
                    "date_raw": values[0],
                    "gmt_raw": values[1],
                    "date": _excel_serial_date(values[0], date1904),
                    "sheet": sheet_name,
                    "row": row_number,
                }
                count += 1

            sheet_counts[sheet_name] = count

    _require(
        len(matrix_by_key) == EXPECTED_RECORDS,
        f"Expected {EXPECTED_RECORDS} matrix records, got {len(matrix_by_key)}",
    )

    return {
        "records": matrix_by_key,
        "sheet_counts": sheet_counts,
        "date1904": date1904,
    }


def _classify_text(csv_value: str, matrix_value: str) -> str:
    if csv_value == matrix_value:
        return "exact"

    if _normal_text(csv_value) == _normal_text(matrix_value):
        return "case_whitespace_equivalent"

    if _comma_normalized(csv_value) == _comma_normalized(matrix_value):
        return "comma_whitespace_candidate"

    if (
        _normal_text(csv_value) == "2 cm sibal"
        and _normal_text(matrix_value) == "sibal 2 cm"
    ):
        return "verified_sibal_word_order_alias"

    return "different"


def _classify_numeric(csv_value: str, matrix_value: str) -> str:
    if csv_value == matrix_value:
        return "exact"

    a = _decimal(csv_value)
    b = _decimal(matrix_value)

    if a is not None and b is not None:
        if a == b:
            return "numeric_equivalent"
        if abs(a - b) <= DECIMAL_TOLERANCE:
            return "floating_point_close"

    return "different"


def _reconcile(csv_rows: list, matrix_data: dict) -> dict:
    matrix_by_key = matrix_data["records"]
    csv_by_key = {}
    sample_ids = Counter()
    pi_counts = Counter()

    for row in csv_rows:
        key = (row["PI"].strip(), row["Test #"].strip())
        _require(key not in csv_by_key, f"Duplicate CSV identity: {key}")
        csv_by_key[key] = row
        sample_ids[row["Sample #"]] += 1
        pi_counts[row["PI"].strip()] += 1

    _require(
        len(csv_by_key) == EXPECTED_RECORDS,
        f"Expected {EXPECTED_RECORDS} CSV identities",
    )
    _require(
        set(csv_by_key) == set(matrix_by_key),
        "CSV and matrix composite identities do not match exactly",
    )

    field_map = {
        "material": ("Fuel Sample Material", "material", "text"),
        "flow_restrictor": ("Flow restrictor", "flow_restrictor", "text"),
        "fan_display": ("Fan display", "fan_display", "text"),
        "air_display": ("Air display", "air_display", "text"),
        "radiometer_gain": (
            "Radiometer gain   (1000   250   50   10)",
            "radiometer_gain",
            "text",
        ),
        "total_frames": ("Total Frames Shot", "total_frames", "text"),
        "initial_o2": (
            "Calibrated  initial O2 % by vol ",
            "initial_o2",
            "numeric",
        ),
        "final_o2": (
            "Calibrated final O2 % by vol",
            "final_o2",
            "numeric",
        ),
        "initial_co2": ("Initial CO2 % by vol", "initial_co2", "numeric"),
        "final_co2": ("Final CO2 % by vol", "final_co2", "numeric"),
        "initial_co": ("Initial CO (ppm)", "initial_co", "numeric"),
        "final_co": ("Final CO (ppm)", "final_co", "numeric"),
    }

    field_counts = {
        name: Counter()
        for name in field_map
    }

    checks = Counter()
    matrix_rows = {}

    for logical_row, csv_row in enumerate(csv_rows, start=2):
        key = (csv_row["PI"].strip(), csv_row["Test #"].strip())
        matrix_row = matrix_by_key[key]
        matrix_rows[key] = matrix_row

        checks["identity_exact"] += 1

        _require(
            csv_row["Sample #"] == matrix_row["sample_id"],
            f"Sample ID mismatch: {key}",
        )
        checks["sample_id_exact"] += 1

        csv_date = _parse_csv_date(csv_row["Date"])
        _require(
            matrix_row["date"] is not None and csv_date == matrix_row["date"],
            f"Date mismatch: {key}",
        )
        checks["date_exact"] += 1

        _require(
            csv_row["GMT"].strip() == matrix_row["gmt_raw"].strip(),
            f"GMT mismatch: {key}",
        )
        checks["gmt_exact"] += 1

        _require(
            csv_row["Flow restrictor"].strip()
            == matrix_row["flow_restrictor"].strip(),
            f"Flow restrictor mismatch: {key}",
        )
        checks["flow_restrictor_exact"] += 1

        for field, (csv_column, matrix_key, kind) in field_map.items():
            left = csv_row[csv_column].strip()
            right = matrix_row[matrix_key].strip()

            status = (
                _classify_text(left, right)
                if kind == "text"
                else _classify_numeric(left, right)
            )

            field_counts[field][status] += 1

    for field, counts in field_counts.items():
        _require(
            counts.get("different", 0) == 0,
            f"Unresolved CSV/Matrix discrepancy in {field}",
        )

    _require(
        checks["identity_exact"] == EXPECTED_RECORDS
        and checks["sample_id_exact"] == EXPECTED_RECORDS
        and checks["date_exact"] == EXPECTED_RECORDS
        and checks["gmt_exact"] == EXPECTED_RECORDS
        and checks["flow_restrictor_exact"] == EXPECTED_RECORDS,
        "Core cross-reference checks incomplete",
    )

    reused = {
        sample: count
        for sample, count in sample_ids.items()
        if count > 1
    }

    return {
        "csv_record_count": len(csv_rows),
        "matrix_record_count": len(matrix_by_key),
        "identity_match_count": len(csv_by_key),
        "core_checks": dict(checks),
        "field_reconciliation": {
            field: dict(counts)
            for field, counts in field_counts.items()
        },
        "pi_record_counts": dict(sorted(pi_counts.items())),
        "distinct_raw_sample_ids": len(sample_ids),
        "reused_raw_sample_id_groups": len(reused),
        "reused_sample_ids": dict(sorted(reused.items())),
        "matrix_sheet_counts": dict(sorted(matrix_data["sheet_counts"].items())),
        "excel_date_system": "1904" if matrix_data["date1904"] else "1900",
        "_matrix_records": matrix_rows,
    }


def _parse_quantity(
    raw: str,
    unit: str,
    *,
    is_co: bool = False,
    or_threshold_verified: bool = False,
) -> dict:
    """Parse a scalar while retaining blank, none and censoring states."""
    token = raw.strip()

    result = {
        "raw": raw,
        "parsed_decimal": None,
        "unit": unit,
        "status": None,
        "aggregation_eligible": False,
        "censoring": None,
    }

    if token == "":
        result["status"] = "blank"
        return result

    if token.casefold() == "none":
        result["status"] = "source_none"
        return result

    if token.casefold() == "or" and is_co:
        if or_threshold_verified:
            result["status"] = "right_censored"
            result["censoring"] = {
                "operator": ">",
                "lower_bound": "1000",
                "bound_basis": "NASA BASS-II ReadMe",
            }
        else:
            result["status"] = "right_censored_threshold_unverified"
        return result

    explicit_bound = re.fullmatch(
        r">\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))",
        token,
    )

    if explicit_bound:
        result["status"] = "right_censored"
        result["censoring"] = {
            "operator": ">",
            "lower_bound": _decimal_text(Decimal(explicit_bound.group(1))),
            "bound_basis": "explicit source notation",
        }
        return result

    if token.casefold() == "over":
        result["status"] = "over_range_threshold_unspecified"
        return result

    number = _decimal(token)

    if number is None:
        result["status"] = "non_numeric_source_token"
        return result

    result["parsed_decimal"] = _decimal_text(number)

    if number < 0:
        result["status"] = "negative_numeric_requires_review"
        return result

    result["status"] = "numeric_exact"
    result["aggregation_eligible"] = True
    return result


def _parse_freeform_numeric(raw: str, unit: str | None, role: str) -> dict:
    token = raw.strip()

    result = {
        "raw": raw,
        "parsed_decimal": None,
        "unit": unit,
        "status": None,
        "aggregation_eligible": False,
    }

    if not token:
        result["status"] = "blank"
        return result

    if token.casefold() == "none":
        result["status"] = "source_none"
        return result

    if not _strict_number(token):
        result["status"] = "sequence_or_note"
        return result

    number = _decimal(token)
    if number is None:
        result["status"] = "non_numeric_source_token"
        return result

    if role == "fan_display":
        # Values may be fan display readings or potentiometer settings.
        # A single token alone does not resolve that ambiguity.
        result["status"] = "single_numeric_token_uninterpreted"
        result["candidate_decimal"] = _decimal_text(number)
        result["unit"] = None
        return result

    if role == "air_display":
        result["parsed_decimal"] = _decimal_text(number)
        result["status"] = "numeric_scalar_steady_state_unverified"
        result["aggregation_eligible"] = False
        result["steady_state_evidence"] = "not_present_in_exported_record"
        if number < 0:
            result["status"] = "negative_numeric_requires_review"
        return result

    if role == "radiometer_gain":
        allowed = {"10", "50", "250", "1000"}
        if _decimal_text(number) in allowed:
            result["status"] = "single_gain_setting"
            result["candidate_decimal"] = _decimal_text(number)
        else:
            result["status"] = "unrecognized_gain_setting"
        result["unit"] = None
        return result

    raise ValueError(f"Unknown freeform measurement role: {role}")


def _parse_frames(raw: str) -> dict:
    token = raw.strip()
    result = {
        "raw": raw,
        "parsed_integer": None,
        "unit": "frames",
        "status": None,
        "aggregation_eligible": False,
        "interpretation_note": (
            "Nikon still-frame count; not experiment duration or FPS."
        ),
    }

    if not token:
        result["status"] = "blank"
    elif token.casefold() == "none":
        result["status"] = "source_none"
    elif re.fullmatch(r"\d+", token):
        result["parsed_integer"] = int(token)
        result["status"] = "integer_frame_count"
        result["aggregation_eligible"] = True
    else:
        result["status"] = "source_descriptor"

    return result


def _parse_flow_restrictor(raw: str) -> dict:
    token = raw.strip()

    meanings = {
        "0": "highest_flow_lowest_restriction",
        "1": "intermediate_restrictor_code",
        "2": "lowest_flow_highest_restriction",
    }

    code = int(token) if token in meanings else None

    return {
        "raw": raw,
        "code": code,
        "status": "source_verified_code" if code is not None else "unrecognized_code",
        "documented_interpretation": meanings.get(token),
    }


def _parse_material(raw: str, pi: str, readme: dict) -> dict:
    token = raw.strip()
    lowered = token.casefold()

    result = {
        "raw": raw,
        "canonical_class": None,
        "mapping_status": "raw_description_only",
        "attributes": {},
        "source_evidence": None,
    }

    if "sibal" in lowered:
        if readme["sibal_composition_verified"]:
            width_match = re.search(
                r"(\d+(?:\.\d+)?)\s*cm",
                lowered,
            )

            result.update({
                "canonical_class": "SIBAL fabric",
                "mapping_status": "source_verified",
                "attributes": {
                    "composition": {
                        "cotton_percent": 75,
                        "fiberglass_percent": 25,
                    },
                    "width_cm": (
                        width_match.group(1)
                        if width_match
                        else None
                    ),
                },
                "source_evidence": {
                    "file": README_NAME,
                    "paragraphs": readme["sibal_paragraphs"],
                },
            })
        else:
            result["mapping_status"] = "sibal_mapping_not_verified"

        return result

    if "spherical section" in lowered and pi == "T'ien":
        if readme["sphere_mapping_verified"]:
            result.update({
                "canonical_class": "PMMA",
                "mapping_status": "source_verified",
                "attributes": {
                    "shape": "spherical_section",
                    "diameter_cm": 4,
                },
                "source_evidence": {
                    "file": README_NAME,
                    "paragraphs": readme["sphere_paragraphs"],
                },
            })
        return result

    if "pmma" in lowered:
        result.update({
            "canonical_class": "PMMA",
            "mapping_status": "explicit_in_source_description",
        })

    return result


def _measurement_status_counts(records: list) -> dict:
    counts = defaultdict(Counter)

    for record in records:
        for field, value in record["measurements"].items():
            counts[field][value["status"]] += 1

    return {
        field: dict(sorted(statuses.items()))
        for field, statuses in sorted(counts.items())
    }


def _json_bytes(value: dict) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def build_canonical_dataset(
    root: Path = ROOT,
    output_dir: Path | None = None,
) -> Path:
    """Build a new derived PSI-25 dataset without overwriting existing output."""
    root = Path(root).resolve()
    source_dir = root / SOURCE_RELATIVE
    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (root / DEFAULT_OUTPUT).resolve()
    )

    _require(source_dir.is_dir(), "Selected PSI-25 source directory missing")
    _require(not output.exists(), f"Refusing to overwrite existing output: {output}")

    stage = output.parent / f".{output.name}.staging"
    _require(not stage.exists(), f"Staging directory already exists: {stage}")

    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        source_info = _read_source_manifest(source_dir)

        csv_path = source_dir / CSV_NAME
        matrix_path = source_dir / MATRIX_NAME
        readme_path = source_dir / README_NAME

        with csv_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)
            csv_rows = list(reader)

        _require(len(csv_rows) == EXPECTED_RECORDS, "CSV record count mismatch")

        required_headers = {
            "PI", "Test #", "Date", "GMT", "Sample #",
            "Fuel Sample Material", "Flow restrictor",
            "Fan display", "Air display",
            "Radiometer gain   (1000   250   50   10)",
            "Total Frames Shot",
            "Calibrated  initial O2 % by vol ",
            "Calibrated final O2 % by vol",
            "Initial CO2 % by vol",
            "Final CO2 % by vol",
            "Initial CO (ppm)",
            "Final CO (ppm)",
        }
        _require(
            required_headers.issubset(set(reader.fieldnames or [])),
            "Experimental Table header mismatch",
        )

        readme = _read_readme(readme_path)
        matrix_data = _read_matrix(matrix_path)
        reconciliation = _reconcile(csv_rows, matrix_data)
        matrix_records = reconciliation.pop("_matrix_records")

        sample_counts = Counter(row["Sample #"] for row in csv_rows)

        canonical_records = []
        for logical_row, row in enumerate(csv_rows, start=2):
            pi = row["PI"].strip()
            test_id = row["Test #"].strip()
            key = (pi, test_id)
            matrix = matrix_records[key]

            date_value = _parse_csv_date(row["Date"])
            gmt_raw = row["GMT"]
            gmt_token = gmt_raw.strip()
            gmt_integer = (
                int(gmt_token)
                if re.fullmatch(r"\d+", gmt_token)
                else None
            )

            measurements = {
                "fan_display": _parse_freeform_numeric(
                    row["Fan display"],
                    None,
                    "fan_display",
                ),
                "air_display": _parse_freeform_numeric(
                    row["Air display"],
                    "cm/s",
                    "air_display",
                ),
                "radiometer_gain": _parse_freeform_numeric(
                    row["Radiometer gain   (1000   250   50   10)"],
                    None,
                    "radiometer_gain",
                ),
                "total_frames_shot": _parse_frames(
                    row["Total Frames Shot"]
                ),
                "initial_o2": _parse_quantity(
                    row["Calibrated  initial O2 % by vol "],
                    "% by volume",
                ),
                "final_o2": _parse_quantity(
                    row["Calibrated final O2 % by vol"],
                    "% by volume",
                ),
                "initial_co2": _parse_quantity(
                    row["Initial CO2 % by vol"],
                    "% by volume",
                ),
                "final_co2": _parse_quantity(
                    row["Final CO2 % by vol"],
                    "% by volume",
                ),
                "initial_co": _parse_quantity(
                    row["Initial CO (ppm)"],
                    "ppm",
                    is_co=True,
                    or_threshold_verified=readme["co_or_threshold_verified"],
                ),
                "final_co": _parse_quantity(
                    row["Final CO (ppm)"],
                    "ppm",
                    is_co=True,
                    or_threshold_verified=readme["co_or_threshold_verified"],
                ),
            }

            canonical_records.append({
                "schema": "sira.firelab.psi25.experiment.v1",
                "identity": {
                    "pi_raw": row["PI"],
                    "pi": pi,
                    "test_id_raw": row["Test #"],
                    "test_id": test_id,
                    "record_key": f"{pi}::{test_id}",
                },
                "sample": {
                    "id_raw": row["Sample #"],
                    "reuse_count_exact_raw_id": sample_counts[row["Sample #"]],
                    "is_reused_exact_raw_id": sample_counts[row["Sample #"]] > 1,
                    "case_sensitive": True,
                },
                "date": {
                    "raw": row["Date"],
                    "iso": date_value.isoformat(),
                    "status": "csv_date_verified_against_matrix",
                },
                "gmt_day_of_year": {
                    "raw": gmt_raw,
                    "integer": gmt_integer,
                    "interpretation": "source GMT day-of-year component; not a time-of-day",
                },
                "material": _parse_material(
                    row["Fuel Sample Material"],
                    pi,
                    readme,
                ),
                "flow_restrictor": _parse_flow_restrictor(
                    row["Flow restrictor"]
                ),
                "measurements": measurements,
                "source_provenance": {
                    "csv": {
                        "file": CSV_NAME,
                        "sha256": source_info["sources"][CSV_NAME]["sha256"],
                        "logical_record_number": logical_row,
                    },
                    "matrix": {
                        "file": MATRIX_NAME,
                        "sha256": source_info["sources"][MATRIX_NAME]["sha256"],
                        "worksheet": matrix["sheet"],
                        "row": matrix["row"],
                    },
                    "interpretation_reference": {
                        "file": README_NAME,
                        "sha256": source_info["sources"][README_NAME]["sha256"],
                    },
                },
            })

        _require(
            len(canonical_records) == EXPECTED_RECORDS,
            "Canonical record count mismatch",
        )

        material_status = Counter(
            record["material"]["mapping_status"]
            for record in canonical_records
        )

        quality_report = {
            "schema": "sira.firelab.psi25.quality_report.v1",
            "dataset": "NASA PSI-25 BASS-II",
            "investigation_version": 4,
            "record_count": len(canonical_records),
            "pi_record_counts": reconciliation["pi_record_counts"],
            "identity_reconciliation": {
                "csv_records": reconciliation["csv_record_count"],
                "matrix_records": reconciliation["matrix_record_count"],
                "matched_composite_identities": reconciliation["identity_match_count"],
                "core_checks": reconciliation["core_checks"],
                "field_reconciliation": reconciliation["field_reconciliation"],
            },
            "sample_reuse": {
                "distinct_exact_raw_ids": reconciliation["distinct_raw_sample_ids"],
                "reused_exact_raw_id_groups": reconciliation["reused_raw_sample_id_groups"],
                "reused_ids": reconciliation["reused_sample_ids"],
                "case_sensitive": True,
            },
            "material_mapping": {
                "status_counts": dict(sorted(material_status.items())),
                "sibal_composition_verified": readme["sibal_composition_verified"],
                "sibal_readme_paragraphs": readme["sibal_paragraphs"],
                "sphere_mapping_verified": readme["sphere_mapping_verified"],
                "sphere_readme_paragraphs": readme["sphere_paragraphs"],
            },
            "measurement_status_counts": _measurement_status_counts(
                canonical_records
            ),
            "censoring_documentation": {
                "co_or_threshold_verified": readme["co_or_threshold_verified"],
                "co_or_threshold_readme_paragraphs": readme["co_or_threshold_paragraphs"],
                "or_threshold_used_ppm": (
                    "1000" if readme["co_or_threshold_verified"] else None
                ),
            },
            "scientific_use_constraints": [
                "Raw source strings are retained; no original source was normalized.",
                "OR is right-censored only when the ReadMe verifies its >1000 ppm meaning.",
                "Explicit >N source values remain right-censored and are not replaced by N.",
                "The word 'over' has no inferred numeric threshold.",
                "Blank and literal none are separate states.",
                "Negative CO readings are retained and flagged for review.",
                "Fan display scalar tokens are not interpreted as fan voltage or potentiometer settings.",
                "Air display sequences and notes are not split into invented measurements.",
                "Single Air display scalars are not aggregation eligible without steady-state evidence.",
                "Radiometer gain is a setting, not absolute heat flux.",
                "Total Frames Shot is not experiment duration or FPS.",
                "No airflow reconstruction or fan calibration is performed.",
                "Repeated samples remain separate experiment records.",
            ],
        }

        records_bytes = _json_bytes({
            "schema": "sira.firelab.psi25.canonical_records.v1",
            "source_investigation": "PSI-25",
            "study_version": 4,
            "record_count": len(canonical_records),
            "records": canonical_records,
        })

        report_bytes = _json_bytes(quality_report)

        module_path = Path(__file__).resolve()
        canonical_manifest = {
            "schema": "sira.firelab.psi25.canonical_manifest.v1",
            "dataset": "NASA PSI-25 BASS-II",
            "study_version": 4,
            "record_count": len(canonical_records),
            "source_manifest_sha256": source_info["manifest_sha256"],
            "source_files": source_info["sources"],
            "builder": {
                "module": "tools/firelab/psi25_canonical.py",
                "sha256": _sha256_file(module_path),
            },
            "derived_files": {
                "canonical_records.json": {
                    "bytes": len(records_bytes),
                    "sha256": _sha256_bytes(records_bytes),
                },
                "quality_report.json": {
                    "bytes": len(report_bytes),
                    "sha256": _sha256_bytes(report_bytes),
                },
            },
            "deterministic_build": True,
            "original_sources_modified": False,
        }

        manifest_bytes = _json_bytes(canonical_manifest)

        stage.mkdir(parents=False, exist_ok=False)
        _write_exclusive(stage / "canonical_records.json", records_bytes)
        _write_exclusive(stage / "quality_report.json", report_bytes)
        _write_exclusive(stage / "canonical_manifest.json", manifest_bytes)

        # Verify staged output before directory promotion.
        _require(
            _sha256_file(stage / "canonical_records.json")
            == canonical_manifest["derived_files"]["canonical_records.json"]["sha256"],
            "Staged canonical records hash mismatch",
        )
        _require(
            _sha256_file(stage / "quality_report.json")
            == canonical_manifest["derived_files"]["quality_report.json"]["sha256"],
            "Staged quality report hash mismatch",
        )

        os.rename(stage, output)

        parent_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

        return output

    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def main() -> int:
    output = build_canonical_dataset()

    records = json.loads(
        (output / "canonical_records.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (output / "quality_report.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (output / "canonical_manifest.json").read_text(encoding="utf-8")
    )

    print("=" * 72)
    print("PSI-25 CANONICAL DATASET BUILD SUCCESS")
    print("=" * 72)
    print("Output:", output)
    print("Canonical records:", records["record_count"])
    print("Matched identities:", report["identity_reconciliation"]["matched_composite_identities"])
    print("Distinct exact Sample IDs:", report["sample_reuse"]["distinct_exact_raw_ids"])
    print("Reused Sample ID groups:", report["sample_reuse"]["reused_exact_raw_id_groups"])
    print("Source files:", len(manifest["source_files"]))
    print("Canonical records SHA-256:", manifest["derived_files"]["canonical_records.json"]["sha256"])
    print("Quality report SHA-256:", manifest["derived_files"]["quality_report.json"]["sha256"])
    print("Original source files modified: NO")
    print("Existing dashboard data modified: NO")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
