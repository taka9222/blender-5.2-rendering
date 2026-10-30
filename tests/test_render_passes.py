import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from render_passes import read_openexr_channels


def _attribute(name, attribute_type, value):
    return (
        name.encode("ascii")
        + b"\0"
        + attribute_type.encode("ascii")
        + b"\0"
        + struct.pack("<I", len(value))
        + value
    )


def _write_test_exr(path, channels, minimum_y=0):
    height, width = next(iter(channels.values())).shape
    channel_list = b"".join(
        name.encode("ascii") + b"\0" + struct.pack("<iB3xii", 2, 0, 1, 1)
        for name in channels
    ) + b"\0"
    maximum_y = minimum_y + height - 1
    header = b"".join(
        (
            _attribute("channels", "chlist", channel_list),
            _attribute("compression", "compression", b"\0"),
            _attribute(
                "dataWindow",
                "box2i",
                struct.pack("<4i", 0, minimum_y, width - 1, maximum_y),
            ),
        )
    ) + b"\0"
    header = struct.pack("<II", 20000630, 2) + header
    chunk_size = 8 + width * 4 * len(channels)
    first_chunk = len(header) + height * 8
    offsets = [
        first_chunk + row * chunk_size
        for row in reversed(range(height))
    ]
    chunks = []
    for row in reversed(range(height)):
        pixel_data = b"".join(
            values[row].astype("<f4").tobytes() for values in channels.values()
        )
        chunks.append(struct.pack("<iI", minimum_y + row, len(pixel_data)) + pixel_data)
    path.write_bytes(
        header + struct.pack(f"<{height}Q", *offsets) + b"".join(chunks)
    )


class RenderPassReaderTests(unittest.TestCase):
    def test_reads_float_channels_and_scanlines_in_any_order(self):
        expected_x = np.array([[1, 2], [3, 4]], dtype=np.float32)
        expected_z = np.array([[5, 6], [7, 8]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "passes.exr"
            _write_test_exr(
                path,
                {"Normal.X": expected_x, "Normal.Z": expected_z},
                minimum_y=-1,
            )
            actual = read_openexr_channels(path)

        np.testing.assert_array_equal(actual["Normal.X"], expected_x)
        np.testing.assert_array_equal(actual["Normal.Z"], expected_z)

    def test_rejects_non_exr_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.exr"
            path.write_bytes(b"not an exr")
            with self.assertRaisesRegex(ValueError, "Unsupported OpenEXR"):
                read_openexr_channels(path)


if __name__ == "__main__":
    unittest.main()
