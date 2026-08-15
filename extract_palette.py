"""
调色板颜色提取器
从调色板图片中自动识别每个色块的精确 RGB 值。
用法：运行后选择调色板图片，或拖拽图片到窗口。
"""

import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import numpy as np
import sys
import ctypes

# ── Windows 高 DPI 感知 ──
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

# ── 背景检测容差（与背景色的最小距离，低于此值视为背景） ──
_BG_DISTANCE_THRESHOLD = 25


def extract_palette_colors(img: Image.Image, min_area_ratio: float = 0.002) -> list:
    """
    从调色板图片中提取色块颜色。

    原理：
    1. 从图片四角采样自动检测背景色
    2. 计算每个像素与背景色的距离，低于阈值的视为背景
    3. 用连通域检测找到独立的色块
    4. 取每个色块中心区域的平均颜色

    返回: [(R, G, B), ...] 按从上到下、从左到右排列
    """
    img = img.convert("RGB")
    arr = np.array(img, dtype=np.float64)
    h, w, _ = arr.shape

    # ── Step 1: 自动检测背景色（取图片边缘像素的中位数） ──
    edge_pixels = np.concatenate([
        arr[0, :, :],        # 顶行
        arr[-1, :, :],       # 底行
        arr[:, 0, :],        # 左列
        arr[:, -1, :],       # 右列
    ], axis=0)
    bg_color = np.median(edge_pixels, axis=0)

    # ── Step 2: 前景掩码（与背景距离 > 阈值） ──
    diff = arr - bg_color
    dist = np.sqrt(np.sum(diff ** 2, axis=2))
    mask = dist > _BG_DISTANCE_THRESHOLD

    from scipy.ndimage import label, find_objects
    labeled, num_features = label(mask)

    if num_features == 0:
        return []

    # ── Step 3: 分析每个连通域（含粘连拆分） ──
    total_pixels = h * w
    min_area = total_pixels * min_area_ratio  # 最小色块面积

    regions = find_objects(labeled)
    arr_uint8 = np.array(img.convert("RGB"))  # 用于采样颜色

    # 第一轮：收集所有合格区域及其面积
    raw_regions = []
    for i, region in enumerate(regions):
        if region is None:
            continue
        label_id = i + 1
        r_slice, c_slice = region
        sub_mask = labeled[r_slice, c_slice] == label_id
        area = int(sub_mask.sum())
        if area >= min_area:
            raw_regions.append({
                "label_id": label_id, "r": r_slice, "c": c_slice,
                "mask": sub_mask, "area": area,
            })

    if not raw_regions:
        return []

    # 计算中位面积，用于检测粘连
    areas_sorted = sorted(r["area"] for r in raw_regions)
    median_area = areas_sorted[len(areas_sorted) // 2]

    swatches = []
    for reg in raw_regions:
        r_s, c_s = reg["r"], reg["c"]
        rh = r_s.stop - r_s.start
        rw = c_s.stop - c_s.start

        if reg["area"] > median_area * 1.5:
            # 粘连区域：按长轴等分为若干子块
            n_splits = max(2, round(reg["area"] / median_area))
            if rw >= rh:  # 水平拆分
                step = rw / n_splits
                for k in range(n_splits):
                    c0 = int(c_s.start + k * step)
                    c1 = int(c_s.start + (k + 1) * step) if k < n_splits - 1 else c_s.stop
                    sub_px = arr_uint8[r_s.start:r_s.stop, c0:c1].reshape(-1, 3)
                    if sub_px.size > 0:
                        avg = tuple(int(v) for v in sub_px.mean(axis=0).round().astype(int))
                        swatches.append({"color": avg,
                                          "center_y": (r_s.start + r_s.stop) / 2,
                                          "center_x": (c0 + c1) / 2,
                                          "area": reg["area"] // n_splits})
            else:  # 垂直拆分
                step = rh / n_splits
                for k in range(n_splits):
                    r0 = int(r_s.start + k * step)
                    r1 = int(r_s.start + (k + 1) * step) if k < n_splits - 1 else r_s.stop
                    sub_px = arr_uint8[r0:r1, c_s.start:c_s.stop].reshape(-1, 3)
                    if sub_px.size > 0:
                        avg = tuple(int(v) for v in sub_px.mean(axis=0).round().astype(int))
                        swatches.append({"color": avg,
                                          "center_y": (r0 + r1) / 2,
                                          "center_x": (c_s.start + c_s.stop) / 2,
                                          "area": reg["area"] // n_splits})
        else:
            # 正常区域：取中心 40% 区域的平均色
            margin_r = max(int(rh * 0.3), 1)
            margin_c = max(int(rw * 0.3), 1)
            cr = slice(r_s.start + margin_r, r_s.stop - margin_r)
            cc = slice(c_s.start + margin_c, c_s.stop - margin_c)
            cmask = labeled[cr, cc] == reg["label_id"]
            if cmask.sum() < 10:
                cr, cc = r_s, c_s
                cmask = labeled[cr, cc] == reg["label_id"]
            center_pixels = arr_uint8[cr, cc][cmask]
            if center_pixels.size == 0:
                center_pixels = arr_uint8[r_s.start:r_s.stop, c_s.start:c_s.stop].reshape(-1, 3)
            avg_color = center_pixels.mean(axis=0).round().astype(int)
            swatches.append({
                "color": tuple(int(v) for v in avg_color),
                "center_y": (r_s.start + r_s.stop) / 2,
                "center_x": (c_s.start + c_s.stop) / 2,
                "area": reg["area"],
            })

    # ── Step 4: 按从上到下、从左到右排序 ──
    if not swatches:
        return []

    # 先按 Y 聚类为行（容差 = 图像高度的 5%）
    row_threshold = h * 0.05
    swatches.sort(key=lambda s: s["center_y"])

    rows = []
    current_row = [swatches[0]]
    for s in swatches[1:]:
        if s["center_y"] - current_row[0]["center_y"] < row_threshold:
            current_row.append(s)
        else:
            rows.append(current_row)
            current_row = [s]
    rows.append(current_row)

    # 每行内按 X 排序
    result = []
    for row in rows:
        row.sort(key=lambda s: s["center_x"])
        for s in row:
            result.append(s["color"])

    return result


class PaletteExtractorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("调色板颜色提取器")
        self.geometry("900x700")
        self.configure(bg="#2b2b2b")
        self.minsize(700, 500)

        self._photo = None
        self._build_ui()

    def _build_ui(self):
        # 顶部工具栏
        toolbar = tk.Frame(self, bg="#2b2b2b", pady=8)
        toolbar.pack(fill=tk.X, padx=12)

        tk.Button(toolbar, text="选择图片", command=self._open_file,
                  bg="#404040", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        tk.Button(toolbar, text="复制颜色列表", command=self._copy_results,
                  bg="#404040", fg="white", relief=tk.FLAT, padx=12, pady=4,
                  font=("Microsoft YaHei", 10)).pack(side=tk.RIGHT)

        self.status_var = tk.StringVar(value="请选择调色板图片")
        tk.Label(toolbar, textvariable=self.status_var, bg="#2b2b2b",
                 fg="#888888", font=("Microsoft YaHei", 9)).pack(side=tk.LEFT, padx=12)

        # 主区域：上下分栏
        paned = tk.PanedWindow(self, orient=tk.VERTICAL, bg="#333333", sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # 上方 - 图片预览
        self.preview_frame = tk.LabelFrame(paned, text="图片预览", bg="#2b2b2b",
                                           fg="#888888", font=("Microsoft YaHei", 9))
        paned.add(self.preview_frame, height=300)
        self.preview_canvas = tk.Canvas(self.preview_frame, bg="#1e1e1e",
                                        highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # 下方 - 颜色结果
        result_frame = tk.LabelFrame(paned, text="提取结果", bg="#2b2b2b",
                                     fg="#888888", font=("Microsoft YaHei", 9))
        paned.add(result_frame, height=350)

        # 颜色网格画布
        self.grid_frame = tk.Frame(result_frame, bg="#2b2b2b")
        self.grid_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # 滚动文本框显示代码
        self.code_text = tk.Text(result_frame, bg="#1e1e1e", fg="#cccccc",
                                 font=("Consolas", 9), height=8, relief=tk.FLAT,
                                 insertbackground="white")
        self.code_text.pack(fill=tk.X, padx=8, pady=(0, 8))

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="选择调色板图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                       ("所有文件", "*.*")])
        if not path:
            return
        self._process_image(path)

    def _process_image(self, path):
        try:
            img = Image.open(path).convert("RGB")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开图片:\n{e}")
            return

        # 显示预览
        self._show_preview(img)

        # 提取颜色
        colors = extract_palette_colors(img)

        if not colors:
            messagebox.showwarning("未检测到色块", "未能从图片中识别出色块，请确认图片是调色板格式。")
            self.status_var.set("未检测到色块")
            return

        self._extracted_colors = colors
        self._show_results(colors)
        self.status_var.set(f"已识别 {len(colors)} 种颜色")

    def _show_preview(self, img):
        canvas = self.preview_canvas
        canvas.update_idletasks()
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 10:
            cw, ch = 800, 300

        w, h = img.size
        scale = min(cw / w, ch / h, 2.0)
        dw, dh = int(w * scale), int(h * scale)
        resized = img.resize((dw, dh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)

        canvas.delete("all")
        canvas.create_image(cw // 2, ch // 2, anchor=tk.CENTER, image=self._photo)

    def _show_results(self, colors):
        # 清除旧内容
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.code_text.delete("1.0", tk.END)

        # 计算网格列数（每行最多 8 个）
        cols = min(8, len(colors))
        rows = (len(colors) + cols - 1) // cols

        swatch_size = 40
        label_height = 20

        for idx, color in enumerate(colors):
            r, g, b = color
            hex_code = f"#{r:02X}{g:02X}{b:02X}"
            row = idx // cols
            col = idx % cols

            # 色块
            frame = tk.Frame(self.grid_frame, bg="#2b2b2b")
            frame.grid(row=row * 2, column=col, padx=3, pady=(6, 0))

            swatch = tk.Canvas(frame, width=swatch_size, height=swatch_size,
                               bg=hex_code, highlightthickness=1,
                               highlightbackground="#555555")
            swatch.pack()

            # 标签
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            tk.Label(frame, text=hex_code, fg="#cccccc", bg="#2b2b2b",
                     font=("Consolas", 7)).pack()

            # 序号
            tk.Label(frame, text=f"[{idx}]", fg="#666666", bg="#2b2b2b",
                     font=("Consolas", 7)).pack()

        # 生成 Python 代码
        code_lines = ["# 调色板颜色（自动提取）", "PALETTE_COLORS = ["]
        for i, (r, g, b) in enumerate(colors):
            hex_code = f"#{r:02X}{g:02X}{b:02X}"
            comma = "," if i < len(colors) - 1 else ""
            code_lines.append(f"    ({r}, {g}, {b}),{comma}  # {hex_code}")
        code_lines.append("]")

        code = "\n".join(code_lines)
        self.code_text.insert("1.0", code)
        self._last_code = code

    def _copy_results(self):
        if not hasattr(self, '_last_code'):
            messagebox.showinfo("提示", "请先提取颜色")
            return
        self.clipboard_clear()
        self.clipboard_append(self._last_code)
        self.status_var.set("已复制到剪贴板")


if __name__ == "__main__":
    app = PaletteExtractorApp()
    app.mainloop()
