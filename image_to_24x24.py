"""
24x24 像素图像转换器
- 通过文件资源管理器选择正方形图片
- 缩放为 24x24 像素
- 显示预览图（放大）和每个像素的颜色代码
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import os
import sys
import ctypes

# ── Windows 高 DPI 感知（必须在创建任何 UI 之前调用） ──
if sys.platform == "win32":
    try:
        # Per-Monitor DPI Aware (Win 8.1+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            # System DPI Aware (Vista+)
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

PIXEL_SIZE = 24          # 目标像素数
PREVIEW_SCALE = 16       # 预览放大倍数
CELL_SIZE = 28           # 颜色网格中每格像素大小


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("24×24 像素图像转换器")
        self.geometry("1200x800")
        self.minsize(900, 600)

        # 获取实际 DPI 缩放因子
        self.dpi_scale = self.tk.call("tk", "scaling") / 72.0
        if self.dpi_scale < 1.0:
            self.dpi_scale = 1.0

        self.pixels = []          # 24x24 RGB 列表
        self.hex_codes = []       # 24x24 HEX 列表
        self.preview_photo = None  # 原图 PhotoImage（适配画布大小）
        self._orig_w = 0          # 原图尺寸
        self._orig_h = 0
        self._preview_offset_x = 0  # 原图在画布中的偏移
        self._preview_offset_y = 0
        self._preview_draw_w = 0    # 原图在画布中的绘制尺寸
        self._zoom = 1.0            # 用户缩放倍率（基于适应画布的基准）
        self._base_scale = 1.0      # 适应画布的基准缩放
        self._preview_draw_h = 0

        # 网格布局参数（供鼠标事件使用）
        self._grid_margin_left = 0
        self._grid_margin_top = 0
        self._grid_cell = 0

        # 悬浮提示窗口
        self._tooltip = tk.Toplevel(self)
        self._tooltip.overrideredirect(True)       # 无边框
        self._tooltip.attributes("-topmost", True)  # 置顶
        self._tooltip.withdraw()                    # 默认隐藏
        self._tooltip.configure(bg="#303030")

        self._tip_label_hex = tk.Label(
            self._tooltip, text="", fg="#FFFFFF", bg="#303030",
            font=("Consolas", 10, "bold"), padx=6, pady=2,
        )
        self._tip_label_hex.pack(anchor=tk.W)
        self._tip_label_rgb = tk.Label(
            self._tooltip, text="", fg="#CCCCCC", bg="#303030",
            font=("Consolas", 9), padx=6, pady=0,
        )
        self._tip_label_rgb.pack(anchor=tk.W, pady=(0, 2))
        self._tip_color_bar = tk.Canvas(
            self._tooltip, width=60, height=12, highlightthickness=0, bg="#303030",
        )
        self._tip_color_bar.pack(anchor=tk.W, padx=6, pady=(0, 4))
        self._tip_bar_rect = self._tip_color_bar.create_rectangle(0, 0, 60, 12, fill="#000000", outline="")

        self._build_ui()

    # ── UI 构建 ──────────────────────────────────────────────
    def _build_ui(self):
        # 顶部工具栏
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="选择图片", command=self._open_file).pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value="未选择图片")
        ttk.Label(toolbar, textvariable=self.path_var, foreground="gray").pack(side=tk.LEFT, padx=12)

        ttk.Button(toolbar, text="导出颜色代码", command=self._export_codes).pack(side=tk.RIGHT)

        # 主区域：左右分栏
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # 左侧 - 原图预览
        self._left_label = ttk.LabelFrame(paned, text="原图预览  |  Ctrl+滚轮缩放  双击重置")
        paned.add(self._left_label, weight=1)

        self.preview_canvas = tk.Canvas(self._left_label, bg="#2b2b2b", highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas.bind("<Configure>", self._draw_preview)
        self.preview_canvas.bind("<Motion>", self._on_preview_motion)
        self.preview_canvas.bind("<Leave>", self._hide_tooltip)
        self.preview_canvas.bind("<Control-MouseWheel>", self._on_preview_zoom)
        self.preview_canvas.bind("<Double-Button-1>", self._reset_zoom)

        # 右侧 - 颜色网格
        right = ttk.LabelFrame(paned, text="像素颜色代码")
        paned.add(right, weight=1)

        container = ttk.Frame(right)
        container.pack(fill=tk.BOTH, expand=True)

        self.grid_canvas = tk.Canvas(container, bg="#1e1e1e", highlightthickness=0)
        self.grid_canvas.pack(fill=tk.BOTH, expand=True)
        self.grid_canvas.bind("<Configure>", self._draw_grid)
        self.grid_canvas.bind("<Motion>", self._on_grid_motion)
        self.grid_canvas.bind("<Leave>", self._hide_tooltip)

        # 底部状态栏
        self.status_var = tk.StringVar(value="请选择一张正方形图片")
        ttk.Label(self, textvariable=self.status_var, foreground="gray").pack(fill=tk.X, padx=8, pady=4)

    # ── 文件选择 ──────────────────────────────────────────────
    def _open_file(self):
        path = filedialog.askopenfilename(
            title="选择正方形图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return

        self.path_var.set(path)
        try:
            img = Image.open(path).convert("RGB")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开图片:\n{e}")
            return

        w, h = img.size
        if w != h:
            if messagebox.askyesno("提示", f"图片不是正方形 ({w}×{h})，是否仍然继续处理？"):
                img = img.crop((0, 0, min(w, h), min(w, h)))
            else:
                return

        # 保存原图尺寸
        self._orig_w, self._orig_h = img.size

        # 缩放到 24x24
        resized = img.resize((PIXEL_SIZE, PIXEL_SIZE), Image.LANCZOS)
        self._update_data(resized, img)
        self.status_var.set(f"已加载 {os.path.basename(path)} ({self._orig_w}×{self._orig_h}) → 24×24")

    # ── 数据处理 ──────────────────────────────────────────────
    def _update_data(self, resized: Image.Image, original: Image.Image):
        self.pixels = []
        self.hex_codes = []
        for y in range(PIXEL_SIZE):
            row_px = []
            row_hex = []
            for x in range(PIXEL_SIZE):
                r, g, b = resized.getpixel((x, y))
                row_px.append((r, g, b))
                row_hex.append(f"#{r:02X}{g:02X}{b:02X}")
            self.pixels.append(row_px)
            self.hex_codes.append(row_hex)

        # 保存原图用于左侧预览
        self._original_image = original
        self.preview_photo = None  # 将在 _draw_preview 中按需生成
        self._draw_preview()
        self._draw_grid()

    # ── 预览绘制（原图） ──────────────────────────────────────
    def _draw_preview(self, event=None):
        if not hasattr(self, '_original_image') or self._original_image is None:
            return
        canvas = self.preview_canvas
        canvas.delete("all")
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 10 or ch < 10:
            return

        # 计算适应画布的基准缩放
        margin = 16
        avail_w = cw - margin * 2
        avail_h = ch - margin * 2
        ow, oh = self._orig_w, self._orig_h
        self._base_scale = min(avail_w / ow, avail_h / oh, 1.0)

        # 应用用户缩放
        scale = self._base_scale * self._zoom
        draw_w = max(int(ow * scale), 1)
        draw_h = max(int(oh * scale), 1)

        fitted = self._original_image.resize((draw_w, draw_h), Image.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(fitted)

        ox = (cw - draw_w) // 2
        oy = (ch - draw_h) // 2
        self._preview_offset_x = ox
        self._preview_offset_y = oy
        self._preview_draw_w = draw_w
        self._preview_draw_h = draw_h

        canvas.create_image(ox, oy, anchor=tk.NW, image=self.preview_photo)

        # 显示缩放百分比
        pct = self._zoom * 100
        canvas.create_text(
            cw - 8, ch - 8, anchor=tk.SE,
            text=f"{pct:.0f}%", fill="#888888",
            font=("Consolas", 9),
        )

    # ── 颜色网格绘制 ──────────────────────────────────────────
    def _draw_grid(self, event=None):
        if not self.pixels:
            return
        canvas = self.grid_canvas
        canvas.delete("all")

        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        margin_left = 52
        margin_top = 24
        avail_w = cw - margin_left - 8
        avail_h = ch - margin_top - 8
        cell = max(min(avail_w // PIXEL_SIZE, avail_h // PIXEL_SIZE), 10)

        # 保存布局参数供鼠标事件使用
        self._grid_margin_left = margin_left
        self._grid_margin_top = margin_top
        self._grid_cell = cell

        font_size = max(int(cell / 4), 6)
        from tkinter import font as tkfont
        small_font = tkfont.Font(family="Consolas", size=int(font_size * self.dpi_scale))

        for y in range(PIXEL_SIZE):
            # 行号
            canvas.create_text(
                margin_left - 6, margin_top + y * cell + cell // 2,
                text=str(y), anchor=tk.E, fill="#888888", font=small_font,
            )
            for x in range(PIXEL_SIZE):
                px = margin_left + x * cell
                py = margin_top + y * cell
                color = self.hex_codes[y][x]
                canvas.create_rectangle(px, py, px + cell, py + cell, fill=color, outline="#333333")

                # # 在格子内显示颜色代码（仅在格子够大时）
                # if cell >= 22:
                #     r, g, b = self.pixels[y][x]
                #     lum = 0.299 * r + 0.587 * g + 0.114 * b
                #     text_color = "#000000" if lum > 128 else "#FFFFFF"
                #     txt = color if cell >= 40 else f"{r:02X}\n{g:02X}\n{b:02X}"
                #     canvas.create_text(
                #         px + cell // 2, py + cell // 2,
                #         text=txt, fill=text_color, font=small_font,
                #     )

        # 列号
        for x in range(PIXEL_SIZE):
            canvas.create_text(
                margin_left + x * cell + cell // 2, margin_top - 8,
                text=str(x), anchor=tk.S, fill="#888888", font=small_font,
            )

    # ── 鼠标悬浮提示 ─────────────────────────────────────────
    def _show_tooltip(self, screen_x, screen_y, x, y):
        """在鼠标位置显示颜色信息"""
        if not self.pixels:
            return
        if not (0 <= x < PIXEL_SIZE and 0 <= y < PIXEL_SIZE):
            self._hide_tooltip()
            return

        r, g, b = self.pixels[y][x]
        hex_code = self.hex_codes[y][x]

        self._tip_label_hex.config(text=f"{hex_code}  [{x},{y}]")
        self._tip_label_rgb.config(text=f"RGB({r}, {g}, {b})")
        self._tip_color_bar.itemconfig(self._tip_bar_rect, fill=hex_code)

        # 定位：鼠标右下方偏移
        tx = screen_x + 16
        ty = screen_y + 16
        self._tooltip.update_idletasks()
        tw, th = self._tooltip.winfo_reqwidth(), self._tooltip.winfo_reqheight()

        # 防止超出屏幕
        sw = self._tooltip.winfo_screenwidth()
        sh = self._tooltip.winfo_screenheight()
        if tx + tw > sw:
            tx = screen_x - tw - 8
        if ty + th > sh:
            ty = screen_y - th - 8

        self._tooltip.geometry(f"+{tx}+{ty}")
        self._tooltip.deiconify()

    def _hide_tooltip(self, event=None):
        self._tooltip.withdraw()

    def _on_grid_motion(self, event):
        """颜色网格上的鼠标移动"""
        ml = self._grid_margin_left
        mt = self._grid_margin_top
        cell = self._grid_cell
        if cell <= 0:
            return

        gx = event.x - ml
        gy = event.y - mt
        if gx < 0 or gy < 0:
            self._hide_tooltip()
            return

        px, py = gx // cell, gy // cell
        if 0 <= px < PIXEL_SIZE and 0 <= py < PIXEL_SIZE:
            # 将 canvas 坐标转换为屏幕坐标
            sx = self.grid_canvas.winfo_rootx() + event.x
            sy = self.grid_canvas.winfo_rooty() + event.y
            self._show_tooltip(sx, sy, px, py)
        else:
            self._hide_tooltip()

    def _on_preview_zoom(self, event):
        """Ctrl+滚轮缩放原图预览"""
        if not hasattr(self, '_original_image') or self._original_image is None:
            return
        # 每档缩放 1.15 倍
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self._zoom = max(0.1, min(self._zoom * factor, 20.0))
        self._draw_preview()

    def _reset_zoom(self, event=None):
        """双击重置缩放"""
        self._zoom = 1.0
        self._draw_preview()

    def _on_preview_motion(self, event):
        """原图预览上的鼠标移动 → 映射到 24x24 像素"""
        if not hasattr(self, '_original_image') or self._original_image is None:
            return
        ox = self._preview_offset_x
        oy = self._preview_offset_y
        dw = self._preview_draw_w
        dh = self._preview_draw_h

        gx = event.x - ox
        gy = event.y - oy
        if gx < 0 or gy < 0 or gx >= dw or gy >= dh:
            self._hide_tooltip()
            return

        # 映射到 24x24 网格
        px = int(gx / dw * PIXEL_SIZE)
        py = int(gy / dh * PIXEL_SIZE)
        px = min(px, PIXEL_SIZE - 1)
        py = min(py, PIXEL_SIZE - 1)

        sx = self.preview_canvas.winfo_rootx() + event.x
        sy = self.preview_canvas.winfo_rooty() + event.y
        self._show_tooltip(sx, sy, px, py)

    # ── 导出 ──────────────────────────────────────────────────
    def _export_codes(self):
        if not self.hex_codes:
            messagebox.showinfo("提示", "请先选择图片")
            return

        path = filedialog.asksaveasfilename(
            title="导出颜色代码",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("CSV", "*.csv"), ("所有文件", "*.*")],
        )
        if not path:
            return

        with open(path, "w", encoding="utf-8") as f:
            f.write("24x24 像素颜色代码\n")
            f.write("=" * 60 + "\n\n")

            # HEX 格式
            f.write("HEX 颜色代码:\n")
            for y, row in enumerate(self.hex_codes):
                f.write(f"Row {y:02d}: " + " ".join(row) + "\n")

            f.write("\n" + "=" * 60 + "\n")
            f.write("RGB 颜色代码:\n")
            for y, row in enumerate(self.pixels):
                rgb_str = " ".join(f"({r:3d},{g:3d},{b:3d})" for r, g, b in row)
                f.write(f"Row {y:02d}: {rgb_str}\n")

            # C 数组格式
            f.write("\n" + "=" * 60 + "\n")
            f.write("C 数组格式 (uint32_t, 0xRRGGBB):\n")
            f.write("const uint32_t image_24x24[24][24] = {\n")
            for y, row in enumerate(self.pixels):
                vals = ", ".join(f"0x{r:02X}{g:02X}{b:02X}" for r, g, b in row)
                f.write(f"  {{ {vals} }},\n")
            f.write("};\n")

        self.status_var.set(f"颜色代码已导出到: {path}")
        messagebox.showinfo("完成", f"颜色代码已保存到:\n{path}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
