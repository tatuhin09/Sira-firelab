import unittest

from firelab_service.paper_search.query import cache_key, matched_terms, normalize_query
from firelab_service.paper_search.records import validate_execution_result, validate_papers


def paper(provider="crossref", *, doi="10.1000/test", title="Microgravity flame extinction"):
    return {
        "paper_id": f"{provider}:123",
        "title": f"<jats:title>{title}</jats:title>",
        "abstract": "<jats:p>Flame response under microgravity conditions.</jats:p>",
        "authors": ["A. Researcher"],
        "year": 2021,
        "doi": doi,
        "url": "https://doi.org/10.1000/test",
        "open_access_pdf_url": None,
        "retrieved_at": "2026-10-31T00:00:00+00:00",
        "provider": provider,
        "published_date": "2021-02-03",
        "providers": [provider],
    }


def execution(records=None, *, status="completed", chain=None, attempted=None, attempts=None):
    return {
        "schema": "sira.research_execution.v1",
        "status": status,
        "records": records or [],
        "providers_attempted": attempted if attempted is not None else ["crossref"],
        "provider_chain": chain if chain is not None else ["crossref", "openalex", "semantic_scholar", "arxiv"],
        "attempts": attempts if attempts is not None else [{"provider_id": "crossref"}],
        "api_requests": 1,
        # This completed-result placeholder is intentionally ignored.
        "failure": {"code": "provider_unavailable"},
        "paid_spending": False,
    }


class QueryTests(unittest.TestCase):
    def test_nfkc_whitespace_and_casefold_cache_identity(self):
        self.assertEqual(normalize_query("  ＭICROgravity   Flame "), "MICROgravity Flame")
        self.assertEqual(cache_key("Microgravity flame"), cache_key(" microgravity   FLAME "))

    def test_query_bounds_and_controls(self):
        for value in (None, "", "ab", "x" * 201, "\x00fire", "\ufffdtest", "---"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_query(value)

    def test_matched_terms_does_not_require_long_abstract(self):
        self.assertEqual(matched_terms("microgravity flame oxygen", "Flame in microgravity", "O2"), ["microgravity", "flame"])


class RecordValidationTests(unittest.TestCase):
    def test_markup_removed_and_missing_abstract_accepted(self):
        row = paper()
        row["title"] = "<jats:italic>Flame</jats:italic> in microgravity"
        row["abstract"] = None
        result = validate_papers([row])[0]
        self.assertEqual(result["title"], "Flame in microgravity")
        self.assertIsNone(result["abstract"])

    def test_dedupe_prefers_casefolded_doi_and_preserves_provider_attribution(self):
        first = paper("crossref", doi="10.1000/ABC")
        second = paper("openalex", doi="10.1000/abc", title="Same paper from another provider")
        result = validate_papers([first, second])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["provider"], "crossref")
        self.assertEqual(result[0]["providers"], ["crossref", "openalex"])

    def test_invalid_provider_is_rejected(self):
        row = paper()
        row["provider"] = "tavily"
        with self.assertRaises(ValueError):
            validate_papers([row])

    def test_unsafe_urls_are_rejected(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "https://user:pass@example.org/x"):
            row = paper()
            row["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_papers([row])

    def test_html_script_content_is_removed(self):
        row = paper()
        row["abstract"] = "<p>Good evidence</p><script>alert('bad')</script> tail"
        result = validate_papers([row])[0]
        self.assertEqual(result["abstract"], "Good evidence tail")

    def test_execution_accepts_completed_placeholder_failure(self):
        result = validate_execution_result(execution([paper()]))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["records"][0]["provider"], "crossref")

    def test_partial_then_fallback_mixed_providers_are_validated(self):
        rows = [paper("crossref", doi="10.1000/one"), paper("openalex", doi="10.1000/two")]
        result = validate_execution_result(execution(
            rows, status="partial", attempted=["crossref", "openalex"],
            attempts=[{"provider_id": "crossref"}, {"provider_id": "openalex"}],
        ))
        self.assertEqual([row["provider"] for row in result["records"]], ["crossref", "openalex"])

    def test_unknown_provider_in_chain_attempt_or_record_rejects_whole_result(self):
        cases = [
            execution([paper()], chain=["crossref", "unexpected"]),
            execution([paper()], attempts=[{"provider_id": "unexpected"}]),
            execution([paper("unexpected")], attempted=["unexpected"]),
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_execution_result(value)

    def test_unknown_skipped_cooldown_provider_is_rejected(self):
        value = execution([paper()])
        value["providers_skipped_cooldown"] = [{"provider": "unexpected"}]
        with self.assertRaises(ValueError):
            validate_execution_result(value)

    def test_provider_record_must_be_attributed_to_chain_or_attempts(self):
        with self.assertRaises(ValueError):
            validate_execution_result(execution([paper("openalex")], chain=["crossref"], attempted=["crossref"]))

    def test_duplicate_or_conflicting_provider_execution_attribution_rejected(self):
        duplicate_chain = execution([paper()])
        duplicate_chain["provider_chain"] = ["crossref", "crossref"]
        duplicate_attempt = execution([paper()])
        duplicate_attempt["attempts"] = [{"provider_id": "crossref"}, {"provider_id": "crossref"}]
        attempted_and_skipped = execution([paper()])
        attempted_and_skipped["providers_skipped_cooldown"] = [{"provider": "crossref"}]
        for value in (duplicate_chain, duplicate_attempt, attempted_and_skipped):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_execution_result(value)

    def test_more_than_three_records_rejected(self):
        rows = [paper(doi=f"10.1000/{n}") for n in range(4)]
        with self.assertRaises(ValueError):
            validate_execution_result(execution(rows))


if __name__ == "__main__":
    unittest.main()
