"""Bounded adapter joining verified FireLab findings to SIRA scholarly retrieval.

The adapter consumes the existing PaperSearchService (which delegates to the
isolated SIRA Core worker) and a completed, already-validated FireLab answer.
It does not import SIRA Core, call providers directly, run calculations, or
claim that retrieved literature verifies NASA dataset measurements.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from .claim_ledger import OPERATION_SPECS

PSI69_ID = "psi69-flex-v5"
PSI25_ID = "psi25-bass-ii-v4"
APPROVED_INVESTIGATIONS = frozenset({PSI69_ID, PSI25_ID})
CLAIM_LEDGER_SCHEMA = "sira.firelab.claim_ledger.v1"
MAX_PACKET_BYTES = 512 * 1024
MAX_PAPERS = 3
MAX_BULLETS = 20
MAX_TEXT = 4000
_ALLOWED_SEARCH_STATES = frozenset({
    "fresh", "cache_hit", "cache_stale", "cache_miss_offline",
    "no_results", "unavailable", "timeout", "busy",
})
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$", re.I)


class ResearchAdapterError(ValueError):
    """Raised when a FireLab context or scholarly result violates this contract."""


def _text(value: Any, label: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ResearchAdapterError(f"{label} is invalid")
    if not empty and not value.strip():
        raise ResearchAdapterError(f"{label} is empty")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise ResearchAdapterError(f"{label} contains control characters")
    return value


def _json_copy(value: Any, label: str) -> Any:
    try:
        rendered = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(rendered.encode("utf-8")) > MAX_PACKET_BYTES:
            raise ResearchAdapterError(f"{label} exceeds the packet size limit")
        return json.loads(rendered)
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError) as exc:
        if isinstance(exc, ResearchAdapterError):
            raise
        raise ResearchAdapterError(f"{label} is not bounded JSON data") from None


def _validate_answer_context(answer: Any) -> dict[str, Any]:
    if not isinstance(answer, Mapping):
        raise ResearchAdapterError("completed FireLab answer is required")
    if answer.get("status") != "completed":
        raise ResearchAdapterError("research retrieval requires a completed FireLab answer")

    investigation_id = answer.get("investigationId")
    if investigation_id not in APPROVED_INVESTIGATIONS:
        raise ResearchAdapterError("answer investigation is not registered")

    operation_id = answer.get("analysisId")
    data_scope = answer.get("dataScope")
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
        raise ResearchAdapterError("answer operation is invalid")
    if not isinstance(data_scope, str) or not data_scope or len(data_scope) > 80:
        raise ResearchAdapterError("answer data scope is invalid")

    plan = answer.get("scientificPlan")
    if not isinstance(plan, Mapping):
        raise ResearchAdapterError("validated Scientific Plan is required")
    if plan.get("operationId") != operation_id or plan.get("dataScope") != data_scope:
        raise ResearchAdapterError("answer does not match its serialized Scientific Plan")
    plan_investigation = plan.get("resolvedInvestigation")
    if plan_investigation is not None and plan_investigation != investigation_id:
        raise ResearchAdapterError("Scientific Plan investigation does not match the answer")
    plan_metric = plan.get("metric")
    metric = answer.get("metric", "")
    if plan_metric is not None and plan_metric != metric:
        raise ResearchAdapterError("Scientific Plan metric does not match the answer")
    if not isinstance(metric, str) or metric not in {"", "o2", "co2", "co"}:
        raise ResearchAdapterError("answer metric is invalid")
    operation_spec = OPERATION_SPECS.get(operation_id)
    if operation_spec is None:
        raise ResearchAdapterError("answer operation is not in the exact Claim Ledger operation registry")
    if (operation_spec.investigation_id != investigation_id
            or operation_spec.metric != metric
            or operation_spec.data_scope != data_scope):
        raise ResearchAdapterError("answer operation, investigation, metric, or scope conflicts with the registered contract")

    sample_size = answer.get("sampleSize", 0)
    if type(sample_size) is not int or sample_size < 0:
        raise ResearchAdapterError("answer sample size is invalid")

    copied_ledger = None
    ledger = answer.get("claimLedger")
    if ledger is not None:
        if not isinstance(ledger, Mapping):
            raise ResearchAdapterError("Claim Ledger must be an object")
        if ledger.get("schema") != CLAIM_LEDGER_SCHEMA or ledger.get("ledgerVersion") != 1:
            raise ResearchAdapterError("Claim Ledger schema/version is unsupported")
        if ledger.get("ledgerStatus") != "verified_provenance":
            raise ResearchAdapterError("Claim Ledger provenance status is not accepted")
        if (ledger.get("investigationId") != investigation_id
                or ledger.get("operationId") != operation_id
                or ledger.get("dataScope") != data_scope
                or ledger.get("metric") != metric):
            raise ResearchAdapterError("Claim Ledger context does not match the completed answer")
        claims = ledger.get("claims")
        if not isinstance(claims, list) or len(claims) > 30:
            raise ResearchAdapterError("Claim Ledger claims are malformed or exceed their limit")
        if not claims and not operation_id.endswith("research_questions"):
            raise ResearchAdapterError("completed scientific answer has an empty Claim Ledger")
        copied_ledger = _json_copy(dict(ledger), "Claim Ledger")

    title = _text(answer.get("title", "FireLab evidence result"), "answer title", 300)
    summary = _text(answer.get("text", ""), "answer summary", MAX_TEXT, empty=True)
    bullets_raw = answer.get("bullets", [])
    if not isinstance(bullets_raw, list) or len(bullets_raw) > MAX_BULLETS:
        raise ResearchAdapterError("answer bullets are malformed or exceed their limit")
    bullets = [_text(item, "answer bullet", 600) for item in bullets_raw]

    # Copy only the deterministic analysis context needed for downstream synthesis.
    dataset_context = {
        "investigation_id": investigation_id,
        "operation_id": operation_id,
        "metric": metric,
        "data_scope": data_scope,
        "sample_size": sample_size,
        "analysis_version": answer.get("analysisVersion", 1),
        "title": title,
        "summary": summary,
        "bullets": bullets,
        "claim_ledger": copied_ledger,
        "claim_ledger_status": "verified_provenance" if copied_ledger is not None else "not_present",
    }
    return _json_copy(dataset_context, "FireLab dataset context")


def _safe_https_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        return value
    except ValueError:
        return None


def _paper_source(row: Any) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ResearchAdapterError("scholarly result contains a malformed paper")
    title = _text(row.get("title"), "paper title", 500)
    paper_id = _text(row.get("paper_id", ""), "paper ID", 300, empty=True)
    provider = _text(row.get("provider", ""), "paper provider", 80, empty=True)
    doi = row.get("doi")
    if doi is not None:
        doi = _text(doi, "paper DOI", 300)
    year = row.get("year")
    if year is not None and (type(year) is not int or not 1800 <= year <= 2200):
        year = None
    abstract = row.get("abstract")
    abstract_truncated = False
    if abstract is not None:
        if not isinstance(abstract, str):
            raise ResearchAdapterError("paper abstract is invalid")
        abstract_truncated = len(abstract) > 4000
        abstract = _text(abstract[:4000], "paper abstract", 4000, empty=True)
    authors_raw = row.get("authors", [])
    if not isinstance(authors_raw, list) or len(authors_raw) > 40:
        raise ResearchAdapterError("paper authors are malformed")
    authors = [_text(item, "paper author", 200) for item in authors_raw]
    providers_raw = row.get("providers", [])
    if not isinstance(providers_raw, list) or len(providers_raw) > 4:
        raise ResearchAdapterError("paper provider attribution is malformed")
    providers = [_text(item, "paper provider attribution", 80) for item in providers_raw]
    retrieved_at = row.get("retrieved_at")
    if retrieved_at is not None:
        retrieved_at = _text(retrieved_at, "paper retrieval timestamp", 80)
    published_date = row.get("published_date")
    if published_date is not None:
        published_date = _text(published_date, "paper publication date", 80)
    matched_terms = row.get("matched_terms", [])
    if not isinstance(matched_terms, list) or len(matched_terms) > 40:
        matched_terms = []
    matched_terms = [_text(item, "matched query term", 100) for item in matched_terms]

    identity = "\0".join((paper_id, doi or "", provider, title)).encode("utf-8")
    source_id = "paper-" + hashlib.sha256(identity).hexdigest()[:24]
    return {
        "source_id": source_id,
        "source_type": "scholarly_record_metadata",
        "paper_id": paper_id,
        "title": title,
        "abstract": abstract,
        "abstract_truncated": abstract_truncated,
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": _safe_https_url(row.get("url")),
        "open_access_pdf_url": _safe_https_url(row.get("open_access_pdf_url")),
        "retrieved_at": retrieved_at,
        "published_date": published_date,
        "provider": provider,
        "providers": providers,
        "matched_terms": matched_terms,
        "interpretation_status": "metadata_only_not_independently_verified",
    }


class FireLabResearchAdapter:
    """Attach bounded scholarly retrieval to one completed, source-specific answer.

    `paper_search_service` is the existing FireLab PaperSearchService instance.
    Its configured runner uses the existing isolated SIRA Core worker and broker.
    """

    def __init__(self, paper_search_service: Any):
        if not callable(getattr(paper_search_service, "search", None)):
            raise TypeError("paper_search_service must expose search(query, refresh=False)")
        self._paper_search_service = paper_search_service

    def retrieve_supporting_literature(
        self,
        *,
        query: str,
        completed_answer: Mapping[str, Any],
        refresh: bool = False,
    ) -> dict[str, Any]:
        if type(refresh) is not bool:
            raise ResearchAdapterError("refresh must be boolean")
        query = _text(query, "research query", 200)
        if len(query.strip()) < 3:
            raise ResearchAdapterError("research query must contain at least 3 characters")

        # Validate the trusted FireLab execution context BEFORE any provider/cache call.
        dataset_context = _validate_answer_context(completed_answer)
        response = self._paper_search_service.search(query, refresh=refresh)
        if not isinstance(response, Mapping):
            raise ResearchAdapterError("PaperSearchService returned a non-object response")
        state = response.get("state")
        if state not in _ALLOWED_SEARCH_STATES:
            raise ResearchAdapterError("PaperSearchService returned an unknown search state")
        papers_raw = response.get("papers", [])
        if not isinstance(papers_raw, list) or len(papers_raw) > MAX_PAPERS:
            raise ResearchAdapterError("PaperSearchService returned an invalid paper collection")
        papers = [_paper_source(row) for row in papers_raw]
        retrieved_at = response.get("retrieved_at")
        if retrieved_at is not None:
            retrieved_at = _text(retrieved_at, "retrieval timestamp", 80)
        providers_raw = response.get("providers", [])
        if not isinstance(providers_raw, list) or len(providers_raw) > 4:
            raise ResearchAdapterError("search provider attribution is malformed")
        providers = [_text(item, "search provider", 80) for item in providers_raw]
        partial = response.get("partial", False)
        if not isinstance(partial, bool):
            raise ResearchAdapterError("search partial flag is malformed")
        message = response.get("message")
        if message is not None:
            message = _text(message, "search status message", 500)

        packet = {
            "schema": "sira.firelab.research_evidence_packet.v1",
            "dataset_context": dataset_context,
            "literature": {
                "query": query,
                "state": state,
                "retrieved_at": retrieved_at,
                "providers": providers,
                "partial": partial,
                "message": message,
                "source_count": len(papers),
                "sources": papers,
            },
            "verification_boundary": {
                "status": "not_performed",
                "dataset_claims_verified_by_literature": False,
                "literature_metadata_is_not_measurement_evidence": True,
                "cross_investigation_pooling_performed": False,
                "operational_safety_conclusion_performed": False,
            },
            "limitations": [
                "Scholarly records are discovery references; their metadata and abstracts have not been independently verified here.",
                "Retrieved papers do not verify or replace NASA PSI-69/PSI-25 source records or deterministic calculations.",
                "No cross-investigation pooling, causal inference, prediction, or operational safety recommendation was performed.",
            ],
        }
        return _json_copy(packet, "research evidence packet")
