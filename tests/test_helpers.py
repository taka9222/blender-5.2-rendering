import math
import tempfile
import unittest
from pathlib import Path

from misc.directional2euler import _read_directions, direction_to_euler
from working_dir.visualization import read_samples


def _rotated_z_axis(angles):
    x, y, z = angles
    cos_x, sin_x = math.cos(x), math.sin(x)
    cos_y, sin_y = math.cos(y), math.sin(y)
    cos_z, sin_z = math.cos(z), math.sin(z)
    return (
        cos_z * sin_y * cos_x + sin_z * sin_x,
        sin_z * sin_y * cos_x - cos_z * sin_x,
        cos_y * cos_x,
    )


class HelperTests(unittest.TestCase):
    def test_direction_conversion_handles_axes_and_gimbal_lock(self):
        for direction in (
            (1, 0, 0),
            (0, 1, 0),
            (0, -1, 0),
            (0, 0, 1),
            (0, 0, -1),
            (1, 2, 3),
        ):
            with self.subTest(direction=direction):
                length = math.sqrt(sum(component * component for component in direction))
                expected = tuple(component / length for component in direction)
                actual = _rotated_z_axis(direction_to_euler(direction))
                for actual_component, expected_component in zip(actual, expected):
                    self.assertAlmostEqual(actual_component, expected_component, places=7)

    def test_direction_input_skips_blank_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "directions.txt"
            path.write_text("# heading\n\n1, 0, 0\n0 1 0 # second\n", encoding="utf-8")
            self.assertEqual(_read_directions(path), [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])

    def test_direction_input_rejects_zero_vector(self):
        with self.assertRaises(ValueError):
            direction_to_euler((0.0, 0.0, 0.0))

    def test_visualization_reads_csv_and_whitespace_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            csv_path = base / "samples.csv"
            csv_path.write_text("# samples\n-1, 0, 0.5\n1, 0, 1\n", encoding="utf-8")
            txt_path = base / "samples.txt"
            txt_path.write_text("-1 0 0.5\n1   0 1\n", encoding="utf-8")
            self.assertEqual(read_samples(csv_path), read_samples(txt_path))
            self.assertEqual(read_samples(csv_path), ([-1.0, 1.0], [0.0, 0.0], [0.5, 1.0]))


if __name__ == "__main__":
    unittest.main()
