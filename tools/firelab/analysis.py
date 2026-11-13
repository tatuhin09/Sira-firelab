"""Reproducible summaries over validated exact measurements."""
import math
from collections import defaultdict
from statistics import mean, stdev


def _is_finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def grouped_summary(rows, *, value_column, group_column=None):
    """Summarize exact values while preserving bundle or parser quality metadata.

    Bundle records use ``quality``; parser rows use the legacy ``_quality``.
    When neither contains metadata for this field, retain the historical
    numeric-value fallback.
    """
    groups = defaultdict(lambda: {
        "values": [],
        "approximate_n": 0,
        "missing_n": 0,
        "invalid_n": 0,
    })

    for row in rows:
        key = str(row.get(group_column, "All")) if group_column else "All"
        group = groups[key]
        value = row.get(value_column)

        bundle_quality = row.get("quality")
        parser_quality = row.get("_quality")

        quality = (
            bundle_quality.get(value_column)
            if isinstance(bundle_quality, dict)
            else None
        )
        if quality is None and isinstance(parser_quality, dict):
            quality = parser_quality.get(value_column)

        if quality is None:
            quality = "exact" if _is_finite_number(value) else "invalid"

        if quality == "exact":
            if _is_finite_number(value):
                group["values"].append(float(value))
            else:
                group["invalid_n"] += 1
        elif quality == "approximate":
            if _is_finite_number(value):
                group["approximate_n"] += 1
            else:
                group["invalid_n"] += 1
        elif quality == "missing":
            group["missing_n"] += 1
        else:
            group["invalid_n"] += 1

    if not groups:
        groups["All"]

    result = []
    for key in sorted(groups):
        group = groups[key]
        values = group["values"]
        result.append({
            "group": key,
            "n": len(values),
            "approximate_n": group["approximate_n"],
            "missing_n": group["missing_n"],
            "invalid_n": group["invalid_n"],
            "mean": mean(values) if values else None,
            "sample_sd": stdev(values) if len(values) > 1 else None,
            "method": "arithmetic mean; sample standard deviation (n-1); approximate values excluded",
        })
    return result
