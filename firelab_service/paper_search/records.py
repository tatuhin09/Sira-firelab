"""Strict validation and safe normalization of untrusted scholarly metadata."""
from __future__ import annotations

from datetime import date, datetime
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Mapping

from .query import matched_terms

ALLOWED_PROVIDERS = frozenset({"crossref", "openalex", "semantic_scholar", "arxiv"})
MAX_PAPERS = 3
MAX_TITLE = 4000
MAX_ABSTRACT = 5000
MAX_AUTHORS = 20
MAX_AUTHOR_LENGTH = 200
MAX_URL = 2048
MAX_PAPER_ID = 256


class _MarkupText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self.suppressed and data:
            self.parts.append(data)


def clean_text(value: object, *, maximum: int, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError("text field has an invalid type")
    parser = _MarkupText()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, UnicodeError):
        raise ValueError("text field contains malformed markup") from None
    text = unicodedata.normalize("NFKC", " ".join("".join(parser.parts).split()))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in {"Cc", "Cf", "Cs"})
    text = " ".join(text.split()).strip()
    if not text and required:
        raise ValueError("required text field is empty")
    if len(text) > maximum:
        if required:
            raise ValueError("required text field is too long")
        text = text[:maximum].rstrip()
    return text or None


def safe_http_url(value: object, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_URL:
        raise ValueError("URL has an invalid type or length")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise ValueError("URL contains whitespace or control characters")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in {"http", "https"}:
            raise ValueError("URL scheme is not allowed")
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("URL host or credentials are invalid")
        _ = parsed.port
    except ValueError:
        raise ValueError("URL is invalid") from None
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def _safe_provider(value: object) -> str:
    if not isinstance(value, str) or value not in ALLOWED_PROVIDERS:
        raise ValueError("paper provider is not approved")
    return value


def validate_paper(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("paper record must be an object")
    paper_id = clean_text(raw.get("paper_id"), maximum=MAX_PAPER_ID, required=True)
    title = clean_text(raw.get("title"), maximum=MAX_TITLE, required=True)
    abstract = clean_text(raw.get("abstract"), maximum=MAX_ABSTRACT)
    provider = _safe_provider(raw.get("provider"))

    authors_raw = raw.get("authors", [])
    if isinstance(authors_raw, tuple):
        authors_raw = list(authors_raw)
    if not isinstance(authors_raw, list) or len(authors_raw) > 500:
        raise ValueError("paper authors are invalid")
    authors: list[str] = []
    for author in authors_raw[:MAX_AUTHORS]:
        cleaned = clean_text(author, maximum=MAX_AUTHOR_LENGTH, required=True)
        if cleaned:
            authors.append(cleaned)

    year = raw.get("year")
    if year is not None and (type(year) is not int or not 1 <= year <= 9999):
        raise ValueError("paper year is invalid")

    doi = raw.get("doi")
    if doi is not None:
        doi = clean_text(doi, maximum=300, required=True)
        if doi is None or any(ord(ch) < 32 for ch in doi):
            raise ValueError("paper DOI is invalid")

    retrieved_at = raw.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not retrieved_at.strip() or len(retrieved_at) > 64:
        raise ValueError("paper retrieval timestamp is invalid")
    try:
        parsed_retrieval = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        if parsed_retrieval.tzinfo is None:
            raise ValueError("timestamp has no timezone")
    except ValueError:
        raise ValueError("paper retrieval timestamp is invalid") from None

    published_date = raw.get("published_date")
    if published_date is not None:
        if not isinstance(published_date, str) or len(published_date) != 10:
            raise ValueError("paper published date is invalid")
        try:
            date.fromisoformat(published_date)
        except ValueError:
            raise ValueError("paper published date is invalid") from None

    providers_raw = raw.get("providers", [provider])
    if isinstance(providers_raw, tuple):
        providers_raw = list(providers_raw)
    if not isinstance(providers_raw, list) or not 1 <= len(providers_raw) <= 4:
        raise ValueError("paper provider attribution is invalid")
    providers = list(dict.fromkeys(_safe_provider(item) for item in providers_raw))
    if provider not in providers:
        providers.insert(0, provider)

    return {
        "paper_id": paper_id,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "year": year,
        "doi": doi,
        "url": safe_http_url(raw.get("url"), required=True),
        "open_access_pdf_url": safe_http_url(raw.get("open_access_pdf_url")),
        "retrieved_at": retrieved_at,
        "provider": provider,
        "published_date": published_date,
        "providers": providers,
    }


def dedupe_key(paper: Mapping[str, Any]) -> str:
    doi = paper.get("doi")
    if isinstance(doi, str) and doi.strip():
        return "doi:" + doi.casefold().strip()
    url = paper.get("url")
    if isinstance(url, str) and url.strip():
        return "url:" + url.casefold().strip()
    return "id:" + str(paper.get("paper_id", "")).casefold()


def validate_papers(raw_records: object) -> list[dict[str, Any]]:
    if not isinstance(raw_records, list) or len(raw_records) > MAX_PAPERS:
        raise ValueError("research result must contain at most three paper records")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_records:
        paper = validate_paper(raw)
        key = dedupe_key(paper)
        if key in seen:
            existing = next(item for item in validated if dedupe_key(item) == key)
            existing["providers"] = list(dict.fromkeys(existing["providers"] + paper["providers"] + [paper["provider"]]))
            continue
        seen.add(key)
        validated.append(paper)
    return validated[:MAX_PAPERS]


def _validate_provider_ids(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError(f"{field} is invalid")
    result: list[str] = []
    for provider in value:
        result.append(_safe_provider(provider))
    return result


def validate_execution_result(raw: object) -> dict[str, Any]:
    """Validate the worker envelope and every provider attribution boundary."""
    if not isinstance(raw, Mapping) or raw.get("schema") != "sira.research_execution.v1":
        raise ValueError("worker result schema is invalid")
    status = raw.get("status")
    if status not in {"completed", "partial", "no_results", "unavailable", "failed", "cancelled"}:
        raise ValueError("worker result status is invalid")

    attempted = _validate_provider_ids(raw.get("providers_attempted", []), field="providers_attempted")
    chain = _validate_provider_ids(raw.get("provider_chain", []), field="provider_chain")
    if len(set(attempted)) != len(attempted) or len(set(chain)) != len(chain):
        raise ValueError("provider execution chain contains duplicate IDs")
    if any(provider not in chain for provider in attempted):
        raise ValueError("attempted provider was not present in the broker chain")

    attempts_raw = raw.get("attempts", [])
    if not isinstance(attempts_raw, list) or len(attempts_raw) > 8:
        raise ValueError("worker attempts are invalid")
    attempts: list[dict[str, Any]] = []
    for item in attempts_raw:
        if not isinstance(item, Mapping):
            raise ValueError("worker attempt is invalid")
        provider_id = _safe_provider(item.get("provider_id"))
        attempts.append({"provider_id": provider_id})

    skipped_raw = raw.get("providers_skipped_cooldown", [])
    if not isinstance(skipped_raw, list) or len(skipped_raw) > 8:
        raise ValueError("skipped provider list is invalid")
    skipped: list[str] = []
    for item in skipped_raw:
        if not isinstance(item, Mapping):
            raise ValueError("skipped provider record is invalid")
        skipped.append(_safe_provider(item.get("provider")))
    attempt_ids = [item["provider_id"] for item in attempts]
    if len(set(attempt_ids)) != len(attempt_ids):
        raise ValueError("provider attempts contain duplicate IDs")
    if any(provider not in chain for provider in attempt_ids):
        raise ValueError("provider attempt was not present in the broker chain")
    if len(set(skipped)) != len(skipped) or any(provider not in chain for provider in skipped):
        raise ValueError("skipped provider was not uniquely present in the broker chain")
    if set(skipped) & set(attempted):
        raise ValueError("a provider cannot be both attempted and skipped")

    records = raw.get("records", [])
    papers = validate_papers(records)
    if status in {"completed", "partial"} and not papers:
        raise ValueError("successful research status has no paper records")
    if status in {"no_results", "unavailable", "failed", "cancelled"} and papers:
        raise ValueError("unsuccessful research status contains paper records")

    for paper in papers:
        if paper["provider"] not in attempted:
            raise ValueError("paper provider was not actually attempted")
        for provider in paper["providers"]:
            if provider not in attempted:
                raise ValueError("paper provider attribution was not actually attempted")

    api_requests = raw.get("api_requests", 0)
    if type(api_requests) is not int or not 0 <= api_requests <= 100:
        raise ValueError("worker request count is invalid")

    # The orchestrator emits a placeholder failure on completed outcomes; never
    # interpret or forward it. Failure details are intentionally discarded.
    return {
        "schema": "sira.research_execution.v1",
        "status": status,
        "records": papers,
        "providers_attempted": attempted,
        "provider_chain": chain,
        "attempts": attempts,
        "providers_skipped_cooldown": skipped,
        "api_requests": api_requests,
        "providers": list(dict.fromkeys(
            provider for paper in papers for provider in paper["providers"]
        )),
    }


def with_relevance(query: str, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for paper in papers:
        item = dict(paper)
        item["matched_terms"] = matched_terms(query, item["title"], item.get("abstract"))
        result.append(item)
    return result
