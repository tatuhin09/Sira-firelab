"""FireLab deterministic evidence engine.

Python port of ``firelab_site/condition-analysis.js`` plus the pure helpers that
live in ``firelab_site/app.js`` (``countsBy``, ``exactMeasurementSummary`` and the
oxygen-sensitivity composition).

Rules:
* standard library only; no SIRA imports, no network, no file writes;
* record and result keys keep the JSON/JS names (camelCase) so results can be
  compared with the browser output and serialised unchanged;
* same formulas and same operation order as the JavaScript (parity-tested);
* nothing is imputed: only values whose ``quality`` is "exact" are used.

Intentional differences from the JavaScript (Python is stricter):
* numeric strings must look like plain decimals (no "0x10", "1_0", whitespace-only);
* booleans are never accepted as numbers;
* non-mapping records are skipped;
* ties between fuel names use casefold then swapcase, an approximation of
  ``localeCompare`` that is exact for ordinary ASCII fuel names.

Known quirk copied on purpose for parity: ``exact_measurement_summary`` counts a
row as "missing" when its quality is "missing" OR its value is null, so a row
whose quality is "invalid" and whose value is null is counted as both.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

OUTCOME_ORDER = ("Extinction", "Disruption", "Completion")
CONDITION_FIELDS = (
    "ambientPressureMmHg",
    "oxygenMoleFraction",
    "coSourceMoleFraction",
    "heliumMoleFraction",
)
UNSPECIFIED_FUEL = "Unspecified fuel"
Z_95 = 1.959963984540054
FIXED_OXYGEN = 0.21
SENSITIVITY_FIXED_KEYS = ("pressureMin", "pressureMax", "coSourceMoleFraction", "heliumMoleFraction")

ERR_PRESSURE = "Enter valid minimum and maximum pressure values."
ERR_PRESSURE_ORDER = "Minimum pressure must be less than or equal to maximum pressure."
ERR_GAS = "Choose an exact numeric gas fraction or Any exact value."

_DECIMAL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


# ---------------------------------------------------------------- helpers
def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_integer(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value) and value.is_integer()


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _quality_of(record: Any, field: str) -> Any:
    if not isinstance(record, Mapping):
        return None
    quality = record.get("quality")
    if not isinstance(quality, Mapping):
        return None
    return quality.get(field)


def _locale_key(value: Any) -> tuple[str, str]:
    text = str(value)
    return (text.casefold(), text.swapcase())


def normalize_optional_number(value: Any) -> Any:
    """None for "not set", NaN for "set but invalid", otherwise the number."""
    if value is None or (isinstance(value, str) and value == ""):
        return None
    if isinstance(value, bool):
        return math.nan
    if isinstance(value, (int, float)):
        return value if _is_finite_number(value) else math.nan
    if isinstance(value, str):
        text = value.strip()
        if _DECIMAL.fullmatch(text):
            number = float(text)
            return number if math.isfinite(number) else math.nan
        return math.nan
    return math.nan


def exact_condition_value(record: Any, field: str) -> Any:
    if _quality_of(record, field) != "exact":
        return None
    value = record.get(field)
    return value if _is_finite_number(value) else None


# ---------------------------------------------------------------- filtering
def filter_records(records: Any, filters: Any = None) -> dict[str, Any]:
    if not isinstance(filters, Mapping):
        filters = {}
    pressure_min = normalize_optional_number(filters.get("pressureMin"))
    pressure_max = normalize_optional_number(filters.get("pressureMax"))
    oxygen = normalize_optional_number(filters.get("oxygenMoleFraction"))
    co_source = normalize_optional_number(filters.get("coSourceMoleFraction"))
    helium = normalize_optional_number(filters.get("heliumMoleFraction"))

    if any(v is None or _is_nan(v) for v in (pressure_min, pressure_max)):
        return {"rows": [], "error": ERR_PRESSURE}
    if pressure_min > pressure_max:
        return {"rows": [], "error": ERR_PRESSURE_ORDER}
    if any(_is_nan(v) for v in (oxygen, co_source, helium)):
        return {"rows": [], "error": ERR_GAS}

    rows = []
    for record in records if isinstance(records, (list, tuple)) else []:
        values = [exact_condition_value(record, field) for field in CONDITION_FIELDS]
        if any(v is None for v in values):
            continue
        pressure_value, oxygen_value, co_value, helium_value = values
        if (
            pressure_min <= pressure_value <= pressure_max
            and (oxygen is None or oxygen_value == oxygen)
            and (co_source is None or co_value == co_source)
            and (helium is None or helium_value == helium)
        ):
            rows.append(record)
    return {"rows": rows, "error": None}


# ---------------------------------------------------------------- statistics
def wilson_interval(successes: Any, total: Any, z: float = Z_95) -> dict[str, Any]:
    if (
        not _is_integer(successes)
        or not _is_integer(total)
        or total <= 0
        or successes < 0
        or successes > total
    ):
        return {"low": None, "high": None}
    proportion = successes / total
    z_squared = z * z
    denominator = 1 + z_squared / total
    center = (proportion + z_squared / (2 * total)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) / total) + (z_squared / (4 * total * total))) / denominator
    return {
        "low": 0.0 if successes == 0 else max(0.0, center - margin),
        "high": 1.0 if successes == total else min(1.0, center + margin),
    }


def _median(values: list[float]) -> Any:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def summarize_by_fuel(rows: Any) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping]] = {}
    for record in rows if isinstance(rows, (list, tuple)) else []:
        if not isinstance(record, Mapping):
            continue
        fuel = record.get("fuel") or UNSPECIFIED_FUEL
        if not isinstance(fuel, str):
            fuel = str(fuel)
        grouped.setdefault(fuel, []).append(record)

    result = []
    for fuel, fuel_records in grouped.items():
        n = len(fuel_records)
        outcomes = {name: 0 for name in OUTCOME_ORDER}
        for record in fuel_records:
            test_end = record.get("testEnd")
            if isinstance(test_end, str) and test_end in outcomes:
                outcomes[test_end] += 1

        outcome_summaries = []
        for outcome in OUTCOME_ORDER:
            count = outcomes[outcome]
            interval = wilson_interval(count, n)
            outcome_summaries.append({
                "outcome": outcome,
                "count": count,
                "share": count / n if n else 0,
                "ciLow": interval["low"],
                "ciHigh": interval["high"],
            })

        values: list[float] = []
        approximate = missing = invalid = 0
        for record in fuel_records:
            if record.get("testEnd") != "Extinction":
                continue
            quality = _quality_of(record, "visibleFlameExtinctionDiameterMm")
            value = record.get("visibleFlameExtinctionDiameterMm")
            if quality == "exact" and _is_finite_number(value):
                values.append(float(value))
            elif quality == "approximate":
                approximate += 1
            elif quality == "invalid":
                invalid += 1
            else:
                missing += 1
        values.sort()

        result.append({
            "fuel": fuel,
            "n": n,
            "outcomes": outcomes,
            "outcomeSummaries": outcome_summaries,
            "extinctionDiameter": {
                "exact": len(values),
                "approximate": approximate,
                "missing": missing,
                "invalid": invalid,
                "median": _median(values),
                "min": values[0] if values else None,
                "max": values[-1] if values else None,
            },
        })
    result.sort(key=lambda group: (-group["n"], _locale_key(group["fuel"])))
    return result


def _find_summary(summaries: Any, outcome: str) -> Any:
    for item in summaries:
        if isinstance(item, Mapping) and item.get("outcome") == outcome:
            return item
    return None


def _valid_summary(summary: Any, group_size: Any) -> bool:
    return (
        summary is not None
        and _is_integer(summary.get("count"))
        and summary["count"] >= 0
        and summary["count"] <= group_size
    )


def rank_outcome_share_gaps(groups: Any) -> list[dict[str, Any]]:
    candidates = groups if isinstance(groups, (list, tuple)) else []
    valid = [
        group for group in candidates
        if isinstance(group, Mapping)
        and _is_integer(group.get("n"))
        and group["n"] > 0
        and isinstance(group.get("outcomeSummaries"), (list, tuple))
    ]
    valid.sort(key=lambda group: _locale_key(group.get("fuel")))

    comparisons = []
    for left_index in range(len(valid)):
        for right_index in range(left_index + 1, len(valid)):
            left_group, right_group = valid[left_index], valid[right_index]
            for outcome in OUTCOME_ORDER:
                left_summary = _find_summary(left_group["outcomeSummaries"], outcome)
                right_summary = _find_summary(right_group["outcomeSummaries"], outcome)
                if not (_valid_summary(left_summary, left_group["n"]) and _valid_summary(right_summary, right_group["n"])):
                    continue
                left = {
                    "fuel": str(left_group.get("fuel") or UNSPECIFIED_FUEL),
                    "count": left_summary["count"],
                    "n": left_group["n"],
                    "share": left_summary["count"] / left_group["n"],
                }
                right = {
                    "fuel": str(right_group.get("fuel") or UNSPECIFIED_FUEL),
                    "count": right_summary["count"],
                    "n": right_group["n"],
                    "share": right_summary["count"] / right_group["n"],
                }
                delta = left["share"] - right["share"]
                comparisons.append({
                    "outcome": outcome,
                    "left": left,
                    "right": right,
                    "gap": abs(delta),
                    "gapPercentagePoints": abs(delta) * 100,
                    "higherShareFuel": left["fuel"] if delta > 0 else right["fuel"] if delta < 0 else None,
                })

    order = {name: index for index, name in enumerate(OUTCOME_ORDER)}
    comparisons.sort(key=lambda item: (
        -item["gap"],
        order[item["outcome"]],
        _locale_key(item["left"]["fuel"]),
        _locale_key(item["right"]["fuel"]),
    ))
    return comparisons


# ---------------------------------------------------------------- app.js helpers
def counts_by(records: Any, field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in records if isinstance(records, (list, tuple)) else []:
        value = row.get(field) if isinstance(row, Mapping) else None
        if isinstance(value, str) and value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def exact_measurement_summary(rows: Any, key: str) -> dict[str, Any]:
    exact: list[float] = []
    approximate = missing = invalid = 0
    for row in rows if isinstance(rows, (list, tuple)) else []:
        if not isinstance(row, Mapping):
            continue
        quality = _quality_of(row, key)
        value = row.get(key)
        if quality == "exact" and _is_finite_number(value):
            exact.append(float(value))
        if quality == "approximate":
            approximate += 1
        if quality == "missing" or value is None:
            missing += 1
        if quality == "invalid":
            invalid += 1

    mean = None
    sd = None
    if exact:
        total = 0.0
        for value in exact:
            total += value
        mean = total / len(exact)
    if len(exact) > 1:
        squares = 0.0
        for value in exact:
            squares += (value - mean) * (value - mean)
        sd = math.sqrt(squares / (len(exact) - 1))
    return {"n": len(exact), "mean": mean, "sd": sd, "approximate": approximate, "missing": missing, "invalid": invalid}


# ---------------------------------------------------------------- compositions
def condition_evidence(records: Any, filters: Any) -> dict[str, Any]:
    result = filter_records(records, filters)
    groups = summarize_by_fuel(result["rows"])
    return {
        "error": result["error"],
        "matchedCount": len(result["rows"]),
        "testNumbers": [row.get("testNumber") for row in result["rows"]],
        "groups": groups,
        "ranking": rank_outcome_share_gaps(groups),
    }


def oxygen_sensitivity(records: Any, filters: Any) -> dict[str, Any]:
    if not isinstance(filters, Mapping):
        return {
            "status": "unavailable",
            "message": "Sensitivity comparison is unavailable until the condition filters are ready.",
        }
    fixed = {key: filters.get(key) for key in SENSITIVITY_FIXED_KEYS}
    definitions = (("Fixed oxygen \u00b7 0.21", FIXED_OXYGEN), ("All exact oxygen values", None))
    slices = []
    for label, oxygen in definitions:
        result = filter_records(records, {**fixed, "oxygenMoleFraction": oxygen})
        slices.append({
            "label": label,
            "oxygenMoleFraction": oxygen,
            "rows": result["rows"],
            "error": result["error"],
            "groups": summarize_by_fuel(result["rows"]),
        })

    invalid = next((s for s in slices if s["error"]), None)
    if invalid:
        return {"status": "unavailable", "message": f"Sensitivity comparison unavailable: {invalid['error']}"}
    insufficient = next((s for s in slices if not rank_outcome_share_gaps(s["groups"])), None)
    if insufficient:
        count = len(insufficient["groups"])
        return {
            "status": "unavailable",
            "message": (
                "At least two fuel groups with matched records are needed in both slices. "
                f"{insufficient['label']} has {count} fuel group{'' if count == 1 else 's'}."
            ),
        }

    ranked = [{
        "label": s["label"],
        "oxygenMoleFraction": s["oxygenMoleFraction"],
        "n": len(s["rows"]),
        "groups": s["groups"],
        "ranked": rank_outcome_share_gaps(s["groups"]),
    } for s in slices]
    fixed_order = [item["outcome"] for item in ranked[0]["ranked"]]
    broad_order = [item["outcome"] for item in ranked[1]["ranked"]]
    return {
        "status": "ok",
        "message": None,
        "slices": ranked,
        "fixedOrder": fixed_order,
        "broadOrder": broad_order,
        "orderChanged": fixed_order != broad_order,
    }


# ---------------------------------------------------------------- bundle loading
def load_bundle(site_dir: str | Path) -> dict[str, Any]:
    """Load the static bundle and verify all three source/bundle hashes."""
    data_dir = Path(site_dir) / "data"
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))

    quality_bytes = (data_dir / "quality.json").read_bytes()
    records_bytes = (data_dir / "records.json").read_bytes()
    hash_specs = (
        ("qualitySha256", quality_bytes, "quality.json"),
        ("recordsSha256", records_bytes, "records.json"),
    )
    verified_hashes: dict[str, str] = {}
    for field, content, label in hash_specs:
        expected = manifest.get(field)
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError(f"Manifest {field} is missing or invalid")
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise ValueError(f"{label} hash does not match manifest.{field}")
        verified_hashes[field] = actual

    quality = json.loads(quality_bytes.decode("utf-8"))
    records = json.loads(records_bytes.decode("utf-8"))
    source = data_dir / "source" / manifest["sourceFile"]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != manifest["sourceSha256"]:
        raise ValueError("Source CSV hash does not match manifest.sourceSha256")
    if not isinstance(records, list) or len(records) != manifest["recordCount"]:
        raise ValueError("records.json count does not match manifest.recordCount")
    return {
        "manifest": manifest,
        "quality": quality,
        "records": records,
        "sourceSha256": digest,
        "recordsSha256": verified_hashes["recordsSha256"],
        "qualitySha256": verified_hashes["qualitySha256"],
    }
