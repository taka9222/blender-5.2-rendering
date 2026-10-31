import configparser
import numpy as np
from PIL import Image
from pathlib import Path
from matplotlib import pyplot as plt
import matplotlib.cm as cm


OUTPUT_PATH = Path("output_dir/sphere")


def parse_meta_file(file_path):
    config = configparser.ConfigParser()
    config.optionxform = str
    with open(file_path, "r", encoding="utf-8") as f:
        config.read_file(f)
    image_paths = []
    for key, value in config["filenames"].items():
        image_paths.append(value)
    rotations = []
    for key, value in config["light rotations"].items():
        angles = [float(x) for x in value.split(",")]
        rotations.append(angles)
    return image_paths, np.array(rotations)


def rotations_to_directions(light_rotations):
    light_directions = []
    init_dir = np.array([0.0, 0.0, 1.0])
    for rot in light_rotations:
        x, y, z = rot
        R_x = np.array([[1, 0, 0],
                        [0, np.cos(x), -np.sin(x)],
                        [0, np.sin(x), np.cos(x)]])
        R_y = np.array([[np.cos(y), 0, np.sin(y)],
                        [0, 1, 0],
                        [-np.sin(y), 0, np.cos(y)]])
        R_z = np.array([[np.cos(z), -np.sin(z), 0],
                        [np.sin(z), np.cos(z), 0],
                        [0, 0, 1]])
        R = np.dot(R_z, np.dot(R_y, R_x))
        dir_rotated = np.dot(R, init_dir)
        light_directions.append(dir_rotated)
    return np.array(light_directions)


def photometric_stereo(image_paths, L):
    images = []
    for path in image_paths:
        with Image.open(OUTPUT_PATH / path) as img:
            gray_img = img.convert("L")
            images.append(np.array(gray_img, dtype=np.float32) / 255.0)
    I_imgs = np.array(images)
    N, H, W = I_imgs.shape
    I = I_imgs.reshape(N, -1)
    L = L / np.linalg.norm(L, axis=1, keepdims=True)
    L_inv = np.linalg.pinv(L)
    G = np.dot(L_inv, I)
    albedo_flat = np.linalg.norm(G, axis=0)
    normals_flat = G / (albedo_flat + 1e-6)
    albedo = albedo_flat.reshape(H, W)
    normals = normals_flat.T.reshape(H, W, 3)
    return normals, albedo


def save_normals(normals, filename="normals.png"):
    vis_normals = (normals + 1.0) / 2.0 * 255.0
    vis_normals = np.clip(vis_normals, 0, 255).astype(np.uint8)
    Image.fromarray(vis_normals).save(filename)


def save_normals_quiver(normals, filename="normals_quiver.png", step=6):
    H, W, _ = normals.shape
    X, Y = np.meshgrid(np.arange(0, W, step), np.arange(0, H, step))
    U = normals[::step, ::step, 0]  # X grad
    V = -normals[::step, ::step, 1]  # Y grad
    tilt_magnitude = np.sqrt(U**2 + V**2)
    plt.figure(figsize=(6, 4), dpi=100)
    Q = plt.quiver(X, Y, U, V, tilt_magnitude, cmap=cm.jet,
                   angles="xy", scale_units="xy",
                   scale=0.03, width=0.003, headwidth=1, headlength=2)
    plt.xlim(-step, W + step)
    plt.ylim(H + step, -step)
    plt.gca().set_aspect("equal", adjustable="box")
    plt.axis("off")
    plt.savefig(filename, bbox_inches="tight", pad_inches=0, dpi=200, facecolor=plt.gca().get_facecolor())
    plt.close()


def MAngE(Nest, Ngt, mask=None, filename="./MAngE.png"):
    if mask is None:
        mask = Ngt[:, :, 2] > 0.0
        norm = np.linalg.norm(Ngt, axis=2)
        is_unit = np.isclose(norm, 1.0, atol=0.1)
        mssk = mask & is_unit
    else:
        mask = mask / np.max(mask)
        mask = np.where(mask > 0.5, True, False)
    dot_product = np.sum(Nest * Ngt, axis=2)
    dot_product = np.clip(dot_product, -1.0, 1.0)
    ange = np.degrees(np.arccos(dot_product))
    ange = np.where(mask, ange, np.nan)
    masked = ange[mask]
    print(f"[MAngE deg] Avg={np.mean(masked):.3f} Mean={np.median(masked):.3f}")
    plt.imshow(ange, cmap="jet", vmax=30, vmin=0)
    plt.colorbar()
    plt.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()


if __name__ == "__main__":
    RES_DIR = Path("tests/PS_result")
    RES_DIR.mkdir(parents=True, exist_ok=True)

    img_files, R = parse_meta_file(OUTPUT_PATH / "filenames.ini")
    L = rotations_to_directions(R)
    print("L head (top 5):")
    print(L[:5])

    N, albedo = photometric_stereo(img_files, L)

    save_normals(N, RES_DIR / "normals.png")
    save_normals_quiver(N, RES_DIR / "normals_quiver.png", step=8)

    vis_albedo = np.clip(albedo * 255.0, 0, 255).astype(np.uint8)
    Image.fromarray(vis_albedo).save(RES_DIR / "albedo.png")

    MAngE(N, np.load(OUTPUT_PATH / "normals_alt.npy")[::-1],
          mask=np.load(OUTPUT_PATH / "mask.npy")[::-1],
          filename=RES_DIR / "MAngE.png")
    print(f"PS result can be viewed in {str(RES_DIR)}")
