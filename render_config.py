"""Configuration parsing and validation for the Blender rendering script."""

from __future__ import annotations

import configparser
import csv
import math
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when a render configuration or one of its assets is invalid."""


@dataclass(frozen=True)
class RenderJob:
    config_path: Path
    settings: dict[str, str]
    rendering: dict[str, str]
    light: dict[str, str]
    camera: dict[str, str]
    object_global: dict[str, str]
    object_files: list[str]
    object_params: list[dict[str, str]]
    shader_params: list[dict[str, str]]
    working_dir: Path
    output_dir: Path


def str2bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"true", "t", "yes", "y", "1", "on"}:
        return True
    if normalized in {"false", "f", "no", "n", "0", "off"}:
        return False
    raise ConfigError(f"Expected a boolean value, got {value!r}.")


def split_csv_values(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_vector(value: str, *, length: int, name: str) -> tuple[float, ...]:
    try:
        values = tuple(float(part) for part in split_csv_values(value))
    except ValueError as exc:
        raise ConfigError(f"{name} must contain {length} numeric values.") from exc
    if len(values) != length or not all(math.isfinite(item) for item in values):
        raise ConfigError(f"{name} must contain {length} finite numeric values.")
    return values


def _resolve_working_dir(value: str, config_dir: Path) -> tuple[Path, Path]:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve(), config_dir
    bases = (config_dir, *config_dir.parents, Path.cwd())
    for base in dict.fromkeys(bases):
        candidate = (base / path).resolve()
        if candidate.exists():
            return candidate, base
    return (config_dir / path).resolve(), config_dir


def _enabled_axis(value: str, *, name: str) -> tuple[bool, int | None]:
    normalized = value.strip().lower()
    if normalized in {"x", "y", "z"}:
        return True, {"x": 0, "y": 1, "z": 2}[normalized]
    if normalized in {"true", "t", "yes", "y", "1", "on"}:
        return True, None
    if normalized in {"false", "f", "no", "n", "0", "off", ""}:
        return False, None
    raise ConfigError(f"{name} must be a boolean value or an X, Y, or Z axis.")


def resolve_asset(value: str, working_dir: Path, config_dir: Path) -> Path:
    """Resolve an asset relative to the working directory, then the config."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    for candidate in (working_dir / path, config_dir / path):
        if candidate.exists():
            return candidate.resolve()
    return (working_dir / path).resolve()


def _read_rows(
    path: Path, *, expected_columns: tuple[int, ...], label: str
) -> list[tuple[int, list[str]]]:
    rows: list[tuple[int, list[str]]] = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.reader(source)
            for row in reader:
                line_number = reader.line_num
                if not row or not any(cell.strip() for cell in row):
                    continue
                if row[0].lstrip().startswith("#"):
                    continue
                if len(row) not in expected_columns:
                    accepted = " or ".join(map(str, expected_columns))
                    raise ConfigError(
                        f"{label} {path}:{line_number} must have {accepted} columns."
                    )
                rows.append((line_number, [cell.strip() for cell in row]))
    except OSError as exc:
        raise ConfigError(f"Cannot read {label} file: {path}") from exc
    if not rows:
        raise ConfigError(f"{label} file contains no data rows: {path}")
    return rows


def _float_cell(value: str, *, path: Path, line: int, column: int) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ConfigError(
            f"{path}:{line} column {column} must be a number, got {value!r}."
        ) from exc
    if not math.isfinite(result):
        raise ConfigError(f"{path}:{line} column {column} must be finite.")
    return result


def _degree_steps(value: str, *, name: str) -> tuple[float, int]:
    try:
        degree = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive divisor of 360.") from exc
    if not math.isfinite(degree) or degree <= 0:
        raise ConfigError(f"{name} must be a positive divisor of 360.")
    steps = round(360 / degree)
    if steps < 1 or not math.isclose(steps * degree, 360, abs_tol=1e-6):
        raise ConfigError(f"{name} must be a positive divisor of 360.")
    return degree, steps


def create_light_directions(
    params_light: dict[str, str], working_dir: Path, config_dir: Path
) -> list[list[tuple[float, float, float, float | None, float]]]:
    """Return light samples grouped by render, with 3 coordinates and 2 settings."""
    model = params_light.get("model", "distant").strip().lower()
    if model not in {"distant", "near"}:
        raise ConfigError("light.model must be 'distant' or 'near'.")

    try:
        amount = int(params_light.get("amount", "1"))
    except ValueError as exc:
        raise ConfigError("light.amount must be a positive integer.") from exc
    if amount < 1:
        raise ConfigError("light.amount must be a positive integer.")

    enabled_value = params_light.get("enable_rendering_by_degree", "false")
    enabled, selected_axis = _enabled_axis(
        enabled_value, name="light.enable_rendering_by_degree"
    )
    is_sun = model == "distant"
    size_key = "SUN_angle" if is_sun else "POINT_size"
    try:
        default_energy = float(params_light.get("energy", "1"))
        default_size = float(params_light.get(size_key, "0.25"))
    except ValueError as exc:
        raise ConfigError("Light energy and size settings must be numeric.") from exc
    if not math.isfinite(default_energy) or not math.isfinite(default_size):
        raise ConfigError("Light energy and size settings must be finite.")
    if default_energy < 0 or default_size < 0:
        raise ConfigError("Light energy and size settings cannot be negative.")

    samples: list[tuple[float, float, float, float | None, float]] = []
    if enabled:
        degree, count = _degree_steps(params_light.get("degree", "360"), name="light.degree")
        radius = 0.0
        if not is_sun:
            try:
                radius = float(params_light.get("POINT_radius", "5"))
            except ValueError as exc:
                raise ConfigError("light.POINT_radius must be numeric.") from exc
            if not math.isfinite(radius) or radius <= 0:
                raise ConfigError("light.POINT_radius must be positive and finite.")
        for index in range(count):
            angle = math.radians(index * degree)
            coordinates = [0.0, 0.0, 0.0]
            if is_sun:
                axis = selected_axis if selected_axis is not None else 1
                coordinates[axis] = angle
            else:
                axis = selected_axis if selected_axis is not None else 2
                coordinates[(axis + 1) % 3] = radius * math.cos(angle)
                coordinates[(axis + 2) % 3] = radius * math.sin(angle)
            samples.append(
                (coordinates[0], coordinates[1], coordinates[2], default_energy, default_size)
            )
    else:
        filename = params_light.get("light_directions_file", "").strip()
        if not filename:
            raise ConfigError(
                "light.light_directions_file is required when degree sampling is disabled."
            )
        path = resolve_asset(filename, working_dir, config_dir)
        if not path.is_file():
            raise ConfigError(f"Light direction file does not exist: {path}")
        rows = _read_rows(path, expected_columns=(3, 4, 5), label="Light directions")
        normalize = str2bool(params_light.get("file_normalization"), default=False)
        for line_number, row in rows:
            coords = tuple(
                _float_cell(cell, path=path, line=line_number, column=index)
                for index, cell in enumerate(row[:3], start=1)
            )
            energy = (
                _float_cell(row[3], path=path, line=line_number, column=4)
                if len(row) >= 4 and row[3] else None
            )
            size = (
                _float_cell(row[4], path=path, line=line_number, column=5)
                if len(row) >= 5 and row[4] else default_size
            )
            if size < 0:
                raise ConfigError(f"{path}:{line_number} light size cannot be negative.")
            if normalize and is_sun and math.isclose(
                math.sqrt(sum(component * component for component in coords)), 0.0
            ):
                raise ConfigError(f"{path}:{line_number} has a zero-length sun direction.")
            samples.append((coords[0], coords[1], coords[2], energy, size))

    if len(samples) % amount:
        raise ConfigError(
            f"Light sample count ({len(samples)}) must be divisible by light.amount ({amount})."
        )
    return [samples[index:index + amount] for index in range(0, len(samples), amount)]


def create_object_directions(
    params_object_global: dict[str, str], working_dir: Path, config_dir: Path
) -> list[tuple[float, float, float]]:
    if not str2bool(params_object_global.get("enable_multiple_views"), default=False):
        return [(0.0, 0.0, 0.0)]

    enabled_value = params_object_global.get("enable_rendering_by_degree", "false")
    enabled, selected_axis = _enabled_axis(
        enabled_value, name="object.enable_rendering_by_degree"
    )
    if enabled:
        degree, count = _degree_steps(
            params_object_global.get("degree", "360"), name="object.degree"
        )
        axis = selected_axis if selected_axis is not None else 1
        return [
            tuple(
                math.radians(index * degree) if coordinate == axis else 0.0
                for coordinate in range(3)
            )
            for index in range(count)
        ]

    filename = params_object_global.get("object_directions_file", "").strip()
    if not filename:
        raise ConfigError(
            "object.object_directions_file is required when degree sampling is disabled."
        )
    path = resolve_asset(filename, working_dir, config_dir)
    if not path.is_file():
        raise ConfigError(f"Object direction file does not exist: {path}")
    rows = _read_rows(path, expected_columns=(3,), label="Object directions")
    return [
        tuple(
            _float_cell(cell, path=path, line=line_number, column=index)
            for index, cell in enumerate(row, start=1)
        )
        for line_number, row in rows
    ]


def _normalise_presets(value: str, count: int, *, setting: str) -> list[str]:
    presets = split_csv_values(value)
    if not presets:
        raise ConfigError(f"{setting} must name at least one preset.")
    if len(presets) < count:
        presets.extend([presets[-1]] * (count - len(presets)))
    return presets[:count]


def _finite_number(value: str, *, name: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be numeric.") from exc
    if not math.isfinite(number):
        raise ConfigError(f"{name} must be finite.")
    return number


def load_job(config_path: str | Path) -> RenderJob:
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"Configuration file does not exist: {path}")

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        with path.open(encoding="utf-8-sig") as source:
            parser.read_file(source)
    except (OSError, configparser.Error) as exc:
        raise ConfigError(f"Cannot read configuration file {path}: {exc}") from exc

    if not parser.has_section("settings"):
        raise ConfigError(f"{path} is missing the [settings] section.")
    settings = {
        key.lower(): value.strip()
        for key, value in parser.items("settings")
    }
    object_files = split_csv_values(settings.get("object_file", ""))
    if not object_files:
        raise ConfigError(f"{path} [settings] must define object_file.")

    def section_values(name: str) -> dict[str, str]:
        if not parser.has_section(name):
            return {}
        return {
            key.lower(): value.strip()
            for key, value in parser.items(name)
        }

    config_dir = path.parent
    working_dir, settings_base = _resolve_working_dir(
        settings.get("working_dir", "."), config_dir
    )
    output_path = Path(settings.get("out_dir", "output")).expanduser()
    output_dir = (
        output_path.resolve()
        if output_path.is_absolute() else (settings_base / output_path).resolve()
    )
    rendering = section_values("rendering")
    light = section_values("light")
    camera = section_values("camera")
    object_global = section_values("object")

    object_presets = _normalise_presets(
        object_global.get("preset", "object_custom"),
        len(object_files),
        setting="[object] preset",
    )
    shader_presets = _normalise_presets(
        section_values("shader").get("preset", "default"),
        len(object_files),
        setting="[shader] preset",
    )
    object_params: list[dict[str, str]] = []
    shader_params: list[dict[str, str]] = []
    for name in object_presets:
        if not parser.has_section(name):
            raise ConfigError(f"{path} is missing the object preset section [{name}].")
        object_params.append(section_values(name))
    for name in shader_presets:
        if not parser.has_section(name):
            raise ConfigError(f"{path} is missing the shader preset section [{name}].")
        shader_params.append(section_values(name))

    for object_name in object_files:
        if object_name.lower() == "sphere":
            continue
        object_path = resolve_asset(object_name, working_dir, config_dir)
        if not object_path.is_file():
            raise ConfigError(f"Object file does not exist: {object_path}")
        if object_path.suffix.lower() not in {".obj", ".fbx", ".ply", ".stl", ".x3d"}:
            raise ConfigError(f"Unsupported object format: {object_path.suffix}")

    hdri = rendering.get("use_hdri", "")
    if hdri and hdri.lower() != "none":
        hdri_path = resolve_asset(hdri, working_dir, config_dir)
        if not hdri_path.is_file():
            raise ConfigError(f"HDRI file does not exist: {hdri_path}")

    for shader in shader_params:
        for key, value in shader.items():
            if key.endswith("_texture") and value:
                texture_path = resolve_asset(value, working_dir, config_dir)
                if not texture_path.is_file():
                    raise ConfigError(f"Texture file does not exist: {texture_path}")
            elif key in {
                "subsurface", "metallic", "specular", "specular_tint",
                "roughness", "anisotropic", "anisotropic_rotation", "sheen",
                "sheen_tint", "clearcoat", "clearcoat_roughness",
                "transmission", "transmission_roughness", "ior", "alpha",
                "emission_strength",
            } and value:
                _finite_number(value, name=f"shader.{key}")
            elif key in {"base_color", "subsurface_color", "emission"} and value:
                components = parse_vector(
                    value, length=3 if len(split_csv_values(value)) == 3 else 4,
                    name=f"shader.{key}",
                )
                if any(component < 0 or component > 255 for component in components):
                    raise ConfigError(f"shader.{key} components must be in [0, 255].")
            elif key == "load_uv":
                str2bool(value)

    for key, default, minimum in (
        ("resolution_x", "640", 1),
        ("resolution_y", "480", 1),
        ("samples", "64", 1),
        ("max_bounces", "12", 0),
        ("min_light_bounces", rendering.get("min_bounces", "0"), 0),
        ("min_bounces", "0", 0),
        ("glossy_bounces", "4", 0),
        ("transmission_bounces", "12", 0),
        ("volume_bounces", "0", 0),
        ("transparent_max_bounces", "8", 0),
        ("min_transparent_bounces", rendering.get("transparent_min_bounces", "0"), 0),
        ("transparent_min_bounces", "0", 0),
    ):
        try:
            number = int(rendering.get(key, default))
        except ValueError as exc:
            raise ConfigError(f"rendering.{key} must be an integer.") from exc
        if number < minimum:
            raise ConfigError(f"rendering.{key} must be at least {minimum}.")
    color_mode = rendering.get("color_mode", "RGB").upper()
    if color_mode not in {"BW", "RGB", "RGBA"}:
        raise ConfigError("rendering.color_mode must be BW, RGB, or RGBA.")
    if rendering.get("device", "CPU").upper() not in {"CPU", "GPU"}:
        raise ConfigError("rendering.device must be CPU or GPU.")

    camera_model = camera.get("model", "perspective").lower()
    if camera_model not in {
        "o", "ortho", "orthographic",
        "p", "persp", "perspective",
        "pano", "panorama"
    }:
        raise ConfigError(
            "camera.model must be orthographic, perspective, or panorama."
        )
    for key, default in (
        ("location", "0, 0, 10"),
        ("rotation", "0, 0, 0"),
    ):
        parse_vector(camera.get(key, default), length=3, name=f"camera.{key}")
    for key, default in (
        ("sensor_width", "36"),
        ("sensor_height", "24"),
        ("focal_length", "50"),
    ):
        if _finite_number(camera.get(key, default), name=f"camera.{key}") <= 0:
            raise ConfigError(f"camera.{key} must be positive.")
    for key in (
        "clip_start", "clip_end", "ortho_scale", "focus_distance",
        "aperture_fstop", "aperture_ratio",
    ):
        if key in camera and _finite_number(camera[key], name=f"camera.{key}") <= 0:
            raise ConfigError(f"camera.{key} must be positive.")
    for key in ("shift_x", "shift_y", "aperture_rotation", "aperture_ratio"):
        if key in camera:
            _finite_number(camera[key], name=f"camera.{key}")
    if "aperture_blades" in camera:
        try:
            if int(camera["aperture_blades"]) < 0:
                raise ConfigError("camera.aperture_blades cannot be negative.")
        except ValueError as exc:
            raise ConfigError("camera.aperture_blades must be an integer.") from exc
    str2bool(camera.get("use_dof"), default=False)
    if "enable_rendering_by_degree" in object_global:
        _enabled_axis(
            object_global["enable_rendering_by_degree"],
            name="object.enable_rendering_by_degree",
        )

    for shape, params in zip(object_files, object_params):
        for key, default in (
            ("location", "0, 0, 0"),
            ("rotation", "0, 0, 0"),
        ):
            parse_vector(params.get(key, default), length=3, name=f"object.{key}")
        for key in ("use_smooth", "no_shadow", "geometry_to_origin", "subdivision_surface"):
            if key in params:
                str2bool(params[key])
        if shape.lower() == "sphere":
            for key, default in (
                ("radius", "1"),
                ("segments", "32"),
                ("ring_count", "16"),
            ):
                number = _finite_number(params.get(key, default), name=f"object_sphere.{key}")
                if number <= 0 or (key != "radius" and not number.is_integer()):
                    raise ConfigError(f"object_sphere.{key} must be a positive integer or number.")
        else:
            max_dimension = params.get("max_dimension", "none")
            if max_dimension.lower() != "none" and _finite_number(
                max_dimension, name="object_custom.max_dimension"
            ) <= 0:
                raise ConfigError("object_custom.max_dimension must be positive or None.")

    for values in (light, object_global):
        for key in ("synchronize_with_views", "file_normalization"):
            if key in values:
                str2bool(values[key])

    for key in (
        "denoising", "denoising_legacy", "transparent_background",
        "disable_anti_aliasing", "no_background", "synchronize_with_views",
    ):
        if key in rendering:
            str2bool(rendering[key])
    if "background_color" in rendering and rendering["background_color"]:
        components = parse_vector(
            rendering["background_color"],
            length=3 if len(split_csv_values(rendering["background_color"])) == 3 else 4,
            name="rendering.background_color",
        )
        if any(component < 0 or component > 255 for component in components):
            raise ConfigError("rendering.background_color components must be in [0, 255].")
    if "hdri_offset" in rendering:
        _finite_number(rendering["hdri_offset"], name="rendering.hdri_offset")

    create_light_directions(light, working_dir, config_dir)
    create_object_directions(object_global, working_dir, config_dir)

    return RenderJob(
        config_path=path,
        settings=settings,
        rendering=rendering,
        light=light,
        camera=camera,
        object_global=object_global,
        object_files=object_files,
        object_params=object_params,
        shader_params=shader_params,
        working_dir=working_dir,
        output_dir=output_dir,
    )
