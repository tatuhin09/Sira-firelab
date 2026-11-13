import unittest
from pathlib import Path
from tools.firelab.analysis import grouped_summary
from tools.firelab.parser import parse_csv
from tools.ingest_firelab_flex import build_bundle


class FireLabParserTests(unittest.TestCase):
    def test_parser_keeps_valid_rows_and_reports_rejections(self):
        source = "id,fuel,value\na,heptane,1.5\na,heptane,2\n,heptane,3\nb,heptane,nope\nc,heptane,\n"
        parsed = parse_csv(source, id_column="id", numeric_columns=("value",), required_columns=("fuel",))
        self.assertEqual([row["id"] for row in parsed["rows"]], ["a", "b", "c"])
        self.assertEqual([row["value"] for row in parsed["rows"]], [1.5, None, None])
        self.assertEqual([row["_source_row"] for row in parsed["rows"]], [2, 5, 6])
        self.assertEqual(parsed["report"]["duplicate_id_rows"], 1)
        self.assertEqual(parsed["report"]["missing_id_rows"], 1)
        self.assertEqual(parsed["report"]["invalid_numeric_rows"], 1)
        self.assertEqual(parsed["report"]["missing_measurement_rows"], 1)
        self.assertEqual(parsed["report"]["field_quality"]["value"], {
            "exact": 1, "approximate": 0, "missing": 1, "invalid": 1
        })
        self.assertEqual(len(parsed["report"]["source_sha256"]), 64)

    def test_parser_handles_cp1252_missing_and_approximate_values(self):
        source = (
            "FLEX Test #,FLEX Identifier,Fuel,Value; mm\n"
            "1,same,Methanol,2.0\n"
            "2,same,Heptane,–\n"
            "3,other,Methanol,~4\n"
        ).encode("cp1252")
        parsed = parse_csv(source, id_column="FLEX Test #", numeric_columns=("Value; mm",))
        self.assertEqual([row["FLEX Test #"] for row in parsed["rows"]], ["1", "2", "3"])
        self.assertEqual([row["Value; mm"] for row in parsed["rows"]], [2.0, None, 4.0])
        self.assertEqual(parsed["rows"][2]["_quality"]["Value; mm"], "approximate")
        self.assertEqual(parsed["rows"][1]["_raw"]["Value; mm"], "–")
        self.assertEqual(parsed["rows"][2]["_raw"]["Value; mm"], "~4")
        self.assertEqual(parsed["report"]["field_quality"]["Value; mm"], {
            "exact": 1, "approximate": 1, "missing": 1, "invalid": 0
        })
        self.assertEqual(parsed["report"]["duplicate_id_rows"], 0)

    def test_parser_marks_non_finite_numbers_invalid_without_dropping_rows(self):
        parsed = parse_csv("id,value\nok,1\nnan,NaN\ninf,Infinity\n", id_column="id", numeric_columns=("value",))
        self.assertEqual([row["id"] for row in parsed["rows"]], ["ok", "nan", "inf"])
        self.assertEqual([row["value"] for row in parsed["rows"]], [1.0, None, None])
        self.assertEqual(parsed["report"]["invalid_numeric_rows"], 2)

    def test_parser_rejects_missing_columns(self):
        with self.assertRaisesRegex(ValueError, "Missing required CSV columns"):
            parse_csv("id\na\n", id_column="id", numeric_columns=("burn_rate",))


class FireLabAnalysisTests(unittest.TestCase):
    def test_bundle_quality_metadata_is_used_in_exact_summaries(self):
        source_path = (
            Path(__file__).resolve().parents[1]
            / "firelab_site" / "data" / "source"
            / "PSI-69_Experimental table_FLEX.csv"
        )
        bundle = build_bundle(
            source_path.read_bytes(),
            source_name=source_path.name,
            retrieved_at="2026-10-30",
        )

        summary = grouped_summary(
            bundle["records"],
            value_column="burnTimeSeconds",
        )[0]

        self.assertEqual(summary["n"], 266)
        self.assertEqual(summary["approximate_n"], 2)
        self.assertEqual(summary["missing_n"], 6)
        self.assertEqual(summary["invalid_n"], 0)

    def test_non_finite_values_are_never_counted_as_exact(self):
        rows = [
            {"v": float("nan"), "quality": {"v": "exact"}},
            {"v": float("inf"), "quality": {"v": "approximate"}},
            {"v": None, "quality": {"v": "missing"}},
        ]

        summary = grouped_summary(rows, value_column="v")[0]

        self.assertEqual(summary["n"], 0)
        self.assertEqual(summary["approximate_n"], 0)
        self.assertEqual(summary["missing_n"], 1)
        self.assertEqual(summary["invalid_n"], 2)

    def test_group_summary_reports_group_sample_sizes(self):
        rows = [{"fuel":"A","v":1.0},{"fuel":"A","v":3.0},{"fuel":"B","v":4.0}]
        summary = grouped_summary(rows, value_column="v", group_column="fuel")
        self.assertEqual([(x["group"], x["n"]) for x in summary], [("A",2),("B",1)])
        self.assertEqual(summary[0]["mean"], 2.0)
        self.assertIsNone(summary[1]["sample_sd"])

    def test_empty_summary_does_not_invent_values(self):
        summary = grouped_summary([], value_column="value")
        self.assertEqual(summary[0]["n"], 0)
        self.assertIsNone(summary[0]["mean"])

    def test_group_summary_excludes_approximate_values_from_exact_statistics(self):
        rows = [
            {"fuel": "A", "v": 2.0, "_quality": {"v": "exact"}},
            {"fuel": "A", "v": 4.0, "_quality": {"v": "approximate"}},
            {"fuel": "A", "v": None, "_quality": {"v": "missing"}},
        ]
        summary = grouped_summary(rows, value_column="v", group_column="fuel")
        self.assertEqual(summary[0]["n"], 1)
        self.assertEqual(summary[0]["approximate_n"], 1)
        self.assertEqual(summary[0]["missing_n"], 1)
        self.assertEqual(summary[0]["mean"], 2.0)

    def test_real_psi69_file_retains_all_test_numbers_and_reports_quality(self):
        source_path = Path(__file__).resolve().parents[1] / "firelab_site" / "data" / "source" / "PSI-69_Experimental table_FLEX.csv"
        parsed = parse_csv(source_path.read_bytes(), id_column="FLEX Test #", numeric_columns=(
            "Ambient pressure; mmHg",
            "Droplet initial diameter; mm",
            "Visible flame extinction diameter; mm",
            "Burning rate; mm",
            "Burn time; s",
        ), required_columns=("Fuel", "Test end"))
        self.assertEqual(parsed["report"]["input_rows"], 274)
        self.assertEqual(parsed["report"]["accepted_rows"], 274)
        self.assertEqual(parsed["rows"][113]["FLEX Test #"], "114")
        self.assertEqual(parsed["report"]["field_quality"]["Visible flame extinction diameter; mm"]["exact"], 197)
        self.assertEqual(parsed["report"]["field_quality"]["Visible flame extinction diameter; mm"]["missing"], 77)
        self.assertEqual(parsed["report"]["field_quality"]["Burn time; s"]["approximate"], 2)
        self.assertEqual(parsed["report"]["source_sha256"], "37c88ce8ae9391b7544ff630a45ce87543d04d317cdbfbed104fe7d5c27e1b96")

    def test_bundle_preserves_source_lineage_units_and_quality_flags(self):
        source_path = Path(__file__).resolve().parents[1] / "firelab_site" / "data" / "source" / "PSI-69_Experimental table_FLEX.csv"
        bundle = build_bundle(source_path.read_bytes(), source_name=source_path.name, retrieved_at="2026-10-29")
        self.assertEqual(bundle["manifest"]["recordCount"], 274)
        self.assertEqual(bundle["manifest"]["sourceSha256"], "37c88ce8ae9391b7544ff630a45ce87543d04d317cdbfbed104fe7d5c27e1b96")
        self.assertEqual(bundle["quality"]["identifierChecks"]["FLEX Identifier"]["duplicateRows"], 1)
        self.assertEqual(bundle["quality"]["measurementQuality"]["visibleFlameExtinctionDiameterMm"]["exact"], 197)
        self.assertEqual(bundle["quality"]["measurementQuality"]["visibleFlameExtinctionDiameterMm"]["missing"], 77)
        self.assertEqual(bundle["quality"]["measurementQuality"]["burnTimeSeconds"]["approximate"], 2)
        self.assertEqual(bundle["quality"]["compositionCheck"]["outsideOnePercent"], 25)
        test_114 = next(row for row in bundle["records"] if row["testNumber"] == 114)
        self.assertEqual(test_114["ambientPressureMmHg"], 0.0)
        self.assertIn("zero_pressure_source_value", test_114["flags"])
        test_223 = next(row for row in bundle["records"] if row["testNumber"] == 223)
        self.assertEqual(test_223["burnTimeSeconds"], 6.0)
        self.assertEqual(test_223["quality"]["burnTimeSeconds"], "approximate")


if __name__ == "__main__":
    unittest.main()
