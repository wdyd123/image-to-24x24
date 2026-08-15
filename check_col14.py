"""诊断：检查第14列的像素数据和点击坐标"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ark_draw import group_pixels_by_color, ArkDrawer, PALETTE_COLORS, PALETTE_TOP_ROWS, PALETTE_COLS

data = json.load(open(r'C:\Users\12280\Desktop\24x24\方舟数据\塔露拉.json', encoding='utf-8'))
pixels = data['pixels']
size = data['size']
groups = group_pixels_by_color(pixels, size)
d = ArkDrawer(groups, 0, 0)

# 检查第14列 (用户说的14, 可能是0-indexed=13 或 1-indexed=14)
for col in [13, 14]:
    print(f"\n{'='*60}")
    print(f"检查列 {col} (0-indexed)")
    print(f"{'='*60}")

    # 该列所有像素
    col_pixels = [(idx, pixels[idx]) for idx in range(len(pixels)) if idx % size == col]
    print(f"像素数: {len(col_pixels)}")

    # 该列像素的颜色分布
    color_counts = {}
    for idx, rgb in col_pixels:
        key = tuple(rgb)
        if key not in color_counts:
            color_counts[key] = []
        color_counts[key].append(idx // size)  # y坐标

    for rgb, ys in sorted(color_counts.items()):
        hex_c = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        print(f"  {hex_c}: y={ys}")

    # 该列像素在 color_groups 中的分布
    print(f"\n在 color_groups 中的分布:")
    for ci in sorted(groups.keys()):
        col_in_group = [(x, y) for (x, y) in groups[ci] if x == col]
        if col_in_group:
            phase = "TOP" if ci < PALETTE_TOP_ROWS * PALETTE_COLS else "BOTTOM"
            pal_rgb = PALETTE_COLORS[ci]
            hex_c = f"#{pal_rgb[0]:02X}{pal_rgb[1]:02X}{pal_rgb[2]:02X}"
            print(f"  idx={ci:2d} [{phase:6s}] {hex_c}: {len(col_in_group)} px, y={[y for x,y in col_in_group]}")

    # 点击坐标
    print(f"\n点击坐标 (窗口相对):")
    for gy in [0, 12, 23]:
        pos = d.grid_click_pos(col, gy)
        print(f"  grid({col},{gy}) = {pos}")

# 汇总：每列有多少像素被包含在 groups 中
print(f"\n{'='*60}")
print("每列像素覆盖统计:")
print(f"{'='*60}")
for col in range(24):
    total = sum(1 for positions in groups.values() for (x, y) in positions if x == col)
    print(f"  col {col:2d}: {total:3d} px", end="")
    if total == 0:
        print("  ← 空列！", end="")
    print()
