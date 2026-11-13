"""Hash-verified, investigation-aware evidence registry for SIRA FireLab M4.1.

This module is deliberately deterministic and model-free. It loads PSI-69 via
its existing verified loader and independently verifies the complete selected
PSI-25 BASS-II v4 artifact chain before exposing either investigation.

No SIRA Core imports, network access, arbitrary paths, or user-selected files.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .engine import load_bundle

PSI25_RELATIVE_ROOT = Path("firelab_site/data/derived/psi25_bass_ii_v4")
PSI25_EXPECTED_SYNTHESIS_MANIFEST_SHA256 = (
    "f8333aeb23e8a34a6c8448a52deb0a64fc46f3d0525e854047cdf344c2d0383b"
)
PSI25_METRICS = ("co", "co2", "o2")
PSI25_RECORD_COUNT = 129
PSI25_INSIGHT_CARD_COUNT = 54
PSI25_RESEARCH_QUESTION_COUNT = 146
_MAX_JSON_BYTES = 8 * 1024 * 1024


class EvidenceRegistryError(RuntimeError):
    """Raised when a registered investigation cannot be safely verified."""


@dataclass(frozen=True)
class InvestigationEvidence:
    """Verified evidence package for one NASA investigation/release."""

    investigation_id: str
    title: str
    source: str
    source_url: str
    version: str
    record_count: int
    source_sha256: str
    records_sha256: str
    quality_sha256: str
    payload: Mapping[str, Any]


class EvidenceRegistry:
    """Read-only allowlist of independently verified investigations."""

    def __init__(self, investigations: Mapping[str, InvestigationEvidence]):
        if not investigations:
            raise EvidenceRegistryError("No verified investigations were registered")
        self._investigations = MappingProxyType(dict(investigations))

    @property
    def investigation_ids(self) -> tuple[str, ...]:
        return tuple(self._investigations.keys())

    def get(self, investigation_id: str) -> InvestigationEvidence:
        if not isinstance(investigation_id, str):
            raise EvidenceRegistryError("Investigation identifier must be text")
        try:
            return self._investigations[investigation_id]
        except KeyError as exc:
            raise EvidenceRegistryError("Investigation is not in the approved registry") from exc

    def as_mapping(self) -> Mapping[str, InvestigationEvidence]:
        return self._investigations


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_inside(root: Path, parent: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise EvidenceRegistryError(f"{label}: missing relative path")
    candidate = (parent / relative).resolve(strict=True)
    if not _inside(root.resolve(strict=True), candidate) or not candidate.is_file():
        raise EvidenceRegistryError(f"{label}: path escapes the approved evidence root")
    return candidate


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        size = path.stat().st_size
        if size < 2 or size > _MAX_JSON_BYTES:
            raise EvidenceRegistryError(f"{label}: JSON byte size is outside the permitted bound")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except EvidenceRegistryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceRegistryError(f"{label}: JSON could not be read safely") from exc
    if not isinstance(value, dict):
        raise EvidenceRegistryError(f"{label}: JSON root must be an object")
    return value, raw


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _verify_digest(path: Path, expected: object, label: str, expected_bytes: object = None) -> str:
    if not isinstance(expected, str) or len(expected) != 64:
        raise EvidenceRegistryError(f"{label}: manifest SHA-256 is invalid")
    if expected_bytes is not None:
        if type(expected_bytes) is not int or expected_bytes < 0 or path.stat().st_size != expected_bytes:
            raise EvidenceRegistryError(f"{label}: manifest byte count mismatch")
    actual = _sha256_file(path)
    if actual != expected:
        raise EvidenceRegistryError(f"{label}: SHA-256 mismatch")
    return actual


def _verify_builder(repo_root: Path, manifest: Mapping[str, Any], label: str) -> None:
    builder = manifest.get("builder")
    if not isinstance(builder, dict):
        raise EvidenceRegistryError(f"{label}: builder lineage is missing")
    path = _resolve_inside(repo_root, repo_root, builder.get("path") or builder.get("module"), f"{label} builder")
    _verify_digest(path, builder.get("sha256"), f"{label} builder")


def _verify_artifact_references(repo_root: Path, manifest_path: Path,
                                manifest: Mapping[str, Any], label: str,
                                evidence_root: Path | None = None) -> None:
    sources = manifest.get("source_artifacts")
    if not isinstance(sources, dict) or not sources:
        raise EvidenceRegistryError(f"{label}: upstream artifact references are missing")
    root = repo_root.resolve(strict=True)
    for key, spec in sources.items():
        if not isinstance(spec, dict):
            raise EvidenceRegistryError(f"{label}: malformed upstream reference {key}")
        relative = spec.get("path")
        expected = spec.get("sha256")
        if not isinstance(relative, str) or not relative or not isinstance(expected, str):
            raise EvidenceRegistryError(f"{label}: incomplete upstream reference {key}")
        # Builders in this repository have used both manifest-directory-relative
        # and repository-relative provenance paths. Accept either only when the
        # recorded SHA-256 selects exactly one in-repository file.
        candidates: set[Path] = set()
        search_parents = [manifest_path.parent]
        if evidence_root is not None:
            search_parents.append(evidence_root)
        search_parents.append(root)
        for parent in search_parents:
            try:
                candidate = (parent / relative).resolve(strict=True)
            except OSError:
                continue
            if _inside(root, candidate) and candidate.is_file():
                candidates.add(candidate)
        matches = [path for path in candidates if _sha256_file(path) == expected]
        if len(matches) != 1:
            raise EvidenceRegistryError(f"{label}: upstream artifact {key} is missing, ambiguous, or has a SHA-256 mismatch")
        _verify_digest(matches[0], expected, f"{label} upstream {key}", spec.get("bytes"))


def _verify_derived_output(manifest_path: Path, manifest: Mapping[str, Any], label: str) -> Path:
    output = manifest.get("derived_output")
    if not isinstance(output, dict):
        raise EvidenceRegistryError(f"{label}: derived output reference is missing")
    path = _resolve_inside(manifest_path.parent, manifest_path.parent, output.get("path"), f"{label} derived output")
    _verify_digest(path, output.get("sha256"), f"{label} derived output", output.get("bytes"))
    return path


def _verify_psi25(root: Path) -> dict[str, Any]:
    repo_root = root.resolve(strict=True)
    evidence_root = (repo_root / PSI25_RELATIVE_ROOT).resolve(strict=True)
    if not _inside(repo_root, evidence_root):
        raise EvidenceRegistryError("PSI-25 evidence root escapes the approved repository root")
    if not evidence_root.is_dir():
        raise EvidenceRegistryError("PSI-25 evidence root is not a directory")

    # Resolve every manifest through the repository boundary. Checking only
    # evidence_root is insufficient: a nested version directory or manifest
    # file could itself be a symlink to a path outside the repository.
    canonical_manifest_path = _resolve_inside(
        repo_root, repo_root,
        (PSI25_RELATIVE_ROOT / "canonical_manifest.json").as_posix(),
        "PSI-25 canonical manifest",
    )
    paired_manifest_path = _resolve_inside(
        repo_root, repo_root,
        (PSI25_RELATIVE_ROOT / "paired_analysis_v1" / "analysis_manifest.json").as_posix(),
        "PSI-25 paired-analysis manifest",
    )
    findings_manifest_path = _resolve_inside(
        repo_root, repo_root,
        (PSI25_RELATIVE_ROOT / "findings_ranking_v1" / "findings_manifest.json").as_posix(),
        "PSI-25 findings manifest",
    )
    synthesis_manifest_path = _resolve_inside(
        repo_root, repo_root,
        (PSI25_RELATIVE_ROOT / "evidence_synthesis_v1" / "synthesis_manifest.json").as_posix(),
        "PSI-25 synthesis manifest",
    )

    # Pin the terminal manifest as the trust anchor for this reviewed release.
    _verify_digest(
        synthesis_manifest_path,
        PSI25_EXPECTED_SYNTHESIS_MANIFEST_SHA256,
        "PSI-25 synthesis manifest trust anchor",
    )

    canonical_manifest, _ = _read_json(canonical_manifest_path, "PSI-25 canonical manifest")
    if canonical_manifest.get("schema") != "sira.firelab.psi25.canonical_manifest.v1":
        raise EvidenceRegistryError("PSI-25 canonical manifest schema mismatch")
    if canonical_manifest.get("record_count") != PSI25_RECORD_COUNT or canonical_manifest.get("study_version") != 4:
        raise EvidenceRegistryError("PSI-25 canonical release scope mismatch")
    _verify_builder(root, canonical_manifest, "PSI-25 canonical builder")

    provenance_path = _resolve_inside(
        root,
        root,
        "firelab_site/data/source/PSI-25_BASS-II_v4_selected/provenance.json",
        "PSI-25 source provenance",
    )
    _verify_digest(provenance_path, canonical_manifest.get("source_manifest_sha256"), "PSI-25 source provenance")

    source_files = canonical_manifest.get("source_files")
    derived_files = canonical_manifest.get("derived_files")
    if not isinstance(source_files, dict) or not isinstance(derived_files, dict):
        raise EvidenceRegistryError("PSI-25 canonical manifest file inventory is malformed")
    if "PSI-25_Experimental table_BASS-II.csv" not in source_files:
        raise EvidenceRegistryError("PSI-25 canonical manifest omits the selected experimental CSV")
    if not {"canonical_records.json", "quality_report.json"}.issubset(derived_files):
        raise EvidenceRegistryError("PSI-25 canonical manifest omits a required derived artifact")
    for filename, spec in source_files.items():
        if not isinstance(spec, dict):
            raise EvidenceRegistryError(f"PSI-25 source inventory entry is malformed: {filename}")
        source_path = _resolve_inside(root, root, spec.get("path"), f"PSI-25 source {filename}")
        _verify_digest(source_path, spec.get("sha256"), f"PSI-25 source {filename}", spec.get("bytes"))
    for filename, spec in derived_files.items():
        if not isinstance(spec, dict):
            raise EvidenceRegistryError(f"PSI-25 derived inventory entry is malformed: {filename}")
        derived_path = _resolve_inside(evidence_root, evidence_root, filename, f"PSI-25 canonical derived {filename}")
        _verify_digest(derived_path, spec.get("sha256"), f"PSI-25 canonical derived {filename}", spec.get("bytes"))

    canonical_path = _resolve_inside(
        evidence_root, evidence_root, "canonical_records.json", "PSI-25 canonical records"
    )
    quality_path = _resolve_inside(
        evidence_root, evidence_root, "quality_report.json", "PSI-25 quality report"
    )
    canonical, _ = _read_json(canonical_path, "PSI-25 canonical records")
    quality, _ = _read_json(quality_path, "PSI-25 quality report")
    records = canonical.get("records")
    if canonical.get("schema") != "sira.firelab.psi25.canonical_records.v1" or not isinstance(records, list):
        raise EvidenceRegistryError("PSI-25 canonical record schema is invalid")
    if canonical.get("record_count") != PSI25_RECORD_COUNT or len(records) != PSI25_RECORD_COUNT:
        raise EvidenceRegistryError("PSI-25 canonical record count mismatch")
    if quality.get("record_count") != PSI25_RECORD_COUNT or quality.get("schema") != "sira.firelab.psi25.quality_report.v1":
        raise EvidenceRegistryError("PSI-25 quality report scope mismatch")

    record_keys: set[str] = set()
    for record in records:
        identity = record.get("identity") if isinstance(record, dict) else None
        key = identity.get("record_key") if isinstance(identity, dict) else None
        if not isinstance(key, str) or not key or key in record_keys:
            raise EvidenceRegistryError("PSI-25 canonical record keys are missing or duplicated")
        record_keys.add(key)
    if len(record_keys) != PSI25_RECORD_COUNT:
        raise EvidenceRegistryError("PSI-25 canonical record key coverage mismatch")

    paired_manifest, _ = _read_json(paired_manifest_path, "PSI-25 paired-analysis manifest")
    if paired_manifest.get("schema") != "sira.psi25.paired_analysis_manifest.v1":
        raise EvidenceRegistryError("PSI-25 paired-analysis manifest schema mismatch")
    if paired_manifest.get("record_count") != PSI25_RECORD_COUNT or paired_manifest.get("study_version") != 4:
        raise EvidenceRegistryError("PSI-25 paired-analysis scope mismatch")
    _verify_builder(root, paired_manifest, "PSI-25 paired-analysis builder")
    _verify_artifact_references(
        root, paired_manifest_path, paired_manifest,
        "PSI-25 paired analysis", evidence_root,
    )
    paired_path = _verify_derived_output(paired_manifest_path, paired_manifest, "PSI-25 paired analysis")
    paired, _ = _read_json(paired_path, "PSI-25 paired analysis")
    if paired.get("record_count") != PSI25_RECORD_COUNT or not isinstance(paired.get("metrics"), dict):
        raise EvidenceRegistryError("PSI-25 paired-analysis payload scope mismatch")
    if set(paired["metrics"]) != set(PSI25_METRICS):
        raise EvidenceRegistryError("PSI-25 paired-analysis metrics mismatch")
    for metric in PSI25_METRICS:
        item = paired["metrics"][metric]
        audit = item.get("record_level_audit") if isinstance(item, dict) else None
        cohorts = item.get("cohort_summaries") if isinstance(item, dict) else None
        if not isinstance(audit, list) or len(audit) != PSI25_RECORD_COUNT or not isinstance(cohorts, list) or len(cohorts) != 18:
            raise EvidenceRegistryError(f"PSI-25 {metric.upper()} paired evidence scope mismatch")
        keys = [row.get("record_key") for row in audit if isinstance(row, dict)]
        if len(keys) != PSI25_RECORD_COUNT or set(keys) != record_keys or len(set(keys)) != PSI25_RECORD_COUNT:
            raise EvidenceRegistryError(f"PSI-25 {metric.upper()} paired record-key lineage mismatch")

    findings_manifest, _ = _read_json(findings_manifest_path, "PSI-25 findings manifest")
    if findings_manifest.get("schema") != "sira.psi25.findings_manifest.v1":
        raise EvidenceRegistryError("PSI-25 findings manifest schema mismatch")
    if findings_manifest.get("record_count") != PSI25_RECORD_COUNT or findings_manifest.get("study_version") != 4:
        raise EvidenceRegistryError("PSI-25 findings scope mismatch")
    _verify_builder(root, findings_manifest, "PSI-25 findings builder")
    _verify_artifact_references(
        root, findings_manifest_path, findings_manifest,
        "PSI-25 findings", evidence_root,
    )
    findings_path = _verify_derived_output(findings_manifest_path, findings_manifest, "PSI-25 findings")
    findings, _ = _read_json(findings_path, "PSI-25 findings ranking")
    if findings.get("record_count") != PSI25_RECORD_COUNT or set(findings.get("metrics", {})) != set(PSI25_METRICS):
        raise EvidenceRegistryError("PSI-25 findings payload scope mismatch")
    if findings.get("causal_claims_produced") is not False or findings.get("cross_metric_ranking") is not False or findings.get("inferential_statistics_produced") is not False:
        raise EvidenceRegistryError("PSI-25 findings scientific safeguards mismatch")
    for metric in PSI25_METRICS:
        item = findings["metrics"][metric]
        ranked = item.get("ranked_cohorts")
        unranked = item.get("not_rankable_cohorts")
        if not isinstance(ranked, list) or not isinstance(unranked, list) or item.get("cohort_count") != 18:
            raise EvidenceRegistryError(f"PSI-25 {metric.upper()} findings cohort scope mismatch")
        seen: list[str] = []
        for cohort in ranked + unranked:
            if not isinstance(cohort, dict):
                raise EvidenceRegistryError(f"PSI-25 {metric.upper()} findings cohort is malformed")
            for evidence_key in ("eligible_record_evidence", "excluded_record_evidence"):
                rows = cohort.get(evidence_key)
                if not isinstance(rows, list):
                    raise EvidenceRegistryError(f"PSI-25 {metric.upper()} findings evidence list is malformed")
                for row in rows:
                    key = row.get("record_key") if isinstance(row, dict) else None
                    if not isinstance(key, str) or key not in record_keys:
                        raise EvidenceRegistryError(f"PSI-25 {metric.upper()} findings contains an unknown record key")
                    seen.append(key)
        if len(seen) != PSI25_RECORD_COUNT or set(seen) != record_keys or len(set(seen)) != PSI25_RECORD_COUNT:
            raise EvidenceRegistryError(f"PSI-25 {metric.upper()} findings do not cover every canonical record exactly once")

    synthesis_manifest, _ = _read_json(synthesis_manifest_path, "PSI-25 synthesis manifest")
    if synthesis_manifest.get("schema") != "sira.psi25.evidence_synthesis_manifest.v1":
        raise EvidenceRegistryError("PSI-25 synthesis manifest schema mismatch")
    if synthesis_manifest.get("record_count") != PSI25_RECORD_COUNT or synthesis_manifest.get("study_version") != 4:
        raise EvidenceRegistryError("PSI-25 synthesis scope mismatch")
    if synthesis_manifest.get("insight_card_count") != PSI25_INSIGHT_CARD_COUNT or synthesis_manifest.get("research_question_count") != PSI25_RESEARCH_QUESTION_COUNT:
        raise EvidenceRegistryError("PSI-25 synthesis manifest counts mismatch")
    _verify_builder(root, synthesis_manifest, "PSI-25 synthesis builder")
    _verify_artifact_references(
        root, synthesis_manifest_path, synthesis_manifest,
        "PSI-25 synthesis", evidence_root,
    )
    synthesis_path = _verify_derived_output(synthesis_manifest_path, synthesis_manifest, "PSI-25 synthesis")
    synthesis, _ = _read_json(synthesis_path, "PSI-25 evidence synthesis")
    if synthesis.get("record_count") != PSI25_RECORD_COUNT or set(synthesis.get("metrics", {})) != set(PSI25_METRICS):
        raise EvidenceRegistryError("PSI-25 synthesis payload scope mismatch")
    if synthesis.get("insight_card_count") != PSI25_INSIGHT_CARD_COUNT or not isinstance(synthesis.get("research_questions"), list) or len(synthesis["research_questions"]) != PSI25_RESEARCH_QUESTION_COUNT:
        raise EvidenceRegistryError("PSI-25 synthesis payload counts mismatch")
    if synthesis.get("generated_with_llm") is not False:
        raise EvidenceRegistryError("PSI-25 synthesis must remain deterministic and non-LLM-generated")
    safeguards = synthesis.get("safeguards")
    required_false = (
        "causal_claims_produced", "cross_metric_ranking", "independent_sample_inference",
        "inferential_statistics_produced", "llm_generated_measurements_or_claims",
        "numeric_imputation", "operational_fire_safety_recommendations",
    )
    if not isinstance(safeguards, dict) or any(safeguards.get(key) is not False for key in required_false):
        raise EvidenceRegistryError("PSI-25 synthesis scientific safeguards mismatch")
    for metric in PSI25_METRICS:
        item = synthesis["metrics"][metric]
        cards = item.get("insight_cards") if isinstance(item, dict) else None
        if not isinstance(cards, list) or len(cards) != 18:
            raise EvidenceRegistryError(f"PSI-25 {metric.upper()} synthesis card count mismatch")
        seen: list[str] = []
        for card in cards:
            if not isinstance(card, dict) or not isinstance(card.get("insight_id"), str):
                raise EvidenceRegistryError(f"PSI-25 {metric.upper()} synthesis card is malformed")
            eligible = card.get("supporting_record_evidence")
            excluded = card.get("excluded_record_evidence")
            if not isinstance(eligible, list) or not isinstance(excluded, list):
                raise EvidenceRegistryError(f"PSI-25 {metric.upper()} synthesis evidence arrays are malformed")
            if len(eligible) != card.get("eligible_pairs") or len(excluded) != card.get("excluded_pairs"):
                raise EvidenceRegistryError(f"PSI-25 {metric.upper()} synthesis pair accounting mismatch")
            if card.get("records_in_cohort") != len(eligible) + len(excluded):
                raise EvidenceRegistryError(f"PSI-25 {metric.upper()} synthesis cohort accounting mismatch")
            for row in eligible + excluded:
                key = row.get("record_key") if isinstance(row, dict) else None
                if not isinstance(key, str) or key not in record_keys:
                    raise EvidenceRegistryError(f"PSI-25 {metric.upper()} synthesis contains an unknown record key")
                seen.append(key)
        if len(seen) != PSI25_RECORD_COUNT or set(seen) != record_keys or len(set(seen)) != PSI25_RECORD_COUNT:
            raise EvidenceRegistryError(f"PSI-25 {metric.upper()} synthesis does not cover every canonical record exactly once")

    # Explicitly retain the source caveats needed by any later SI explanation.
    caveat = synthesis.get("measurement_provenance_caveats", {}).get("o2")
    if not isinstance(caveat, dict) or not caveat.get("interpretation_limit"):
        raise EvidenceRegistryError("PSI-25 oxygen calibration caveat is missing")
    constraints = synthesis.get("scientific_use_constraints")
    if not isinstance(constraints, list) or len(constraints) < 5:
        raise EvidenceRegistryError("PSI-25 scientific-use constraints are missing")

    return {
        "canonical_manifest": canonical_manifest,
        "canonical": canonical,
        "quality": quality,
        "paired_manifest": paired_manifest,
        "paired": paired,
        "findings_manifest": findings_manifest,
        "findings": findings,
        "synthesis_manifest": synthesis_manifest,
        "synthesis": synthesis,
        "record_keys": tuple(sorted(record_keys)),
        "source_sha256": source_files["PSI-25_Experimental table_BASS-II.csv"]["sha256"],
        "artifact_sha256": {
            "canonical_manifest": _sha256_file(canonical_manifest_path),
            "canonical_records": _sha256_file(canonical_path),
            "quality_report": _sha256_file(quality_path),
            "paired_manifest": _sha256_file(paired_manifest_path),
            "paired_analysis": _sha256_file(paired_path),
            "findings_manifest": _sha256_file(findings_manifest_path),
            "findings": _sha256_file(findings_path),
            "synthesis_manifest": _sha256_file(synthesis_manifest_path),
            "synthesis": _sha256_file(synthesis_path),
        },
    }


def load_evidence_registry(repo_root: str | Path) -> EvidenceRegistry:
    """Load PSI-69 and PSI-25 as separate, hash-verified registry entries."""
    root = Path(repo_root).resolve(strict=True)
    site_root = root / "firelab_site"
    try:
        flex = load_bundle(site_root)
    except Exception as exc:
        raise EvidenceRegistryError("PSI-69 FLEX bundle verification failed") from exc
    flex_manifest = flex.get("manifest")
    if not isinstance(flex_manifest, dict) or flex_manifest.get("recordCount") != len(flex.get("records", [])):
        raise EvidenceRegistryError("PSI-69 manifest/record count mismatch")

    psi69 = InvestigationEvidence(
        investigation_id="psi69-flex-v5",
        title=flex_manifest.get("title", "Flame Extinguishment Experiment"),
        source=flex_manifest.get("source", "NASA PSI-69"),
        source_url=flex_manifest.get("sourceUrl", ""),
        version=flex_manifest.get("sourceVersion", "PSI-69 Version 5"),
        record_count=len(flex["records"]),
        source_sha256=flex.get("sourceSha256", ""),
        records_sha256=flex.get("recordsSha256", ""),
        quality_sha256=flex.get("qualitySha256", ""),
        payload=MappingProxyType({"bundle": flex}),
    )

    try:
        bass = _verify_psi25(root)
    except EvidenceRegistryError:
        raise
    except Exception as exc:
        raise EvidenceRegistryError("PSI-25 BASS-II v4 verification failed") from exc

    psi25 = InvestigationEvidence(
        investigation_id="psi25-bass-ii-v4",
        title="BASS-II",
        source="NASA PSI-25",
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
        version="Study Version 4",
        record_count=PSI25_RECORD_COUNT,
        source_sha256=bass["source_sha256"],
        records_sha256=bass["artifact_sha256"]["canonical_records"],
        quality_sha256=bass["artifact_sha256"]["quality_report"],
        payload=MappingProxyType(bass),
    )
    return EvidenceRegistry({psi69.investigation_id: psi69, psi25.investigation_id: psi25})
