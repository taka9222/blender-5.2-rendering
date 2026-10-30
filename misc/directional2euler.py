#!/usr/bin/env python3
"""Convert one direction vector per line to XYZ Euler angles in radians."""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path


def direction_to_euler(
    direction: tuple[float, float, float],
) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in direction))
    if not math.isfinite(length) or length == 0:
        raise ValueError("Direction vectors must be finite and non-zero.")
    z_axis = tuple(component / length for component in direction)
    up = (0.0, 1.0, 0.0)
    x_axis = (
        up[1] * z_axis[2] - up[2] * z_axis[1],
        up[2] * z_axis[0] - up[0] * z_axis[2],
        up[0] * z_axis[1] - up[1] * z_axis[0],
    )
    x_length = math.sqrt(sum(component * component for component in x_axis))
    if x_length < 1e-12:
        up = (1.0, 0.0, 0.0)
        x_axis = (
            up[1] * z_axis[2] - up[2] * z_axis[1],
            up[2] * z_axis[0] - up[0] * z_axis[2],
            up[0] * z_axis[1] - up[1] * z_axis[0],
        )
        x_length = math.sqrt(sum(component * component for component in x_axis))
    x_axis = tuple(component / x_length for component in x_axis)
    y_axis = (
        z_axis[1] * x_axis[2] - z_axis[2] * x_axis[1],
        z_axis[2] * x_axis[0] - z_axis[0] * x_axis[2],
        z_axis[0] * x_axis[1] - z_axis[1] * x_axis[0],
    )

    r11, r12, r13 = x_axis[0], y_axis[0], z_axis[0]
    r21 = x_axis[1]
    r31, r32, r33 = x_axis[2], y_axis[2], z_axis[2]
    r31 = max(-1.0, min(1.0, r31))
    y_angle = -math.asin(r31)
    cosine = math.cos(y_angle)
    if abs(cosine) > 1e-12:
        x_angle = math.atan2(r32, r33)
        z_angle = math.atan2(r21, r11)
    elif r31 < 0:
        x_angle = math.atan2(r12, r13)
        z_angle = 0.0
    else:
        x_angle = math.atan2(-r12, -r13)
        z_angle = 0.0
    return x_angle, y_angle, z_angle


def _read_directions(path: Path) -> list[tuple[float, float, float]]:
    directions = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        text = line.partition("#")[0].strip()
        if not text:
            continue
        values = re.split(r"[\s,]+", text)
        if len(values) != 3:
            raise ValueError(f"{path}:{line_number} must contain three values.")
        try:
            direction = tuple(float(value) for value in values)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number} contains a non-numeric value.") from exc
        if not all(math.isfinite(value) for value in direction):
            raise ValueError(f"{path}:{line_number} values must be finite.")
        directions.append(direction)
    if not directions:
        raise ValueError(f"No direction vectors found in {path}.")
    return directions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="text or CSV file with XYZ vectors")
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="optional output file (defaults to standard output)",
    )
    args = parser.parse_args(argv)
    try:
        rows = [
            direction_to_euler(direction)
            for direction in _read_directions(args.input)
        ]
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    output = "\n".join(f"{x:.8g}, {y:.8g}, {z:.8g}" for x, y, z in rows) + "\n"
    if args.output is None:
        sys.stdout.write(output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
