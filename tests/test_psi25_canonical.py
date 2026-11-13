import json
import tempfile
import unittest
from pathlib import Path

from tools.firelab.psi25_canonical import (
    ROOT,
    _parse_flow_restrictor,
    _parse_freeform_numeric,
    _parse_material,
    _parse_quantity,
    _read_readme,
    build_canonical_dataset,
)


class PSI25MeasurementTests(unittest.TestCase):
    def test_blank_and_none_remain_distinct(self):
        blank = _parse_quantity("", "ppm", is_co=True)
        none = _parse_quantity("none", "ppm", is_co=True)

        self.assertEqual(blank["status"], "blank")
        self.assertEqual(none["status"], "source_none")
        self.assertNotEqual(blank["status"], none["status"])

    def test_or_is_right_censored_only_with_verified_readme(self):
        verified = _parse_quantity(
            "OR", "ppm", is_co=True, or_threshold_verified=True
        )
        unverified = _parse_quantity(
            "OR", "ppm", is_co=True, or_threshold_verified=False
        )

        self.assertEqual(verified["status"], "right_censored")
        self.assertEqual(verified["censoring"]["lower_bound"], "1000")
        self.assertEqual(
            unverified["status"],
            "right_censored_threshold_unverified",
        )
        self.assertIsNone(unverified["parsed_decimal"])

    def test_explicit_bound_is_not_converted_to_a_number(self):
        result = _parse_quantity(">500", "ppm", is_co=True)

        self.assertEqual(result["status"], "right_censored")
        self.assertEqual(result["censoring"]["lower_bound"], "500")
        self.assertIsNone(result["parsed_decimal"])

    def test_actual_readme_verifies_co_or_threshold(self):
        readme = _read_readme(
            ROOT
            / "firelab_site/data/source/PSI-25_BASS-II_v4_selected"
            / "PSI-25_Science Documents_BASS-II_ReadMe.docx"
        )
        self.assertTrue(readme["co_or_threshold_verified"])
        result = _parse_quantity(
            "OR", "ppm", is_co=True,
            or_threshold_verified=readme["co_or_threshold_verified"],
        )
        self.assertEqual(result["status"], "right_censored")
        self.assertEqual(result["censoring"]["lower_bound"], "1000")

    def test_over_has_no_invented_threshold(self):
        result = _parse_quantity("over", "ppm", is_co=True)

        self.assertEqual(
            result["status"],
            "over_range_threshold_unspecified",
        )
        self.assertIsNone(result["censoring"])

    def test_negative_co_is_retained_and_flagged(self):
        result = _parse_quantity("-1", "ppm", is_co=True)

        self.assertEqual(result["parsed_decimal"], "-1")
        self.assertEqual(
            result["status"],
            "negative_numeric_requires_review",
        )
        self.assertFalse(result["aggregation_eligible"])

    def test_fan_numeric_token_is_not_assumed_to_be_voltage(self):
        result = _parse_freeform_numeric(
            "0.9", None, "fan_display"
        )

        self.assertEqual(
            result["status"],
            "single_numeric_token_uninterpreted",
        )
        self.assertIsNone(result["parsed_decimal"])
        self.assertEqual(result["candidate_decimal"], "0.9")

    def test_air_scalar_is_retained_but_not_aggregation_eligible(self):
        result = _parse_freeform_numeric(
            "5", "cm/s", "air_display"
        )

        self.assertEqual(
            result["status"],
            "numeric_scalar_steady_state_unverified",
        )
        self.assertEqual(result["parsed_decimal"], "5")
        self.assertEqual(result["unit"], "cm/s")
        self.assertFalse(result["aggregation_eligible"])
        self.assertEqual(
            result["steady_state_evidence"],
            "not_present_in_exported_record",
        )

    def test_air_sequence_is_not_split(self):
        result = _parse_freeform_numeric(
            "5 down to ext", "cm/s", "air_display"
        )

        self.assertEqual(result["status"], "sequence_or_note")
        self.assertIsNone(result["parsed_decimal"])

    def test_flow_restrictor_semantics(self):
        self.assertEqual(
            _parse_flow_restrictor("0")["documented_interpretation"],
            "highest_flow_lowest_restriction",
        )
        self.assertEqual(
            _parse_flow_restrictor("2")["documented_interpretation"],
            "lowest_flow_highest_restriction",
        )

    def test_sibal_composition_is_source_backed(self):
        readme = _read_readme(
            ROOT
            / "firelab_site/data/source/PSI-25_BASS-II_v4_selected"
            / "PSI-25_Science Documents_BASS-II_ReadMe.docx"
        )

        self.assertTrue(readme["sibal_composition_verified"])

        result = _parse_material("2 cm SIBAL", "T'ien", readme)

        self.assertEqual(result["mapping_status"], "source_verified")
        self.assertEqual(result["canonical_class"], "SIBAL fabric")
        self.assertEqual(
            result["attributes"]["composition"]["cotton_percent"],
            75,
        )
        self.assertEqual(
            result["attributes"]["composition"]["fiberglass_percent"],
            25,
        )
        self.assertEqual(result["attributes"]["width_cm"], "2")

    def test_unverified_material_remains_raw_only(self):
        result = _parse_material(
            "unknown material description",
            "Unknown PI",
            {
                "sibal_composition_verified": False,
                "sibal_paragraphs": [],
                "sphere_mapping_verified": False,
                "sphere_paragraphs": [],
            },
        )

        self.assertEqual(result["mapping_status"], "raw_description_only")
        self.assertIsNone(result["canonical_class"])


class PSI25FullDatasetTests(unittest.TestCase):
    def test_full_source_build_is_reproducible_and_preserves_sources(self):
        source_dir = (
            ROOT
            / "firelab_site/data/source/PSI-25_BASS-II_v4_selected"
        )
        source_hashes_before = {
            path.name: path.read_bytes()
            for path in source_dir.iterdir()
            if path.is_file()
        }

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "psi25_derived"

            result = build_canonical_dataset(
                root=ROOT,
                output_dir=output,
            )

            records = json.loads(
                (result / "canonical_records.json").read_text(encoding="utf-8")
            )
            report = json.loads(
                (result / "quality_report.json").read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (result / "canonical_manifest.json").read_text(encoding="utf-8")
            )

            self.assertEqual(records["record_count"], 129)
            self.assertEqual(len(records["records"]), 129)
            self.assertEqual(
                report["identity_reconciliation"]["matched_composite_identities"],
                129,
            )
            self.assertEqual(
                report["sample_reuse"]["distinct_exact_raw_ids"],
                107,
            )
            self.assertEqual(
                report["sample_reuse"]["reused_exact_raw_id_groups"],
                20,
            )
            self.assertEqual(len(manifest["source_files"]), 4)

            self.assertEqual(
                manifest["derived_files"]["canonical_records.json"]["sha256"],
                __import__("hashlib").sha256(
                    (result / "canonical_records.json").read_bytes()
                ).hexdigest(),
            )

        source_hashes_after = {
            path.name: path.read_bytes()
            for path in source_dir.iterdir()
            if path.is_file()
        }
        self.assertEqual(source_hashes_before, source_hashes_after)
        # Verify deterministic output from a second independent build.
        with tempfile.TemporaryDirectory() as temp:
            first = build_canonical_dataset(
                root=ROOT, output_dir=Path(temp) / "first"
            )
            second = build_canonical_dataset(
                root=ROOT, output_dir=Path(temp) / "second"
            )
            for filename in (
                "canonical_records.json",
                "quality_report.json",
                "canonical_manifest.json",
            ):
                self.assertEqual(
                    (first / filename).read_bytes(),
                    (second / filename).read_bytes(),
                )

            with self.assertRaises(ValueError):
                build_canonical_dataset(root=ROOT, output_dir=first)



if __name__ == "__main__":
    unittest.main()
