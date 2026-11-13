"""Tests for firelab_service.engine: known answers, strictness, stdlib-only, JS parity."""
import ast
import copy
import hashlib
import json
import math
import sys
import unittest
from pathlib import Path

from firelab_service import engine

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "firelab_site"
GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "firelab_golden.json"

BASELINE = {
    "pressureMin": 750,
    "pressureMax": 770,
    "oxygenMoleFraction": 0.21,
    "coSourceMoleFraction": 0,
    "heliumMoleFraction": 0,
}


class KnownAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = engine.load_bundle(SITE)
        cls.records = cls.bundle["records"]

    def test_bundle_matches_manifest(self):
        self.assertEqual(len(self.records), 274)
        self.assertEqual(len(self.bundle["sourceSha256"]), 64)
        self.assertEqual(self.bundle["sourceSha256"], self.bundle["manifest"]["sourceSha256"])

    def test_baseline_slice_sizes_and_outcomes(self):
        evidence = engine.condition_evidence(self.records, BASELINE)
        self.assertIsNone(evidence["error"])
        self.assertEqual(evidence["matchedCount"], 25)
        self.assertEqual([(g["fuel"], g["n"]) for g in evidence["groups"]], [("Heptane", 13), ("Methanol", 12)])
        by_fuel = {g["fuel"]: g for g in evidence["groups"]}
        self.assertEqual(by_fuel["Methanol"]["outcomes"], {"Extinction": 9, "Disruption": 3, "Completion": 0})
        self.assertEqual(by_fuel["Heptane"]["outcomes"], {"Extinction": 4, "Disruption": 7, "Completion": 2})
        methanol = by_fuel["Methanol"]["extinctionDiameter"]
        self.assertEqual((methanol["exact"], methanol["missing"]), (8, 1))
        self.assertAlmostEqual(methanol["median"], 1.18, places=12)
        self.assertEqual(by_fuel["Heptane"]["extinctionDiameter"]["exact"], 4)

    def test_broader_slice_when_oxygen_unrestricted(self):
        evidence = engine.condition_evidence(self.records, {**BASELINE, "oxygenMoleFraction": None})
        self.assertEqual(evidence["matchedCount"], 64)
        self.assertEqual([(g["fuel"], g["n"]) for g in evidence["groups"]], [("Methanol", 35), ("Heptane", 29)])

    def test_default_cohort_ranking(self):
        ranking = engine.condition_evidence(self.records, BASELINE)["ranking"]
        self.assertEqual([item["outcome"] for item in ranking], ["Extinction", "Disruption", "Completion"])
        self.assertAlmostEqual(ranking[0]["gapPercentagePoints"], 44.23076923076923, delta=1e-10)
        self.assertAlmostEqual(ranking[1]["gapPercentagePoints"], 28.846153846153843, delta=1e-10)
        self.assertAlmostEqual(ranking[2]["gapPercentagePoints"], 15.384615384615385, delta=1e-10)
        self.assertEqual(ranking[0]["higherShareFuel"], "Methanol")
        self.assertEqual((ranking[0]["left"]["count"], ranking[0]["left"]["n"]), (4, 13))
        self.assertEqual((ranking[0]["right"]["count"], ranking[0]["right"]["n"]), (9, 12))

    def test_oxygen_sensitivity_matches_documented_values(self):
        result = engine.oxygen_sensitivity(self.records, BASELINE)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([s["n"] for s in result["slices"]], [25, 64])
        self.assertEqual(result["fixedOrder"], ["Extinction", "Disruption", "Completion"])
        self.assertEqual(result["broadOrder"], ["Extinction", "Completion", "Disruption"])
        self.assertTrue(result["orderChanged"])
        for slice_, expected in zip(result["slices"], ([44.2, 28.8, 15.4], [30.5, 17.8, 12.7])):
            for item, value in zip(slice_["ranked"], expected):
                self.assertAlmostEqual(item["gapPercentagePoints"], value, delta=0.05)

    def test_inputs_are_not_mutated(self):
        before = copy.deepcopy(self.records)
        engine.condition_evidence(self.records, BASELINE)
        engine.oxygen_sensitivity(self.records, BASELINE)
        engine.exact_measurement_summary(self.records, "burningRateMm2PerSec")
        self.assertEqual(before, self.records)


class StrictnessTests(unittest.TestCase):
    def test_wilson_reference_values(self):
        interval = engine.wilson_interval(5, 10)
        self.assertAlmostEqual(interval["low"], 0.2366, delta=5e-4)
        self.assertAlmostEqual(interval["high"], 0.7634, delta=5e-4)
        self.assertEqual(engine.wilson_interval(0, 12)["low"], 0)
        self.assertEqual(engine.wilson_interval(12, 12)["high"], 1)
        for bad in ((-1, 5), (6, 5), (1.5, 5), (1, 0), (0, 0), (2, "x"), (True, 5)):
            self.assertEqual(engine.wilson_interval(*bad), {"low": None, "high": None}, bad)

    def test_number_normalisation(self):
        norm = engine.normalize_optional_number
        self.assertIsNone(norm(None))
        self.assertIsNone(norm(""))
        self.assertEqual(norm("0.21"), 0.21)
        self.assertEqual(norm(" 750 "), 750.0)
        self.assertEqual(norm(0), 0)
        for bad in ("abc", "1_0", "0x10", "  ", True, float("nan"), float("inf"), [1], {}):
            self.assertTrue(math.isnan(norm(bad)), repr(bad))

    def test_filter_errors_match_the_browser_messages(self):
        records = []
        self.assertEqual(engine.filter_records(records, {**BASELINE, "pressureMin": 800})["error"], engine.ERR_PRESSURE_ORDER)
        self.assertEqual(engine.filter_records(records, {**BASELINE, "pressureMin": None})["error"], engine.ERR_PRESSURE)
        self.assertEqual(engine.filter_records(records, {**BASELINE, "oxygenMoleFraction": "abc"})["error"], engine.ERR_GAS)
        self.assertEqual(engine.filter_records(records, None)["error"], engine.ERR_PRESSURE)

    def test_approximate_conditions_do_not_satisfy_exact_filters(self):
        record = {
            "ambientPressureMmHg": 760, "oxygenMoleFraction": 0.21,
            "coSourceMoleFraction": 0, "heliumMoleFraction": 0,
            "quality": {
                "ambientPressureMmHg": "exact", "oxygenMoleFraction": "exact",
                "coSourceMoleFraction": "approximate", "heliumMoleFraction": "exact",
            },
        }
        self.assertEqual(engine.filter_records([record], BASELINE)["rows"], [])

    def test_ranking_is_stable_when_groups_arrive_reversed(self):
        def group(fuel, n, counts):
            return {"fuel": fuel, "n": n, "outcomeSummaries": [
                {"outcome": o, "count": counts[o]} for o in engine.OUTCOME_ORDER]}
        first = group("Alpha", 4, {"Extinction": 3, "Disruption": 1, "Completion": 0})
        second = group("Beta", 4, {"Extinction": 1, "Disruption": 2, "Completion": 1})
        self.assertEqual(engine.rank_outcome_share_gaps([first, second]), engine.rank_outcome_share_gaps([second, first]))

    def test_single_fuel_has_no_ranking_and_zero_shares_are_kept(self):
        one = {"fuel": "A", "n": 4, "outcomeSummaries": [{"outcome": o, "count": 0} for o in engine.OUTCOME_ORDER]}
        self.assertEqual(engine.rank_outcome_share_gaps([one]), [])
        a = {"fuel": "A", "n": 4, "outcomeSummaries": [
            {"outcome": "Extinction", "count": 0}, {"outcome": "Disruption", "count": 2}, {"outcome": "Completion", "count": 2}]}
        b = {"fuel": "B", "n": 4, "outcomeSummaries": [
            {"outcome": "Extinction", "count": 4}, {"outcome": "Disruption", "count": 0}, {"outcome": "Completion", "count": 0}]}
        top = engine.rank_outcome_share_gaps([a, b])[0]
        self.assertEqual((top["outcome"], top["gapPercentagePoints"]), ("Extinction", 100))

    def test_engine_imports_only_the_standard_library(self):
        tree = ast.parse((ROOT / "firelab_service" / "engine.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        self.assertTrue(names)
        self.assertEqual(sorted(n for n in names if n not in sys.stdlib_module_names), [])


_DIFFS = []


def assert_same(case, expected, actual, path="$"):
    """Recursive comparison: exact for everything except floats (1e-12 tolerance)."""
    if isinstance(expected, dict):
        case.assertIsInstance(actual, dict, path)
        case.assertEqual(sorted(expected), sorted(actual), f"{path}: keys differ")
        for key in expected:
            assert_same(case, expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        case.assertIsInstance(actual, (list, tuple), path)
        case.assertEqual(len(expected), len(actual), f"{path}: length differs")
        for index, (e, a) in enumerate(zip(expected, actual)):
            assert_same(case, e, a, f"{path}[{index}]")
    elif expected is None or isinstance(expected, (bool, str)):
        case.assertEqual(expected, actual, path)
    else:
        case.assertTrue(isinstance(actual, (int, float)) and not isinstance(actual, bool), f"{path}: not a number: {actual!r}")
        case.assertTrue(math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-12), f"{path}: JS={expected!r} Python={actual!r}")
        if float(expected) != float(actual):
            denominator = max(abs(float(expected)), 1e-300)
            _DIFFS.append(abs(float(expected) - float(actual)) / denominator)
        else:
            _DIFFS.append(0.0)


class ParityWithJavaScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GOLDEN_PATH.is_file():
            raise FileNotFoundError("Run `node tools/firelab_make_golden.js` first.")
        cls.golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        cls.records = engine.load_bundle(SITE)["records"]

    @classmethod
    def tearDownClass(cls):
        worst = max(_DIFFS) if _DIFFS else 0.0
        exact = sum(1 for d in _DIFFS if d == 0.0)
        print(f"\nJS parity: {len(_DIFFS)} numbers compared, {exact} bit-identical, max relative difference {worst:.3e}")

    def test_golden_file_is_current(self):
        digest = hashlib.sha256((SITE / "data" / "records.json").read_bytes()).hexdigest()
        self.assertEqual(self.golden["meta"]["recordsSha256"], digest, "records.json changed: regenerate the golden file")
        self.assertEqual(self.golden["meta"]["recordCount"], len(self.records))

    def test_filter_summary_and_ranking_cases(self):
        self.assertGreater(len(self.golden["filterCases"]), 20)
        for case in self.golden["filterCases"]:
            with self.subTest(case=case["name"]):
                actual = engine.condition_evidence(self.records, case["filters"])
                expected = {k: case[k] for k in ("error", "testNumbers", "groups", "ranking")}
                assert_same(self, expected, {k: actual[k] for k in expected}, case["name"])
                self.assertEqual(actual["matchedCount"], len(case["testNumbers"]))

    def test_oxygen_sensitivity_cases(self):
        for case in self.golden["sensitivityCases"]:
            with self.subTest(case=case["name"]):
                actual = engine.oxygen_sensitivity(self.records, case["filters"])
                expected = {k: v for k, v in case.items() if k not in ("name", "filters")}
                assert_same(self, expected, actual, case["name"])

    def test_wilson_grid(self):
        self.assertGreater(len(self.golden["wilson"]), 800)
        for item in self.golden["wilson"]:
            with self.subTest(successes=item["successes"], total=item["total"]):
                actual = engine.wilson_interval(item["successes"], item["total"])
                assert_same(self, item["result"], actual, "wilson")

    def test_exact_measurement_summaries(self):
        for item in self.golden["measurements"]:
            with self.subTest(key=item["key"], scope=item["scope"]):
                rows = self.records if item["scope"] == "all" else [r for r in self.records if r.get("fuel") == item["scope"]]
                assert_same(self, item["result"], engine.exact_measurement_summary(rows, item["key"]), item["key"])

    def test_counts_by(self):
        for field, expected in self.golden["countsBy"].items():
            with self.subTest(field=field):
                self.assertEqual(expected, engine.counts_by(self.records, field))


if __name__ == "__main__":
    unittest.main()
