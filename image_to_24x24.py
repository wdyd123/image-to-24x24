"""
24x24 像素图像转换器
- 通过文件资源管理器选择正方形图片
- 缩放为 24x24 像素
- 显示预览图（放大）和每个像素的颜色代码
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageEnhance, ImageTk
import os
import sys
import ctypes
import threading
import numpy as np
import urllib.request

# ── ONNX Runtime（可选，用于 AI 超分转换） ──
try:
    import onnxruntime as ort
    _HAS_ONNX = True
except ImportError:
    _HAS_ONNX = False

# ── ESPCN 超分辨率模型配置 ──
# ONNX Model Zoo - ESPCN (Efficient Sub-Pixel CNN) 超分模型
_SR_MODEL_URL = (
    "https://github.com/onnx/models/raw/refs/heads/main/"
    "validated/vision/super_resolution/sub_pixel_cnn_2016/model/"
    "super-resolution-10.onnx"
)
_SR_MODEL_DIR = os.path.join(os.path.expanduser("~"), ".cache", "img24x24")
_SR_MODEL_PATH = os.path.join(_SR_MODEL_DIR, "super-resolution-10.onnx")
_SR_INPUT_SIZE = 224   # 喂给 SR 模型的输入边长（越大细节越丰富）

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
        self._ai_processing = False      # 处理中标志

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

        ttk.Button(toolbar, text="AI 超分转换", command=self._ai_convert).pack(side=tk.LEFT, padx=(8, 0))
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

    # ── ONNX 超分模型管理 ────────────────────────────────────

    @staticmethod
    def _ensure_sr_model(status_cb=None) -> str:
        """
        确保 ESPCN 超分辨率 ONNX 模型已下载。
        尝试用 onnx 库将输入改为动态尺寸以支持任意大小输入。
        如果 onnx 库不可用，直接使用原始模型。
        """
        dynamic_path = _SR_MODEL_PATH.replace(".onnx", "_dynamic.onnx")
        if os.path.isfile(dynamic_path):
            return dynamic_path
        if os.path.isfile(_SR_MODEL_PATH):
            # 原始模型已下载，尝试转换为动态输入
            return App._make_dynamic(_SR_MODEL_PATH, dynamic_path)

        # 下载模型
        os.makedirs(_SR_MODEL_DIR, exist_ok=True)
        if status_cb:
            status_cb("正在下载 ESPCN 超分模型（~1MB，仅首次）…")
        urllib.request.urlretrieve(_SR_MODEL_URL, _SR_MODEL_PATH)
        if status_cb:
            status_cb("模型下载完成，正在准备…")
        return App._make_dynamic(_SR_MODEL_PATH, dynamic_path)

    @staticmethod
    def _make_dynamic(src_path: str, dst_path: str) -> str:
        """尝试将模型输入改为动态尺寸，失败则返回原路径"""
        try:
            import onnx
            model = onnx.load(src_path)
            for inp in model.graph.input:
                shape = inp.type.tensor_type.shape
                # 设 batch=1, channels 固定, H/W 动态
                shape.dim[0].dim_value = 1
                shape.dim[2].dim_param = "height"
                shape.dim[3].dim_param = "width"
            onnx.save(model, dst_path)
            return dst_path
        except Exception:
            return src_path

    # ── AI 超分降采样（ONNX Runtime + ESPCN） ────────────────

    def _ai_downscale(self, img: Image.Image) -> Image.Image:
        """
        用 ESPCN 超分辨率神经网络主导的降采样。
        核心思路：先缩到中等尺寸 → AI 超分辨率增强细节 → 缩到 24×24。
        神经网络在超分阶段"智能重建"像素，保留语义信息。
        """
        # ── 加载 SR 模型 ──
        model_path = self._ensure_sr_model(
            lambda msg: self.after(0, lambda m=msg: self.status_var.set(m)))
        self.after(0, lambda: self.status_var.set("AI 超分处理中…"))
        self.after(0, self.update_idletasks)

        sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        input_name = sess.get_inputs()[0].name
        input_shape = sess.get_inputs()[0].shape  # e.g. [1, 3, 'height', 'width']
        out_name = sess.get_outputs()[0].name

        # 确定模型期望的通道数和输入尺寸
        n_channels = input_shape[1] if len(input_shape) > 1 and isinstance(input_shape[1], int) else 3
        # 如果模型有固定输入尺寸，使用该尺寸；否则用 _SR_INPUT_SIZE
        model_h = input_shape[2] if len(input_shape) > 2 and isinstance(input_shape[2], int) else _SR_INPUT_SIZE
        model_w = input_shape[3] if len(input_shape) > 3 and isinstance(input_shape[3], int) else _SR_INPUT_SIZE

        # ── Step 1: 将原图缩到模型输入尺寸 ──
        # 选择足够大的中间尺寸以保留信息
        sr_input = img.resize((model_w, model_h), Image.LANCZOS)

        # ── Step 2: 预处理 ──
        # ESPCN 模型接受 YCbCr 或 RGB，取决于模型通道数
        if n_channels == 1:
            # Y 通道（亮度）
            ycbcr = sr_input.convert('YCbCr')
            y_arr = np.array(ycbcr.split()[0], dtype=np.float32) / 255.0
            input_tensor = y_arr[np.newaxis, np.newaxis, ...]  # (1, 1, H, W)
        else:
            # RGB 3 通道
            img_arr = np.array(sr_input, dtype=np.float32) / 255.0
            input_tensor = img_arr.transpose(2, 0, 1)[np.newaxis, ...]  # (1, 3, H, W)

        input_tensor = input_tensor.astype(np.float32)

        # ── Step 3: AI 超分推理 ──
        self.after(0, lambda: self.status_var.set("神经网络推理中…"))
        self.after(0, self.update_idletasks)

        sr_output = sess.run([out_name], {input_name: input_tensor})[0]

        # ── Step 4: 后处理输出 ──
        out = sr_output[0]  # 去掉 batch 维
        if out.ndim == 3:
            if out.shape[0] == 1:
                # (1, H, W) → Y 通道
                y_out = (out[0].clip(0, 1) * 255).astype(np.uint8)
                y_img = Image.fromarray(y_out, mode='L')
                # 上采样 Cb, Cr 通道
                sr_w, sr_h = y_img.size
                cb = sr_input.convert('YCbCr').split()[1].resize((sr_w, sr_h), Image.BICUBIC)
                cr = sr_input.convert('YCbCr').split()[2].resize((sr_w, sr_h), Image.BICUBIC)
                result_img = Image.merge('YCbCr', [y_img, cb, cr]).convert('RGB')
            elif out.shape[0] == 3:
                # (3, H, W) → RGB
                out_rgb = out.transpose(1, 2, 0)
                result_img = Image.fromarray(
                    (out_rgb.clip(0, 1) * 255).astype(np.uint8))
            else:
                # 其他格式，尝试按通道处理
                out_rgb = out.transpose(1, 2, 0)
                if out_rgb.shape[2] >= 3:
                    result_img = Image.fromarray(
                        (out_rgb[:, :, :3].clip(0, 1) * 255).astype(np.uint8))
                else:
                    result_img = Image.fromarray(
                        (out_rgb[:, :, 0].clip(0, 1) * 255).astype(np.uint8), mode='L').convert('RGB')
        else:
            # 2D 输出
            result_img = Image.fromarray(
                (out.clip(0, 1) * 255).astype(np.uint8), mode='L').convert('RGB')

        # ── Step 5: 缩放到目标 24×24 ──
        # 用 Lanczos 从 AI 增强后的图像缩放到目标尺寸
        result_img = result_img.resize((PIXEL_SIZE, PIXEL_SIZE), Image.LANCZOS)

        # ── Step 6: 颜色校正 ──
        # 匹配原图的色彩统计（确保 AI 不偏色）
        result_arr = np.array(result_img, dtype=np.float32)
        orig_24 = np.array(
            img.resize((PIXEL_SIZE, PIXEL_SIZE), Image.LANCZOS),
            dtype=np.float32)
        for c in range(3):
            src_mean = result_arr[:, :, c].mean()
            src_std = result_arr[:, :, c].std() + 1e-6
            ref_mean = orig_24[:, :, c].mean()
            ref_std = orig_24[:, :, c].std() + 1e-6
            # 70% 原图色彩 + 30% AI 增强色彩
            result_arr[:, :, c] = (result_arr[:, :, c] - src_mean) * (
                ref_std / src_std) * 0.7 + ref_mean * 0.7 + src_mean * 0.3

        result_img = Image.fromarray(result_arr.clip(0, 255).astype(np.uint8))

        # 轻微饱和度补偿
        result_img = ImageEnhance.Color(result_img).enhance(1.08)

        return result_img

    def _ai_convert(self):
        """AI 智能转换按钮回调（后台线程执行）"""
        if self._ai_processing:
            return
        if not hasattr(self, '_original_image') or self._original_image is None:
            messagebox.showinfo("提示", "请先选择图片")
            return
        if not _HAS_ONNX:
            messagebox.showwarning(
                "缺少依赖",
                "AI 智能转换需要 ONNX Runtime，请运行：\n\n"
                "pip install onnxruntime\n\n"
                "安装后重启程序即可使用。\n"
                "（仅 ~6MB，远小于 PyTorch）"
            )
            return

        self._ai_processing = True
        self.status_var.set("AI 正在分析图像，请稍候…")
        self.update_idletasks()

        original = self._original_image.copy()

        def _worker():
            try:
                resized = self._ai_downscale(original)
                self.after(0, lambda: self._on_ai_done(resized, original))
            except Exception as e:
                self.after(0, lambda: self._on_ai_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_ai_done(self, resized: Image.Image, original: Image.Image):
        """处理完成回调（主线程）"""
        self._ai_processing = False
        self._update_data(resized, original)
        self.status_var.set(
            f"AI 智能转换完成 {self._orig_w}×{self._orig_h} → 24×24")

    def _on_ai_error(self, err: str):
        """处理出错回调（主线程）"""
        self._ai_processing = False
        self.status_var.set("AI 处理失败")
        messagebox.showerror("AI 处理错误", f"处理过程中出错：\n{err}")

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
    def _position_tooltip(self, screen_x, screen_y):
        """定位 tooltip 在鼠标右下方，防止超出屏幕"""
        tx = screen_x + 16
        ty = screen_y + 16
        self._tooltip.update_idletasks()
        tw, th = self._tooltip.winfo_reqwidth(), self._tooltip.winfo_reqheight()

        sw = self._tooltip.winfo_screenwidth()
        sh = self._tooltip.winfo_screenheight()
        if tx + tw > sw:
            tx = screen_x - tw - 8
        if ty + th > sh:
            ty = screen_y - th - 8

        self._tooltip.geometry(f"+{tx}+{ty}")
        self._tooltip.deiconify()

    def _show_tooltip(self, screen_x, screen_y, x, y):
        """在鼠标位置显示 24x24 网格的颜色信息（右侧用）"""
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

        self._position_tooltip(screen_x, screen_y)

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
        """原图预览上的鼠标移动 → 显示原图实际像素颜色"""
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

        # 计算原图中的实际像素坐标
        img_x = int(gx / dw * self._orig_w)
        img_y = int(gy / dh * self._orig_h)
        img_x = min(img_x, self._orig_w - 1)
        img_y = min(img_y, self._orig_h - 1)

        # 获取原图该位置的实际颜色
        r, g, b = self._original_image.getpixel((img_x, img_y))
        hex_code = f"#{r:02X}{g:02X}{b:02X}"

        # 显示原图像素信息
        self._tip_label_hex.config(text=f"{hex_code}  ({img_x},{img_y})")
        self._tip_label_rgb.config(text=f"RGB({r}, {g}, {b})")
        self._tip_color_bar.itemconfig(self._tip_bar_rect, fill=hex_code)

        # 定位 tooltip
        sx = self.preview_canvas.winfo_rootx() + event.x
        sy = self.preview_canvas.winfo_rooty() + event.y
        self._position_tooltip(sx, sy)

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
