"""Read uncompressed scanline OpenEXR passes written by Blender's compositor."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any


_PIXEL_DTYPES = {
    0: ("<u4", 4),
    1: ("<f2", 2),
    2: ("<f4", 4),
}


def read_openexr_channels(path: str | Path) -> dict[str, Any]:
    """Read channels from an uncompressed, scanline OpenEXR file."""
    import numpy as np

    path = Path(path)
    data = path.read_bytes()
    if len(data) < 8:
        raise ValueError(f"OpenEXR file is too short: {path}")
    magic, version = struct.unpack_from("<II", data)
    if magic != 20000630 or version & 0xFF != 2 or version & 0x200:
        raise ValueError(f"Unsupported OpenEXR format: {path}")

    attributes: dict[str, tuple[str, bytes]] = {}
    offset = 8
    while True:
        name_end = data.find(b"\0", offset)
        if name_end < 0:
            raise ValueError(f"Invalid OpenEXR header: {path}")
        name = data[offset:name_end].decode("ascii")
        offset = name_end + 1
        if not name:
            break
        type_end = data.find(b"\0", offset)
        if type_end < 0 or type_end + 5 > len(data):
            raise ValueError(f"Invalid OpenEXR header: {path}")
        attribute_type = data[offset:type_end].decode("ascii")
        size = struct.unpack_from("<I", data, type_end + 1)[0]
        offset = type_end + 5
        end = offset + size
        if end > len(data):
            raise ValueError(f"Invalid OpenEXR attribute {name!r}: {path}")
        attributes[name] = (attribute_type, data[offset:end])
        offset = end

    try:
        compression = attributes["compression"][1][0]
        minimum_x, minimum_y, maximum_x, maximum_y = struct.unpack(
            "<4i", attributes["dataWindow"][1]
        )
        channel_data = attributes["channels"][1]
    except (KeyError, IndexError, struct.error) as exc:
        raise ValueError(f"OpenEXR header is missing required attributes: {path}") from exc
    if compression != 0:
        raise ValueError(f"OpenEXR must use no compression: {path}")

    width = maximum_x - minimum_x + 1
    height = maximum_y - minimum_y + 1
    if width < 1 or height < 1:
        raise ValueError(f"OpenEXR has an invalid data window: {path}")

    channels: list[tuple[str, str, int]] = []
    channel_offset = 0
    while channel_offset < len(channel_data) and channel_data[channel_offset]:
        name_end = channel_data.find(b"\0", channel_offset)
        if name_end < 0 or name_end + 17 > len(channel_data):
            raise ValueError(f"Invalid OpenEXR channel list: {path}")
        name = channel_data[channel_offset:name_end].decode("ascii")
        pixel_type = struct.unpack_from("<i", channel_data, name_end + 1)[0]
        x_sampling, y_sampling = struct.unpack_from(
            "<2i", channel_data, name_end + 9
        )
        if pixel_type not in _PIXEL_DTYPES or x_sampling != 1 or y_sampling != 1:
            raise ValueError(f"Unsupported OpenEXR channel format for {name!r}: {path}")
        dtype, item_size = _PIXEL_DTYPES[pixel_type]
        channels.append((name, dtype, item_size))
        channel_offset = name_end + 17
    if not channels:
        raise ValueError(f"OpenEXR has no channels: {path}")

    offset_table_end = offset + height * 8
    if offset_table_end > len(data):
        raise ValueError(f"OpenEXR has an incomplete scanline table: {path}")
    scanline_offsets = struct.unpack_from(f"<{height}Q", data, offset)
    result = {
        name: np.empty((height, width), dtype=np.float32)
        for name, _, _ in channels
    }
    written_rows: set[int] = set()

    for scanline_offset in scanline_offsets:
        if scanline_offset + 8 > len(data):
            raise ValueError(f"OpenEXR has an invalid scanline offset: {path}")
        y, chunk_size = struct.unpack_from("<iI", data, scanline_offset)
        chunk_start = scanline_offset + 8
        chunk_end = chunk_start + chunk_size
        row = y - minimum_y
        if not 0 <= row < height or row in written_rows or chunk_end > len(data):
            raise ValueError(f"OpenEXR has an invalid scanline chunk: {path}")
        written_rows.add(row)

        channel_offset = chunk_start
        for name, dtype, item_size in channels:
            channel_size = width * item_size
            channel_end = channel_offset + channel_size
            if channel_end > chunk_end:
                raise ValueError(f"OpenEXR scanline is truncated: {path}")
            result[name][row] = np.frombuffer(
                data, dtype=dtype, count=width, offset=channel_offset
            )
            channel_offset = channel_end
        if channel_offset != chunk_end:
            raise ValueError(f"OpenEXR scanline has unexpected data: {path}")

    if len(written_rows) != height:
        raise ValueError(f"OpenEXR is missing scanlines: {path}")
    return result
