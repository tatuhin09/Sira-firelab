"""Bounded query normalization and deterministic relevance matching."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

CACHE_SCHEMA_VERSION = 1
CAPABILITY = "paper_search"
MAX_RESULTS = 3
MIN_QUERY_LENGTH = 3
MAX_QUERY_LENGTH = 200
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "by", "for", "from", "how",
    "in", "into", "is", "of", "on", "or", "the", "to", "with", "what",
})


def normalize_query(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("query must be text")
    normalized = unicodedata.normalize("NFKC", value)
    if "\ufffd" in normalized or _CONTROL_RE.search(normalized) or any(
        unicodedata.category(ch) in {"Cc", "Cf", "Cs"} for ch in normalized
    ):
        raise ValueError("query contains unsupported characters")
    normalized = " ".join(normalized.split())
    if not MIN_QUERY_LENGTH <= len(normalized) <= MAX_QUERY_LENGTH:
        raise ValueError(f"query must contain {MIN_QUERY_LENGTH}..{MAX_QUERY_LENGTH} characters")
    if not any(ch.isalnum() for ch in normalized):
        raise ValueError("query must contain at least one letter or digit")
    return normalized


def canonical_query(value: object) -> str:
    return normalize_query(value).casefold()


def cache_key(query: str) -> str:
    canonical = canonical_query(query)
    payload = {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "capability": CAPABILITY,
        "max_results": MAX_RESULTS,
        "query": canonical,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def query_terms(query: str) -> tuple[str, ...]:
    return tuple(
        token for token in dict.fromkeys(_TOKEN_RE.findall(canonical_query(query)))
        if len(token) > 1 and token not in _STOPWORDS
    )


def matched_terms(query: str, title: str, abstract: str | None) -> list[str]:
    title_text = unicodedata.normalize("NFKC", title).casefold()
    abstract_text = unicodedata.normalize("NFKC", abstract or "").casefold()
    searchable = f" {title_text} {abstract_text} "
    matches: list[str] = []
    for term in query_terms(query):
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", searchable, flags=re.UNICODE):
            matches.append(term)
    return matches
