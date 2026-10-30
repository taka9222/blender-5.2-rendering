#!/usr/bin/env python3
"""Batch-render objects and geometry data maps with Blender 5.2."""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import tempfile
import time
import traceback
import warnings
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))


try:
    import bpy
    from mathutils import Euler, Matrix, Vector
    from render_config import (
        ConfigError, RenderJob, create_light_directions, create_object_directions,
        load_job, parse_vector, resolve_asset, split_csv_values, str2bool,
    )
    from render_passes import read_openexr_channels
except ModuleNotFoundError:
    bpy = None
    Euler = Matrix = Vector = None


_SOCKET_ALIASES = {
    "subsurface": ("Subsurface Weight", "Subsurface"),
    "metallic": ("Metallic",),
    "specular": ("Specular IOR Level", "Specular"),
    "specular_tint": ("Specular Tint",),
    "roughness": ("Roughness",),
    "anisotropic": ("Anisotropic IOR Level", "Anisotropic"),
    "anisotropic_rotation": ("Anisotropic Rotation",),
    "sheen": ("Sheen Weight", "Sheen"),
    "sheen_tint": ("Sheen Tint",),
    "clearcoat": ("Coat Weight", "Clearcoat"),
    "clearcoat_roughness": ("Coat Roughness", "Clearcoat Roughness"),
    "transmission": ("Transmission Weight", "Transmission"),
    "transmission_roughness": ("Transmission Roughness",),
    "ior": ("IOR",),
    "alpha": ("Alpha",),
    "base_color": ("Base Color",),
    "subsurface_color": ("Subsurface Color",),
    "emission": ("Emission Color", "Emission"),
    "emission_strength": ("Emission Strength",),
}

_TEXTURE_SOCKETS = {
    "color_texture": ("Base Color",),
    "metallic_texture": ("Metallic",),
    "specular_texture": ("Specular IOR Level", "Specular"),
    "roughness_texture": ("Roughness",),
    "sheen_texture": ("Sheen Weight", "Sheen"),
    "sheentint_texture": ("Sheen Tint",),
    "ior_texture": ("IOR",),
}

_SCALAR_SHADER_KEYS = {
    "subsurface", "metallic", "specular", "specular_tint", "roughness",
    "anisotropic", "anisotropic_rotation", "sheen", "sheen_tint",
    "clearcoat", "clearcoat_roughness", "transmission",
    "transmission_roughness", "ior", "alpha", "emission_strength",
}


def _require_blender() -> None:
    if bpy is None:
        raise RuntimeError(
            "Rendering requires Blender's bundled Python. Run this script with "
            "`blender -b -P render_object.py -- config.ini`."
        )


def _value(values: dict[str, str], key: str, default: str) -> str:
    return values.get(key, default).strip()


def _vector_setting(
    values: dict[str, str], key: str, default: str, *, length: int = 3
) -> tuple[float, ...]:
    return parse_vector(_value(values, key, default), length=length, name=key)


def _get_socket(node: Any, aliases: tuple[str, ...], *, setting: str) -> Any:
    for name in aliases:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    raise ConfigError(
        f"Blender's Principled BSDF has no socket for shader setting {setting!r}."
    )


def _linear_color(value: str, *, setting: str) -> tuple[float, float, float, float]:
    components = parse_vector(value, length=3 if len(split_csv_values(value)) == 3 else 4,
                              name=setting)
    if any(component < 0 or component > 255 for component in components):
        raise ConfigError(f"{setting} color components must be in [0, 255].")
    rgb = components[:3]
    linear = tuple(
        component / 255 / 12.92
        if component / 255 <= 0.04045
        else ((component / 255 + 0.055) / 1.055) ** 2.4
        for component in rgb
    )
    alpha = components[3] / 255 if len(components) == 4 else 1.0
    return linear[0], linear[1], linear[2], alpha


def _remove_scene_objects(scene: Any) -> None:
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (
        bpy.data.materials,
        bpy.data.meshes,
        bpy.data.lights,
        bpy.data.cameras,
    ):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)


def _new_world(scene: Any, params: dict[str, str], working_dir: Path, config_dir: Path) -> Any:
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.cycles_visibility.camera = True
    nodes = world.node_tree.nodes
    nodes.clear()
    output = nodes.new(type="ShaderNodeOutputWorld")
    background = nodes.new(type="ShaderNodeBackground")
    world.node_tree.links.new(
        background.outputs["Background"], output.inputs["Surface"]
    )

    color = params.get("background_color", "0, 0, 0").strip()
    background.inputs["Color"].default_value = _linear_color(
        color, setting="background_color"
    )

    hdri = params.get("use_hdri", "").strip()
    if hdri and hdri.lower() != "none":
        image_path = resolve_asset(hdri, working_dir, config_dir)
        texcoord = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        mapping.name = "Render HDRI Mapping"
        mapping.inputs["Rotation"].default_value = (
            math.pi / 2,
            0.0,
            float(params.get("hdri_offset", "0")),
        )
        environment = nodes.new("ShaderNodeTexEnvironment")
        environment.image = bpy.data.images.load(str(image_path), check_existing=True)
        world.node_tree.links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
        world.node_tree.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
        world.node_tree.links.new(environment.outputs["Color"], background.inputs["Color"])
        if str2bool(params.get("no_background"), default=False):
            world.cycles_visibility.camera = False
    return world


def _configure_scene(scene: Any, params: dict[str, str]) -> None:
    render = scene.render
    cycles = scene.cycles
    render.engine = "CYCLES"
    scene.display_settings.display_device = 'sRGB'
    scene.view_settings.view_transform = 'Raw'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.sequencer_colorspace_settings.name = 'Non-Color'
    render.resolution_x = int(_value(params, "resolution_x", "640"))
    render.resolution_y = int(_value(params, "resolution_y", "480"))
    render.resolution_percentage = 100
    render.use_compositing = False
    render.image_settings.file_format = "PNG"
    render.image_settings.color_depth = "16"
    render.image_settings.color_mode = _value(params, "color_mode", "RGB").upper()
    render.film_transparent = str2bool(
        params.get("transparent_background"), default=False
    )
    for name, default in (
        ("samples", "64"),
        ("max_bounces", "12"),
        ("glossy_bounces", "4"),
        ("transmission_bounces", "12"),
        ("volume_bounces", "0"),
        ("transparent_max_bounces", "8"),
    ):
        setattr(cycles, name, int(_value(params, name, default)))
    cycles.min_light_bounces = int(
        _value(params, "min_light_bounces", _value(params, "min_bounces", "0"))
    )
    cycles.min_transparent_bounces = int(
        _value(
            params, "min_transparent_bounces",
            _value(params, "transparent_min_bounces", "0"),
        )
    )

    if str2bool(params.get("disable_anti_aliasing"), default=False):
        cycles.pixel_filter_type = "GAUSSIAN"
        cycles.filter_width = 0.01

    denoising = str2bool(params.get("denoising"), default=False) or str2bool(
        params.get("denoising_legacy"), default=False
    )
    for view_layer in scene.view_layers:
        view_layer.cycles.use_denoising = denoising
        view_layer.use_pass_normal = True
        view_layer.use_pass_z = True

    if "tile_x" in params or "tile_y" in params:
        warnings.warn(
            "tile_x and tile_y are obsolete in Blender 5.2 and are ignored.",
            stacklevel=2,
        )


def _configure_device(scene: Any, params: dict[str, str]) -> None:
    device = _value(params, "device", "CPU").upper()
    if device == "CPU":
        scene.cycles.device = "CPU"
        return
    if device != "GPU":
        raise ConfigError("rendering.device must be CPU or GPU.")

    cycles_addon = bpy.context.preferences.addons.get("cycles")
    if cycles_addon is None:
        raise RuntimeError("The Cycles add-on is not enabled in Blender preferences.")
    preferences = cycles_addon.preferences
    backend_property = preferences.bl_rna.properties.get("compute_device_type")
    backend_ids = (
        [item.identifier for item in backend_property.enum_items]
        if backend_property is not None
        else []
    )
    for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        if backend not in backend_ids:
            continue
        preferences.compute_device_type = backend
        preferences.get_devices()
        gpu_devices = [item for item in preferences.devices if item.type != "CPU"]
        if gpu_devices:
            for item in preferences.devices:
                item.use = item.type != "CPU"
            scene.cycles.device = "GPU"
            print(f"Using Cycles GPU backend: {backend}")
            return
    raise RuntimeError(
        "rendering.device is GPU, but Blender detected no supported GPU. "
        "Choose CPU or configure a supported Cycles device."
    )


def _set_camera(params: dict[str, str], scene: Any) -> Any:
    camera_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.location = _vector_setting(params, "location", "0, 0, 10")
    camera.rotation_euler = _vector_setting(params, "rotation", "0, 0, 0")
    camera_model = _value(params, "model", "perspective").upper()
    if camera_model in {"O", "ORTHO", "ORTHOGRAPHIC"}:
        camera_model = "ORTHO"
    if camera_model in {"P", "PERSP", "PERSPECTIVE"}:
        camera_model = "PERSP"
    if camera_model in {"PANO", "PANORAMA"}:
        camera_model = "PANO"
    if camera_model not in {"ORTHO", "PERSP", "PANO"}:
        raise ConfigError("camera.model must be orthographic, perspective, or panorama.")
    camera_data.type = camera_model
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.sensor_width = float(_value(params, "sensor_width", "36"))
    camera_data.sensor_height = float(_value(params, "sensor_height", "24"))
    camera_data.lens = float(_value(params, "focal_length", "50"))
    for name in ("clip_start", "clip_end", "ortho_scale", "shift_x", "shift_y"):
        if name in params:
            setattr(camera_data, name, float(params[name]))

    dof_params = camera_data.dof
    dof_params.use_dof = str2bool(params.get("use_dof"), default=False)
    for name in ("focus_distance", "aperture_fstop", "aperture_rotation", "aperture_ratio"):
        if name in params:
            setattr(dof_params, name, float(params[name]))
    if "aperture_blades" in params:
        dof_params.aperture_blades = int(params["aperture_blades"])
    return camera


def _set_smooth(obj: Any) -> None:
    if obj.type == "MESH":
        for polygon in obj.data.polygons:
            polygon.use_smooth = True


def _set_shadow_visibility(obj: Any, disabled: bool) -> None:
    if not disabled:
        return
    if hasattr(obj, "visible_shadow"):
        obj.visible_shadow = False
    elif hasattr(obj, "cycles_visibility"):
        obj.cycles_visibility.shadow = False
    else:
        raise RuntimeError(
            f"Blender does not expose shadow visibility for object {obj.name!r}."
        )


def _set_sphere(params: dict[str, str], index: int, scene: Any) -> Any:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=int(_value(params, "segments", "32")),
        ring_count=int(_value(params, "ring_count", "16")),
        radius=float(_value(params, "radius", "1")),
        location=_vector_setting(params, "location", "0, 0, 0"),
        rotation=_vector_setting(params, "rotation", "0, 0, 0"),
    )
    obj = bpy.context.object
    if obj is None:
        raise RuntimeError("Blender did not create the requested sphere.")
    obj.name = "Sphere" if index == 0 else f"Sphere{index + 1}"
    if str2bool(params.get("use_smooth"), default=True):
        _set_smooth(obj)
    if str2bool(params.get("subdivision_surface"), default=False):
        modifier = obj.modifiers.new("Subdivision", "SUBSURF")
        modifier.render_levels = 2
    _set_shadow_visibility(obj, str2bool(params.get("no_shadow"), default=False))
    if obj.name not in scene.objects:
        raise RuntimeError("Blender did not link the generated sphere to the scene.")
    return obj


def _import_custom_object(path: Path) -> list[Any]:
    before = {obj.as_pointer() for obj in bpy.data.objects}
    suffix = path.suffix.lower()
    if suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    elif suffix == ".ply":
        bpy.ops.wm.ply_import(filepath=str(path))
    elif suffix == ".stl":
        bpy.ops.wm.stl_import(filepath=str(path))
    elif suffix == ".fbx":
        operator = getattr(bpy.ops.import_scene, "fbx", None)
        if operator is None:
            raise RuntimeError(
                "FBX import requires Blender's FBX I/O extension to be installed and enabled."
            )
        operator(filepath=str(path))
    elif suffix == ".x3d":
        operator = getattr(bpy.ops.wm, "x3d_import", None)
        if operator is None:
            operator = getattr(getattr(bpy.ops, "import_scene", None), "x3d", None)
        if operator is None:
            raise RuntimeError(
                "X3D import is not available in Blender 5.2. Install an X3D I/O extension "
                "or convert the file to OBJ, FBX, PLY, or STL."
            )
        operator(filepath=str(path))
    else:
        raise ConfigError(f"Unsupported object format: {path.suffix}")

    imported = [obj for obj in bpy.data.objects if obj.as_pointer() not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"No mesh objects were imported from {path}.")
    return meshes


def _mesh_world_bounds(meshes: list[Any]) -> tuple[Vector, Vector]:
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in meshes
        for corner in obj.bound_box
    ]
    minimum = Vector(tuple(min(corner[axis] for corner in corners) for axis in range(3)))
    maximum = Vector(tuple(max(corner[axis] for corner in corners) for axis in range(3)))
    return minimum, maximum


def _set_custom_object(
    params: dict[str, str], path: Path, scene: Any
) -> tuple[Any, list[Any]]:
    meshes = _import_custom_object(path)
    original_matrices = [(obj, obj.matrix_world.copy()) for obj in meshes]
    minimum, maximum = _mesh_world_bounds(meshes)
    dimensions = maximum - minimum
    center = (minimum + maximum) / 2
    root = bpy.data.objects.new(path.stem, None)
    scene.collection.objects.link(root)
    if str2bool(params.get("geometry_to_origin"), default=False):
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')

    for mesh, original_matrix in original_matrices:
        mesh.parent = root
        mesh.matrix_parent_inverse = root.matrix_world.inverted()
        mesh.matrix_world = original_matrix

    maximum_dimension = _value(params, "max_dimension", "none")
    if maximum_dimension.lower() != "none":
        target = float(maximum_dimension)
        if target <= 0:
            raise ConfigError("object_custom.max_dimension must be positive or None.")
        current = max(dimensions)
        if current <= 0:
            raise ConfigError(f"Imported object has no measurable dimensions: {path}")
        root.scale = (target / current,) * 3
        print(f"set object {root} scale to {root.scale}")

    root.location = _vector_setting(params, "location", "0, 0, 0")
    root.rotation_euler = _vector_setting(params, "rotation", "0, 0, 0")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if str2bool(params.get("use_smooth"), default=False):
        for mesh in meshes:
            _set_smooth(mesh)
    disabled_shadow = str2bool(params.get("no_shadow"), default=False)
    for mesh in meshes:
        _set_shadow_visibility(mesh, disabled_shadow)

    return root, meshes


def _mesh_parts(root: Any) -> list[Any]:
    if root.type == "MESH":
        return [root]
    return [
        child
        for child in root.children_recursive
        if child.type == "MESH"
    ]


def _load_texture(path: Path, *, data_map: bool) -> Any:
    image = bpy.data.images.load(str(path), check_existing=True)
    if data_map:
        image.colorspace_settings.name = "Non-Color"
    return image


def _set_material(
    index: int,
    params: dict[str, str],
    meshes: list[Any],
    working_dir: Path,
    config_dir: Path,
) -> None:
    material = bpy.data.materials.new(f"Material{index}")
    nodes = material.node_tree.nodes
    shader = _get_node_by_blidname(nodes, "ShaderNodeBsdfPrincipled")
    output = _get_node_by_blidname(nodes, "ShaderNodeOutputMaterial")
    if shader is None:
        shader = nodes.new("ShaderNodeBsdfPrincipled")
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
    for link in list(material.node_tree.links):
        if link.to_node == output and link.to_socket.name == "Surface":
            material.node_tree.links.remove(link)
    material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    for key, value in params.items():
        if not value:
            continue
        if key == "load_uv":
            continue
        if key in _SCALAR_SHADER_KEYS:
            socket = _get_socket(
                shader, _SOCKET_ALIASES[key], setting=key
            )
            scalar = float(value)
            if socket.type == "RGBA":
                socket.default_value = (scalar, scalar, scalar, 1.0)
            elif socket.type == "VECTOR":
                socket.default_value = (scalar, scalar, scalar)
            else:
                socket.default_value = scalar
        elif key in {"base_color", "subsurface_color", "emission"}:
            aliases = _SOCKET_ALIASES[key]
            if key == "subsurface_color" and not any(
                shader.inputs.get(name) is not None for name in aliases
            ):
                if "base_color" not in params:
                    aliases = _SOCKET_ALIASES["base_color"]
                else:
                    warnings.warn(
                        "subsurface_color is not a Principled BSDF input in this "
                        "Blender version; base_color is already set, so it was ignored.",
                        stacklevel=2,
                    )
                    continue
            socket = _get_socket(shader, aliases, setting=key)
            socket.default_value = _linear_color(value, setting=key)
        elif key.endswith("_texture"):
            aliases = _TEXTURE_SOCKETS.get(key)
            if aliases is None:
                raise ConfigError(f"Unknown texture setting: {key}")
            image_path = resolve_asset(value, working_dir, config_dir)
            if not image_path.is_file():
                raise ConfigError(f"Texture file does not exist: {image_path}")
            texture = nodes.new("ShaderNodeTexImage")
            texture.image = _load_texture(
                image_path, data_map=(key != "color_texture")
            )

            use_uv = str2bool(params.get("load_uv"), default=False) and all(
                mesh.data.uv_layers.active is not None for mesh in meshes
            )
            coordinates = nodes.new("ShaderNodeTexCoord")
            coordinate_output = (
                coordinates.outputs["UV"]
                if use_uv
                else coordinates.outputs["Generated"]
            )
            material.node_tree.links.new(
                coordinate_output, texture.inputs["Vector"]
            )
            texture.interpolation = "Closest"
            if not use_uv:
                texture.projection = "SPHERE"

            target = _get_socket(shader, aliases, setting=key)
            if key == "color_texture":
                material.node_tree.links.new(texture.outputs["Color"], target)
            else:
                grayscale = nodes.new("ShaderNodeRGBToBW")
                material.node_tree.links.new(
                    texture.outputs["Color"], grayscale.inputs["Color"]
                )
                source = grayscale.outputs["Val"]
                if key in {"specular_texture", "ior_texture"}:
                    multiply = nodes.new("ShaderNodeMath")
                    multiply.operation = "MULTIPLY"
                    multiply.inputs[1].default_value = 10.0
                    material.node_tree.links.new(source, multiply.inputs[0])
                    source = multiply.outputs[0]
                material.node_tree.links.new(source, target)
        else:
            warnings.warn(
                f"Shader setting {key!r} is not supported and was ignored.",
                stacklevel=2,
            )

    for mesh in meshes:
        if mesh.type == "MESH":
            mesh.data.materials.clear()
            mesh.data.materials.append(material)


def _pose_matrix(angles: tuple[float, float, float]) -> Matrix:
    return Euler(tuple(-angle for angle in angles), "XYZ").to_matrix().to_4x4()


def _set_light_batch(
    batch: list[tuple[float, float, float, float | None, float]],
    light_objects: list[Any],
    model: str,
    view_delta: Matrix,
    sync_with_views: bool,
) -> None:
    for light_object, sample in zip(light_objects, batch):
        x, y, z, energy, size = sample
        if energy is not None and energy >= 0:
            light_object.data.energy = energy
        if model == "distant":
            light_object.data.angle = size
            orientation = Euler((x, y, z), "XYZ").to_matrix().to_4x4()
            if sync_with_views:
                orientation = view_delta @ orientation
            light_object.matrix_world = orientation
        else:
            light_object.data.shadow_soft_size = size
            position = Vector((x, y, z))
            if sync_with_views:
                position = view_delta.to_3x3() @ position
            light_object.location = position


def _set_lights(params: dict[str, str], scene: Any) -> tuple[list[Any], str]:
    model = _value(params, "model", "distant").lower()
    light_type = "SUN" if model == "distant" else "POINT"
    amount = int(_value(params, "amount", "1"))
    light_objects = []
    for index in range(amount):
        data = bpy.data.lights.new(f"Light{index + 1}", type=light_type)
        data.energy = float(_value(params, "energy", "1"))
        if light_type == "SUN":
            data.angle = float(_value(params, "SUN_angle", "0.00918"))
        else:
            data.shadow_soft_size = float(_value(params, "POINT_size", "0.25"))
        obj = bpy.data.objects.new(f"Light{index + 1}", data)
        scene.collection.objects.link(obj)
        light_objects.append(obj)
    return light_objects, light_type


def _intrinsic_matrix(camera: Any, scene: Any) -> list[float]:
    render = scene.render
    camera_data = camera.data
    scale = render.resolution_percentage / 100
    pixel_aspect = render.pixel_aspect_x / render.pixel_aspect_y
    focal = camera_data.lens
    alpha_u = focal * render.resolution_x * scale / camera_data.sensor_width
    alpha_v = (
        focal * render.resolution_y * scale * pixel_aspect / camera_data.sensor_height
    )
    center_x = render.resolution_x * scale / 2
    center_y = render.resolution_y * scale / 2
    return [alpha_u, 0, center_x, 0, alpha_v, center_y, 0, 0, 1]


def _write_info(
    directory: Path,
    filenames: list[str],
    light_type: str,
    light_values: list[list[tuple[float, float, float]]],
    camera: Any,
    object_roots: list[Any],
    scene: Any,
) -> None:
    section = "light rotations" if light_type == "SUN" else "light locations"
    with (directory / "filenames.ini").open("w", encoding="utf-8") as output:
        output.write("[filenames]\n")
        for index, filename in enumerate(filenames, start=1):
            output.write(f"{index:03d} = {filename}\n")
        output.write(f"\n[{section}]\n")
        for index, values in enumerate(light_values, start=1):
            formatted = "\t".join(
                f"{x:.5f}, {y:.5f}, {z:.5f}" for x, y, z in values
            )
            output.write(f"{index:03d} = {formatted}\n")
        loc = camera.location
        rot = camera.rotation_euler
        output.write("\n[info]\n")
        output.write(f"camera_location = {loc.x:.5f}, {loc.y:.5f}, {loc.z:.5f} [m]\n")
        output.write(f"camera_rotation = {rot.x:.5f}, {rot.y:.5f}, {rot.z:.5f} [rad]\n")
        output.write(f"camera_intrinsic = {_intrinsic_matrix(camera, scene)}\n")
        for root in object_roots:
            loc = root.location
            rot = root.rotation_euler
            output.write(
                f"{root.name}_location = {loc.x:.5f}, {loc.y:.5f}, {loc.z:.5f} [m]\n"
            )
            output.write(
                f"{root.name}_rotation = {rot.x:.5f}, {rot.y:.5f}, {rot.z:.5f} [rad]\n"
            )
            meshes = _mesh_parts(root)
            vertex_count = sum(len(mesh.data.vertices) for mesh in meshes)
            edge_count = sum(len(mesh.data.edges) for mesh in meshes)
            polygon_count = sum(len(mesh.data.polygons) for mesh in meshes)
            output.write(
                f"{root.name}_vertices = {vertex_count}\n"
                f"{root.name}_edges = {edge_count}\n"
                f"{root.name}_polygons = {polygon_count}\n"
            )


def _build_geometry_data(depth_values: Any, normal_values: Any) -> tuple[Any, ...]:
    import numpy as np

    normal_lengths = np.linalg.norm(normal_values, axis=2)
    valid_depth = np.isfinite(depth_values) & (depth_values < 1e9)
    mask = valid_depth.astype(np.uint8)
    mask_alt = (valid_depth & (normal_lengths >= 0.8)).astype(np.uint8)

    normalized_depth = np.zeros_like(depth_values, dtype=np.float32)
    if np.any(valid_depth):
        near = float(np.min(depth_values[valid_depth]))
        far = float(np.max(depth_values[valid_depth]))
        if far > near:
            normalized_depth[valid_depth] = (
                depth_values[valid_depth] - near
            ) / (far - near)
        normalized_depth[~valid_depth] = 1.0

    encoded_normals = np.clip((normal_values + 1.0) * 0.5, 0.0, 1.0)
    encoded_normals[~valid_depth] = 0.0
    encoded_normals_alt = np.clip(normal_values, 0.0, 1.0)
    encoded_normals_alt[~valid_depth] = 0.0
    return (
        normalized_depth,
        mask,
        mask_alt,
        encoded_normals,
        encoded_normals_alt,
    )


def _save_float_image(path: Path, rgba: Any, width: int, height: int) -> None:
    image = bpy.data.images.new(
        f"__render_data_{path.stem}", width=width, height=height,
        alpha=True, float_buffer=True, is_data=True,
    )
    try:
        image.pixels.foreach_set(rgba.reshape(-1))
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)


def _save_geometry_maps(
    directory: Path, depth_path: Path, normal_path: Path, scene: Any
) -> None:
    import numpy as np

    width = scene.render.resolution_x
    height = scene.render.resolution_y
    depth_pass = read_openexr_channels(depth_path)
    normal_pass = read_openexr_channels(normal_path)
    depth_channel = next(
        (values for name, values in depth_pass.items() if name.endswith(".V")),
        None,
    )
    normal_components = {
        name.rsplit(".", 1)[-1]: values
        for name, values in normal_pass.items()
    }
    if depth_channel is None or not {"X", "Y", "Z"}.issubset(normal_components):
        raise RuntimeError(
            "Blender compositor did not write the expected depth and normal passes."
        )
    depth_values = np.asarray(depth_channel, dtype=np.float32)
    normal_values = np.stack(
        [normal_components[axis] for axis in ("X", "Y", "Z")], axis=-1
    ).astype(np.float32, copy=False)
    if depth_values.shape != (height, width) or normal_values.shape != (
        height,
        width,
        3,
    ):
        raise RuntimeError(
            "Blender compositor pass resolution does not match the render resolution."
        )
    (
        normalized_depth,
        mask,
        mask_alt,
        encoded_normals,
        encoded_normals_alt,
    ) = _build_geometry_data(depth_values, normal_values)
    np.save(directory / "distance.npy", np.flipud(depth_values))
    np.save(directory / "mask.npy", np.flipud(mask))
    np.save(directory / "mask_alt.npy", np.flipud(mask_alt))
    np.save(directory / "depth.npy", np.flipud(normalized_depth))
    np.save(directory / "normals.npy", np.flipud(encoded_normals))
    np.save(directory / "normals_alt.npy", np.flipud(normal_values))

    depth_rgba = np.empty((height, width, 4), dtype=np.float32)
    depth_rgba[..., :3] = normalized_depth[..., None]
    depth_rgba[..., 3] = 1.0
    normal_rgba = np.ones((height, width, 4), dtype=np.float32)
    normal_rgba[..., :3] = encoded_normals
    normal_alt_rgba = np.ones((height, width, 4), dtype=np.float32)
    normal_alt_rgba[..., :3] = encoded_normals_alt
    _save_float_image(directory / "depth.png", depth_rgba[::-1], width, height)
    _save_float_image(directory / "normals.png", normal_rgba[::-1], width, height)
    _save_float_image(directory / "normals_alt.png", normal_alt_rgba[::-1], width, height)


def _save_exr(output_dir, pass_directory, frame_index=1):
    exr_path = Path(pass_directory.name)
    shutil.copy2(exr_path / "image.exr", output_dir / f"{frame_index:03d}.exr")
    if frame_index > 1:
        return
    shutil.copy2(exr_path / "depth.exr", output_dir / "depth.exr")
    shutil.copy2(exr_path / "normal.exr", output_dir / "normal.exr")


def _render_job(job: RenderJob) -> str:
    _require_blender()
    scene = bpy.context.scene
    _remove_scene_objects(scene)
    _configure_scene(scene, job.rendering)
    _configure_device(scene, job.rendering)
    world = _new_world(
        scene, job.rendering, job.working_dir, job.config_path.parent
    )
    camera = _set_camera(job.camera, scene)
    light_batches = create_light_directions(
        job.light, job.working_dir, job.config_path.parent
    )
    light_objects, light_type = _set_lights(job.light, scene)

    roots: list[Any] = []
    meshes_by_root: list[list[Any]] = []
    sphere_index = 0
    for object_name, params in zip(job.object_files, job.object_params):
        if object_name.lower() == "sphere":
            root = _set_sphere(params, sphere_index, scene)
            sphere_index += 1
            meshes = [root]
        else:
            path = resolve_asset(object_name, job.working_dir, job.config_path.parent)
            root, meshes = _set_custom_object(params, path, scene)
        roots.append(root)
        meshes_by_root.append(meshes)

    for index, (params, meshes) in enumerate(zip(job.shader_params, meshes_by_root)):
        _set_material(
            index, params, meshes, job.working_dir, job.config_path.parent
        )

    old_compositing_group = scene.compositing_node_group
    old_use_compositing = scene.render.use_compositing
    pass_directory = tempfile.TemporaryDirectory(prefix="blender_geometry_passes_")
    pass_group = bpy.data.node_groups.new(
        "__BlenderGeometryPasses", "CompositorNodeTree"
    )
    render_layers = pass_group.nodes.new("CompositorNodeRLayers")
    render_layers.scene = scene
    render_layers.layer = scene.view_layers[0].name
    pass_paths = {
        "Image": Path(pass_directory.name) / "image.exr",
        "Depth": Path(pass_directory.name) / "depth.exr",
        "Normal": Path(pass_directory.name) / "normal.exr",
    }
    pass_output_nodes = []
    for name, socket_type in (("Image", "VECTOR"), ("Depth", "FLOAT"), ("Normal", "VECTOR")):
        output = pass_group.nodes.new("CompositorNodeOutputFile")
        output.file_output_items.clear()
        output.file_output_items.new(socket_type, name)
        output.directory = pass_directory.name
        output.file_name = name.lower()
        output.format.file_format = "OPEN_EXR_MULTILAYER"
        output.format.color_depth = "32"
        output.format.exr_codec = "NONE"
        output.save_as_render = False
        pass_group.links.new(render_layers.outputs[name], output.inputs[name])
        pass_output_nodes.append(output)
    scene.compositing_node_group = pass_group
    scene.render.use_compositing = True

    try:
        object_name = "_".join(root.name for root in roots)
        output_root = job.output_dir / object_name
        output_root.mkdir(parents=True, exist_ok=True)
        source_matrices = [(root, root.matrix_world.copy()) for root in roots]
        object_views = create_object_directions(
            job.object_global, job.working_dir, job.config_path.parent
        )
        multiple_views = str2bool(
            job.object_global.get("enable_multiple_views"), default=False
        )
        sync_lights = multiple_views and str2bool(
            job.light.get("synchronize_with_views"), default=False
        )
        sync_hdri = multiple_views and str2bool(
            job.rendering.get("synchronize_with_views"), default=False
        )
        hdri_mapping = world.node_tree.nodes.get("Render HDRI Mapping")
        for view_index, angles in enumerate(object_views, start=1):
            view_delta = _pose_matrix(angles)
            for root, source_matrix in source_matrices:
                root.matrix_world = view_delta @ source_matrix
            output_dir = (
                output_root / f"view_{view_index:03d}"
                if multiple_views
                else output_root
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            filenames: list[str] = []
            recorded_lights: list[list[tuple[float, float, float]]] = []

            if hdri_mapping is not None and sync_hdri:
                offset = float(job.rendering.get("hdri_offset", "0"))
                hdri_mapping.inputs["Rotation"].default_value = (
                    math.pi / 2 - angles[0],
                    -angles[2],
                    offset - angles[1],
                )

            for frame_index, batch in enumerate(light_batches, start=1):
                for output in pass_output_nodes:
                    output.mute = frame_index < len(light_batches)
                _set_light_batch(
                    batch, light_objects, job.light.get("model", "distant").lower(),
                    view_delta, sync_lights,
                )
                bpy.context.view_layer.update()
                bpy.ops.render.render()
                filepath = output_dir / f"{frame_index:03d}.blend"
                bpy.ops.wm.save_as_mainfile(filepath=str(filepath), copy=True)
                filepath = output_dir / f"{frame_index:03d}.png"
                bpy.data.images["Render Result"].save_render(filepath=str(filepath))
                filenames.append(filepath.name)
                recorded_lights.append(
                    [
                        tuple(float(value) for value in light.matrix_world.translation)
                        if light_type == "POINT"
                        else tuple(float(value) for value in light.rotation_euler)
                        for light in light_objects
                    ]
                )
                if str2bool(job.rendering.get("save_exr"), default=False):
                    _save_exr(output_dir, pass_directory, frame_index=frame_index)
            _save_geometry_maps(
                output_dir, pass_paths["Depth"], pass_paths["Normal"], scene
            )
            _write_info(
                output_dir, filenames, light_type, recorded_lights, camera, roots, scene,
            )

        shutil.copy2(job.config_path, output_root / "save.ini")
        return object_name
    finally:
        scene.compositing_node_group = old_compositing_group
        scene.render.use_compositing = old_use_compositing
        bpy.data.node_groups.remove(pass_group)
        pass_directory.cleanup()


def _get_node_by_blidname(nodes, bl_idname):
    return next((n for n in nodes if n.bl_idname == bl_idname), None)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    elif any(argument.lower().endswith(".ini") for argument in argv):
        argv = [
            argument
            for argument in argv
            if argument.lower().endswith(".ini")
            or argument == "--validate-only"
        ]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate configuration and referenced assets without rendering",
    )
    parser.add_argument("configs", nargs="+", type=Path, help="INI configuration files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        jobs = [load_job(path) for path in args.configs]
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    for job in jobs:
        print(f"Validated {job.config_path} ({len(job.object_files)} object(s)).")
    if args.validate_only:
        return 0
    if bpy is None:
        print(
            "Rendering requires Blender. Use --validate-only with system Python.",
            file=sys.stderr,
        )
        return 2

    for job in jobs:
        started = time.perf_counter()
        object_name = _render_job(job)
        elapsed = time.perf_counter() - started
        output_dir = job.output_dir / object_name
        (output_dir / "time.txt").write_text(
            f"elapsed_time: {elapsed:.5f} [sec]\n", encoding="utf-8"
        )
        print(f"Rendered {object_name} in {elapsed:.2f} seconds.")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
    raise SystemExit(exit_code)
