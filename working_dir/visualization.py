#!/usr/bin/env python3
"""Plot three-column (x, y, value) CSV or whitespace-separated data."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


def read_samples(path: Path) -> tuple[list[float], list[float], list[float]]:
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".txt"}:
        raise ValueError("Input file must have a .csv or .txt extension.")

    x_values: list[float] = []
    y_values: list[float] = []
    values: list[float] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        for line_number, line in enumerate(source, start=1):
            text = line.partition("#")[0].strip()
            if not text:
                continue
            row = next(csv.reader([text])) if suffix == ".csv" else text.split()
            if len(row) != 3:
                raise ValueError(f"{path}:{line_number} must contain three values.")
            try:
                x, y, value = (float(item) for item in row)
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_number} contains a non-numeric value."
                ) from exc
            if not all(math.isfinite(item) for item in (x, y, value)):
                raise ValueError(f"{path}:{line_number} values must be finite.")
            x_values.append(x)
            y_values.append(y)
            values.append(value)
    if not values:
        raise ValueError(f"No data rows found in {path}.")
    return x_values, y_values, values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="input .csv or .txt file")
    parser.add_argument("output", type=Path, help="output image path")
    args = parser.parse_args(argv)
    try:
        x_values, y_values, values = read_samples(args.input)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    import matplotlib.pyplot as plt

    plot = plt.scatter(x_values, y_values, s=5, c=values, cmap="jet", vmin=0, vmax=1)
    plt.xlim(-1, 1)
    plt.ylim(-1, 1)
    plt.xticks([-1, -0.5, 0, 0.5, 1])
    plt.yticks([-1, -0.5, 0, 0.5, 1])
    plt.title(args.input.stem)
    plt.colorbar(plot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output)
    plt.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
