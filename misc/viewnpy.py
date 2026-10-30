#!/usr/bin/env python3
"""Display a NumPy image or save it to a regular image file."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="path to a .npy image")
    parser.add_argument("--cmap", default="gray", help="colormap for 2D arrays")
    parser.add_argument("--save", type=Path, help="save the plot instead of opening a window")
    args = parser.parse_args(argv)

    try:
        image = np.load(args.image, allow_pickle=False)
    except (OSError, ValueError) as exc:
        parser.error(f"Cannot load {args.image}: {exc}")
    if image.ndim not in {2, 3} or (image.ndim == 3 and image.shape[2] not in {3, 4}):
        parser.error("Expected a 2D array or an RGB/RGBA image array.")

    import matplotlib.pyplot as plt

    if image.ndim == 2:
        plt.imshow(image, cmap=args.cmap)
        plt.colorbar()
    else:
        plt.imshow(np.clip(image, 0.0, 1.0))
    plt.axis("off")
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(args.save, bbox_inches="tight", pad_inches=0)
    else:
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
