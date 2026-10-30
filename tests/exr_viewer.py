import array
import os
import Imath
import matplotlib.pyplot as plt
import numpy as np
import OpenEXR


def tonemap(
    hdr_linear_img: np.ndarray, 
    max_luminance_nits: float = 1000.0, 
    paper_white_nits: float = 203.0
) -> np.ndarray:
    """
    BlenderのLinear EXR等から読み込んだNumPy配列に対して、
    ニト換算ベースの拡張Reinhardトーンマッピングを適用する関数。

    Parameters:
    -----------
    hdr_linear_img : np.ndarray
        入力するLinear-RGB画像。形状は (H, W, 3) または (H, W, 4)。
        Blenderの標準出力（1.0 = ディフューズ白）の相対輝度スケールを想定。
    max_luminance_nits : float
        HDRシーンの想定ピーク輝度（ニト）。太陽や光源をどれくらい白飛びさせずに残すかを調整。
    paper_white_nits : float
        Blender内の基準白(1.0)を何ニトとして扱うか（BT.2408基準の 203.0 nits を推奨）。

    Returns:
    --------
    np.ndarray
        トーンマップされた [0.0, 1.0] 範囲の Linear-SDR 画像配列（入力と同じ形状・チャンネル数）。
    """
    # チャンネル数の確認とアルファチャンネルの分離
    has_alpha = hdr_linear_img.shape[-1] == 4
    if has_alpha:
        alpha = hdr_linear_img[..., 3:4]
        rgb = hdr_linear_img[..., :3].copy()
    else:
        rgb = hdr_linear_img.copy()

    # 負のノイズやエラー値を0にクリップ
    rgb = np.maximum(rgb, 0.0)

    # 1. Blenderの相対輝度（1.0＝白）を、内部的に絶対輝度（nits）にスケーリング
    rgb_nits = rgb * paper_white_nits

    # 2. 輝度（Luminance）の計算 (RGB順：BT.709/sRGB用の係数)
    coefficients = np.array([0.2126, 0.7152, 0.0722])
    luminance = np.dot(rgb_nits, coefficients)[..., np.newaxis]
    luminance = np.maximum(luminance, 1e-6)  # 0除算を防止

    # 3. paper_whiteを基準とした相対スケール（1.0＝白）に再変換
    lum_rel = luminance / paper_white_nits
    max_lum_rel = max_luminance_nits / paper_white_nits

    # 4. 拡張Reinhardトーンマッピングオペレータの適用
    # ピーク輝度（max_lum_rel）が正確に1.0（SDRの最大値）にマッピングされる曲線
    lum_mapped = (lum_rel * (1.0 + (lum_rel / (max_lum_rel ** 2)))) / (1.0 + lum_rel)

    # 5. 元の色度（色合い）を維持したまま、トーンマップ後の輝度比率を各チャンネルに再適用
    sdr_linear = rgb_nits * (lum_mapped / luminance)
    sdr_linear = np.clip(sdr_linear, 0.0, 1.0)

    # アルファチャンネルが存在した場合は、結合して返す
    if has_alpha:
        return np.concatenate([sdr_linear, alpha], axis=-1)
    
    return sdr_linear


filePath = "output_dir/Sphere/001.exr"

pt = Imath.PixelType(Imath.PixelType.FLOAT)
img_exr = OpenEXR.InputFile(filePath)
header = img_exr.header()

dw = header["dataWindow"]
width = dw.max.x - dw.min.x + 1
height = dw.max.y - dw.min.y + 1
size = (width, height)
print(f"Image size: {size}")

channels = header["channels"].keys()
print(f"{channels=}")

if "Depth.V" in channels:
    (v_str,) = img_exr.channels(["Depth.V"], pt)
    gray = np.array(array.array("f", v_str))
    img = gray.reshape(height, width)
    img = np.where(img > 1000, np.nan, img)

elif "Normal.X" in channels:
    x_str, y_str, z_str = img_exr.channels(["Normal.X", "Normal.Y", "Normal.Z"], pt)
    red = np.frombuffer(x_str, dtype=np.float32)
    green = np.frombuffer(y_str, dtype=np.float32)
    blue = np.frombuffer(z_str, dtype=np.float32)
    img = np.stack([red, green, blue], axis=-1).reshape(height, width, 3)

else:
    x_str, y_str, z_str = img_exr.channels(["Image.X", "Image.Y", "Image.Z"], pt)
    red = np.frombuffer(x_str, dtype=np.float32)
    green = np.frombuffer(y_str, dtype=np.float32)
    blue = np.frombuffer(z_str, dtype=np.float32)
    img = np.stack([red, green, blue], axis=-1).reshape(height, width, 3)


plt.figure(dpi=200)
if img.ndim == 2:
    plt.imshow(img, cmap="gray")
    plt.colorbar()
else:
    plt.imshow(tonemap(img, max_luminance_nits=700, paper_white_nits=130))
plt.show()
