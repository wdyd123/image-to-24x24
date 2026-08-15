"""
诊断工具：检查导出的 JSON 数据与调色板匹配结果
用法：python diagnose_export.py pixels.json
"""
import json
import sys
import os
import numpy as np

# 加载调色板
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from image_to_24x24 import PALETTE_COLORS

def weighted_dist(a, b):
    """加权 RGB 距离"""
    w = np.array([0.299, 0.587, 0.114])
    d = np.array(a, dtype=float) - np.array(b, dtype=float)
    return float(np.sqrt(np.sum(w * d ** 2)))

def match_index(rgb):
    palette = np.array(PALETTE_COLORS, dtype=np.float32)
    pixel = np.array(rgb, dtype=np.float32)
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    diff = pixel[np.newaxis, :] - palette
    dist_sq = np.sum(weights * diff ** 2, axis=1)
    return int(np.argmin(dist_sq))

def main():
    if len(sys.argv) < 2:
        print("用法: python diagnose_export.py <pixels.json>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)

    pixels = data["pixels"]
    size = data["size"]
    print(f"文件: {sys.argv[1]}")
    print(f"尺寸: {size}x{size}, 像素数: {len(pixels)}")

    # 统计唯一颜色
    unique_colors = {}
    for idx, rgb in enumerate(pixels):
        key = tuple(rgb)
        if key not in unique_colors:
            unique_colors[key] = []
        y, x = divmod(idx, size)
        unique_colors[key].append((x, y))

    print(f"\n唯一颜色数: {len(unique_colors)}")
    print(f"调色板颜色数: {len(PALETTE_COLORS)}")

    # 检查每个颜色是否在调色板中
    print(f"\n{'='*80}")
    print(f"{'JSON中的颜色':<20} {'最近调色板索引':<8} {'调色板颜色':<20} {'距离':<8} {'匹配?'}")
    print(f"{'='*80}")

    mismatches = 0
    for rgb, positions in sorted(unique_colors.items()):
        hex_c = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        idx = match_index(rgb)
        pal_rgb = PALETTE_COLORS[idx]
        pal_hex = f"#{pal_rgb[0]:02X}{pal_rgb[1]:02X}{pal_rgb[2]:02X}"
        dist = weighted_dist(rgb, pal_rgb)
        match = "✓" if dist < 1.0 else "✗ MISMATCH"
        if dist >= 1.0:
            mismatches += 1

        count = len(positions)
        print(f"{hex_c} ({count:3d}px)  → idx={idx:2d}  {pal_hex}  dist={dist:.2f}  {match}")

    print(f"\n{'='*80}")
    if mismatches == 0:
        print("✓ 所有颜色精确匹配调色板 — 导出正确")
    else:
        print(f"✗ {mismatches} 种颜色与调色板不匹配 — 导出有问题！")
        print("  可能原因：导出时调色板限制未开启，或 PALETTE_COLORS 不准确")

    # 检查 ark_draw 的匹配是否一致
    print(f"\n{'='*80}")
    print("ark_draw.py 的颜色分组结果：")
    print(f"{'='*80}")

    # 模拟 group_pixels_by_color
    groups = {}
    for idx, rgb in enumerate(pixels):
        y, x = divmod(idx, size)
        ci = match_index(tuple(rgb))
        if ci not in groups:
            groups[ci] = []
        groups[ci].append((x, y))

    for ci in sorted(groups.keys()):
        pal_rgb = PALETTE_COLORS[ci]
        hex_c = f"#{pal_rgb[0]:02X}{pal_rgb[1]:02X}{pal_rgb[2]:02X}"
        row = ci // 4
        col = ci % 4
        print(f"  色板位置[{ci:2d}] (row={row},col={col}) {hex_c}: {len(groups[ci])} px")

    # 前5行 vs 后5行分布
    top_count = sum(len(v) for ci, v in groups.items() if ci // 4 < 5)
    bot_count = sum(len(v) for ci, v in groups.items() if ci // 4 >= 5)
    print(f"\n  TOP 区 (idx 0-19): {top_count} px")
    print(f"  BOTTOM 区 (idx 20-39): {bot_count} px")

if __name__ == "__main__":
    main()
