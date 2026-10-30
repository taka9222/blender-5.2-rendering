import tempfile
import unittest
from pathlib import Path

import numpy as np

from render_object import _build_geometry_data
from render_config import (
    ConfigError,
    create_light_directions,
    create_object_directions,
    load_job,
    parse_vector,
    str2bool,
)


ROOT = Path(__file__).resolve().parents[1]


class ConfigHelpersTests(unittest.TestCase):
    def test_str2bool_accepts_common_values_and_rejects_invalid_values(self):
        self.assertTrue(str2bool("YES"))
        self.assertFalse(str2bool("off"))
        self.assertTrue(str2bool(None, default=True))
        with self.assertRaises(ConfigError):
            str2bool("sometimes")

    def test_parse_vector_requires_expected_finite_values(self):
        self.assertEqual(parse_vector("1, 2, 3", length=3, name="location"), (1, 2, 3))
        with self.assertRaises(ConfigError):
            parse_vector("1, nan, 3", length=3, name="location")
        with self.assertRaises(ConfigError):
            parse_vector("1, 2", length=3, name="location")

    def test_degree_sampling_uses_expected_axes_and_wraps_one_turn(self):
        sun = create_light_directions(
            {
                "model": "distant",
                "enable_rendering_by_degree": "X",
                "degree": "180",
                "amount": "1",
                "energy": "3",
                "SUN_angle": "0.1",
            },
            Path("."),
            Path("."),
        )
        self.assertEqual(len(sun), 2)
        self.assertEqual(sun[0][0][:3], (0, 0, 0))
        self.assertAlmostEqual(sun[1][0][0], 3.141592653589793)
        self.assertEqual(sun[0][0][3:], (3.0, 0.1))

        point = create_light_directions(
            {
                "model": "near",
                "enable_rendering_by_degree": "True",
                "degree": "90",
                "amount": "1",
                "POINT_radius": "2",
            },
            Path("."),
            Path("."),
        )
        self.assertEqual(len(point), 4)
        self.assertEqual(point[0][0][:3], (2.0, 0.0, 0.0))

    def test_light_csv_rows_group_by_amount_and_validate_count(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            directions = base / "lights.csv"
            directions.write_text(
                "# comments are allowed\n0, 0, 0, 2\n1, 0, 0\n", encoding="utf-8"
            )
            lights = create_light_directions(
                {
                    "model": "near",
                    "amount": "2",
                    "enable_rendering_by_degree": "false",
                    "light_directions_file": "lights.csv",
                    "energy": "1",
                    "POINT_size": "0.25",
                },
                base,
                base,
            )
            self.assertEqual(len(lights), 1)
            self.assertEqual(lights[0][0][3:], (2.0, 0.25))
            self.assertIsNone(lights[0][1][3])

            with self.assertRaises(ConfigError):
                create_light_directions(
                    {
                        "model": "near",
                        "amount": "3",
                        "enable_rendering_by_degree": "false",
                        "light_directions_file": "lights.csv",
                    },
                    base,
                    base,
                )

    def test_direction_files_validate_zero_sun_vectors(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = base / "directions.csv"
            path.write_text("0,0,0\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                create_light_directions(
                    {
                        "model": "distant",
                        "enable_rendering_by_degree": "false",
                        "file_normalization": "true",
                        "light_directions_file": path.name,
                    },
                    base,
                    base,
                )

    def test_object_views_can_be_disabled_or_read_from_file(self):
        disabled = create_object_directions({}, Path("."), Path("."))
        self.assertEqual(disabled, [(0, 0, 0)])

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "views.csv").write_text("0, 0, 0\n0, 1, 0\n", encoding="utf-8")
            views = create_object_directions(
                {
                    "enable_multiple_views": "true",
                    "enable_rendering_by_degree": "false",
                    "object_directions_file": "views.csv",
                },
                base,
                base,
            )
            self.assertEqual(views, [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0)])

    def test_geometry_maps_handle_flat_depth_and_background_pixels(self):
        depth = np.array([[2.0, 2.0], [1e10, np.inf]], dtype=np.float32)
        normals = np.array(
            [
                [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0]],
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            ],
            dtype=np.float32,
        )
        normalized, mask, mask_alt, encoded, encoded_alt = _build_geometry_data(
            depth, normals
        )
        self.assertTrue(np.all(normalized[:1] == 0.0))
        self.assertTrue(np.all(normalized[1:, :] == 1.0))
        np.testing.assert_array_equal(mask, [[1, 1], [0, 0]])
        np.testing.assert_array_equal(mask_alt, [[1, 1], [0, 0]])
        self.assertEqual(encoded.shape, (2, 2, 3))
        self.assertTrue(np.all(encoded_alt[1] == 0.0))

    def test_geometry_maps_return_empty_masks_without_foreground(self):
        depth = np.full((2, 3), 1e10, dtype=np.float32)
        normals = np.zeros((2, 3, 3), dtype=np.float32)
        normalized, mask, mask_alt, encoded, _ = _build_geometry_data(depth, normals)
        self.assertFalse(np.any(normalized))
        self.assertFalse(np.any(mask))
        self.assertFalse(np.any(mask_alt))
        self.assertFalse(np.any(encoded))

    def test_all_repository_sample_configs_are_loadable(self):
        samples = sorted((ROOT / "config_samples").glob("*.ini"))
        self.assertGreater(len(samples), 0)
        for sample in samples:
            with self.subTest(sample=sample.name):
                job = load_job(sample)
                self.assertEqual(len(job.object_files), len(job.object_params))
                self.assertEqual(len(job.object_files), len(job.shader_params))

    def test_all_generated_experiment_configs_are_loadable(self):
        configs = sorted((ROOT / "misc" / "cfg").glob("*.ini"))
        self.assertGreater(len(configs), 0)
        for config in configs:
            with self.subTest(config=config.name):
                job = load_job(config)
                self.assertEqual(job.working_dir, ROOT / "working_dir")


if __name__ == "__main__":
    unittest.main()
