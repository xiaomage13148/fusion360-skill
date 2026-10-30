import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("parameters", ROOT / "fusion360-mcp-cad/scripts/validate_part_params.py")
parameters = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parameters)


class ParameterTests(unittest.TestCase):
    def part(self, params=None, **updates):
        data = {"part_name": "plate", "units": "mm", "features": [
            {"step": 1, "type": "hole", "params": params or {"hole_dia_mm": 3.2}}]}
        data.update(updates)
        return data

    def test_invalid_diameter_types_and_range(self):
        for value in [-3, 0, "large", "3.2", True, None, float("inf"), float("nan"), 10**400]:
            with self.subTest(value=repr(value)):
                self.assertTrue(parameters.validate(self.part({"hole_dia_mm": value}))[0])

    def test_steps_must_be_ordered_integers(self):
        for steps in [[True], [1.0], [0], [2], [2, 1], [1, 1], [1, 3]]:
            data = self.part()
            data["features"] = [{"step": step, "type": "extrude", "params": {"depth_mm": 5}} for step in steps]
            with self.subTest(steps=steps):
                self.assertTrue(parameters.validate(data)[0])

    def test_no_default_manufacturing_process(self):
        errors, warnings, _, _, process = parameters.validate(self.part({"wall_mm": 0.3}))
        self.assertEqual((errors, warnings, process), ([], [], None))
        errors, warnings, _, _, process = parameters.validate(self.part({"wall_mm": 0.3}, process="CNC"))
        self.assertEqual((errors, process), ([], "CNC"))
        self.assertTrue(warnings)
        self.assertFalse(any("FDM" in warning for warning in warnings))

    def test_invalid_process_does_not_crash(self):
        for process in [123, [], {}, True, ""]:
            with self.subTest(process=process):
                self.assertTrue(parameters.validate(self.part(process=process))[0])

    def test_convert_print_thresholds_without_changing_input(self):
        data = self.part({"wall": {"kind": "wall", "value": 0.1, "unit": "in"}}, process="FDM")
        before = copy.deepcopy(data)
        errors, warnings, *_ = parameters.validate(data)
        self.assertEqual((errors, warnings), ([], []))
        self.assertEqual(data, before)
        data["features"][0]["params"]["wall"]["value"] = 0.01
        self.assertTrue(parameters.validate(data)[1])

    def test_signed_coordinates_and_angles_are_valid(self):
        errors, warnings, *_ = parameters.validate(self.part({
            "x_mm": -5, "y_mm": 0, "offset_mm": -2, "angle_deg": -90, "count": 2}))
        self.assertEqual((errors, warnings), ([], []))

    def test_count_and_unit_conflicts(self):
        for params in [{"count": 0}, {"count": 1.5}, {"count": True},
                       {"hole_dia_mm": {"kind": "scalar", "value": -3}},
                       {"width_mm": {"kind": "length", "value": 3, "unit": "in"}},
                       {"theta": {"kind": "angle", "value": 2}},
                       {"custom": {"kind": "length", "value": 2, "unit": ""}},
                       {"custom": {"kind": "length", "value": 2, "unit": "banana"}}]:
            with self.subTest(params=params):
                self.assertTrue(parameters.validate(self.part(params))[0])

    def test_dependency_must_reference_previous_step(self):
        data = self.part()
        data["features"].append({"step": 2, "type": "extrude", "depends_on": [1], "params": {"depth_mm": 5}})
        self.assertFalse(parameters.validate(data)[0])
        for dep in [True, 2, 3, "1"]:
            data["features"][1]["depends_on"] = [dep]
            self.assertTrue(parameters.validate(data)[0])

    def test_unknown_data_not_silently_certified(self):
        errors, warnings, *_ = parameters.validate(self.part({"material": "PLA", "custom": 3}))
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 2)

    def test_json_report_on_input_failure(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = parameters.main([str(ROOT / "missing-parameters.json"), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["verdict"], "FAIL")

    def test_malformed_top_levels_and_features(self):
        for data in [None, [], True, self.part(features=[None]), self.part(features=[]), self.part(units=None)]:
            with self.subTest(data=data):
                self.assertTrue(parameters.validate(data)[0])
