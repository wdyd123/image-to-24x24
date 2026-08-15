"""
24x24 像素图像转换器
- 通过文件资源管理器选择正方形图片
- 缩放为 24x24 像素
- 显示预览图（放大）和每个像素的颜色代码
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageEnhance, ImageFilter, ImageTk
import os
import sys
import json
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

# ── 调色板颜色（从色块图片自动提取） ──
# 暖色调色板（6行×4列 = 24色）+ 冷色调色板（4行×4列 = 16色）
PALETTE_COLORS = [
    # ── 暖色调色板 ──
    # Row 1: 黑 / 灰 / 白系
    (34, 34, 34),         # #222222 深灰黑
    (180, 180, 180),      # #B4B4B4 浅灰
    (234, 231, 223),      # #EAE7DF 米白
    (255, 255, 255),      # #FFFFFF 纯白
    # Row 2: 红 / 品红系
    (211, 47, 54),        # #D32F36 红
    (156, 10, 0),         # #9C0A00 暗红
    (214, 12, 74),        # #D60C4A 品红
    (230, 150, 141),      # #E6968D 浅粉
    # Row 3: 珊瑚 / 粉色系
    (254, 152, 117),      # #FE9875 珊瑚
    (247, 208, 192),      # #F7D0C0 淡粉
    (252, 239, 234),      # #FCEFEA 极淡粉
    (251, 246, 232),      # #FBF6E8 奶白
    # Row 4: 米色 / 棕色系
    (220, 210, 200),      # #DCD2C8 浅米
    (226, 206, 171),      # #E2CEAB 棕褐
    (213, 99, 34),        # #D56322 焦橙
    (212, 140, 66),       # #D48C42 浅棕
    # Row 5: 橙 / 黄系
    (242, 153, 0),        # #F29900 橙
    (249, 201, 51),       # #F9C933 金黄
    (252, 228, 153),      # #FCE499 淡黄
    (179, 180, 122),      # #B3B47A 橄榄卡其
    # Row 6: 绿色 / 褐色系
    (194, 218, 114),      # #C2DA72 浅绿
    (105, 106, 10),       # #696A0A 深橄榄绿
    (166, 138, 85),       # #A68A55 深金棕
    (169, 143, 116),      # #A98F74 灰褐
    # ── 冷色调色板 ──
    # Row 1: 橄榄 / 棕色系
    (170, 146, 40),       # #AA9228 橄榄金
    (63, 43, 18),         # #3F2B12 深棕
    (116, 73, 31),        # #74491F 焦棕
    (83, 70, 88),         # #534658 灰紫
    # Row 2: 深蓝 / 紫色系
    (40, 35, 67),         # #282343 深蓝
    (57, 69, 153),        # #394599 宝蓝
    (90, 69, 157),        # #5A459D 中紫
    (186, 163, 215),      # #BAA3D7 薰衣草
    # Row 3: 淡紫 / 蓝灰系
    (182, 188, 223),      # #B6BCDF 淡薰衣草
    (169, 172, 190),      # #A9ACBE 蓝灰
    (99, 171, 185),       # #63ABB9 青蓝
    (180, 210, 220),      # #B4D2DC 淡天蓝
    # Row 4: 天蓝 / 青绿色系
    (145, 216, 230),      # #91D8E6 天蓝
    (71, 174, 160),       # #47AEA0 海绿
    (182, 211, 200),      # #B6D3C8 薄荷
    (39, 56, 100),        # #273864 深海军蓝
]


class GifFrameSelector(tk.Toplevel):
    """GIF 动画帧可视化选择器：缩略图网格 + 翻页"""

    COLS = 8
    PAGE_SIZE = 40  # 每页最多显示 40 帧

    def __init__(self, parent, img, n_frames):
        super().__init__(parent)
        self.title("选择帧")
        self.transient(parent)
        self.grab_set()

        self.img = img
        self.n_frames = n_frames
        self.selected_frame = 0
        self._page = 0
        self._thumbs: list[ImageTk.PhotoImage] = []
        self._buttons: list[tk.Button] = []

        self._build_ui()
        self._load_page()

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.wait_window()

    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text=f"共 {self.n_frames} 帧 — 点击选择").pack(side=tk.LEFT)
        self._page_label = ttk.Label(top, text="")
        self._page_label.pack(side=tk.RIGHT)

        nav = ttk.Frame(self, padding=4)
        nav.pack(fill=tk.X)
        self._prev_btn = ttk.Button(nav, text="◄ 上一页", command=self._go_prev)
        self._prev_btn.pack(side=tk.LEFT)
        self._next_btn = ttk.Button(nav, text="下一页 ►", command=self._go_next)
        self._next_btn.pack(side=tk.RIGHT)

        self._grid_frame = ttk.Frame(self)
        self._grid_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        bot = ttk.Frame(self, padding=8)
        bot.pack(fill=tk.X)
        ttk.Button(bot, text="取消", command=self._cancel).pack(side=tk.RIGHT)

    def _total_pages(self):
        return max(1, (self.n_frames + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

    def _load_page(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._thumbs.clear()
        self._buttons.clear()

        start = self._page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, self.n_frames)
        tp = self._total_pages()
        self._page_label.config(text=f"第 {self._page + 1}/{tp} 页")
        self._prev_btn.config(state=tk.NORMAL if self._page > 0 else tk.DISABLED)
        self._next_btn.config(state=tk.NORMAL if self._page < tp - 1 else tk.DISABLED)

        # 记住当前帧位置，结束后恢复
        orig_frame = self.img.tell()

        try:
            for i in range(start, end):
                self.img.seek(i)
                thumb_img = self.img.convert("RGBA")
                bg = Image.new("RGBA", thumb_img.size, (255, 255, 255, 255))
                bg.paste(thumb_img, mask=thumb_img.split()[3])
                thumb_img = bg.convert("RGB").resize((48, 48), Image.NEAREST)
                photo = ImageTk.PhotoImage(thumb_img)
                self._thumbs.append(photo)

                row, col = divmod(i - start, self.COLS)
                btn = tk.Button(
                    self._grid_frame, image=photo,
                    command=lambda idx=i: self._select(idx),
                    relief=tk.FLAT, padx=2, pady=2,
                )
                btn.grid(row=row, column=col, padx=3, pady=3)
                # 帧编号标签
                lbl = ttk.Label(self._grid_frame, text=str(i + 1),
                                font=("Consolas", 7))
                lbl.grid(row=row + 1, column=col)
                self._buttons.append(btn)
        finally:
            self.img.seek(orig_frame)

    def _go_prev(self):
        if self._page > 0:
            self._page -= 1
            self._load_page()

    def _go_next(self):
        if self._page < self._total_pages() - 1:
            self._page += 1
            self._load_page()

    def _select(self, idx):
        self.selected_frame = idx
        self.destroy()

    def _cancel(self):
        self.selected_frame = -1
        self.destroy()


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
        self._downscale_mode = tk.StringVar(value="标准")

        # 调色板限制
        self._palette_snap_enabled = False
        self._resized_image_orig = None  # 未吸附调色板的原始 24×24 图像

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
        self._mode_combo = ttk.Combobox(toolbar, textvariable=self._downscale_mode,
                                         values=["标准", "边缘增强", "主色量化", "增强+主色"],
                                         state="readonly", width=10)
        self._mode_combo.pack(side=tk.LEFT, padx=(8, 0))
        self._mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)
        self._palette_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="调色板限制", variable=self._palette_var,
                         command=self._on_palette_toggle).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Button(toolbar, text="导出颜色代码", command=self._export_codes).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="导出24×24图片", command=self._export_image).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(toolbar, text="导出方舟数据", command=self._export_ark_json).pack(side=tk.RIGHT, padx=(0, 8))

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

        # ── Step 5: 智能降采样到目标 24×24 ──
        result_img = self._smart_downscale(result_img)

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
            img = Image.open(path)

            # ── 动画帧选择（GIF 等多帧图片） ──
            n_frames = getattr(img, "n_frames", 1)
            if n_frames > 1:
                selector = GifFrameSelector(self, img, n_frames)
                if selector.selected_frame < 0:
                    return  # 用户取消
                img.seek(selector.selected_frame)

            # 所有图片都垫白色底层（处理透明/半透明/调色板模式）
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                bg.paste(img, mask=img.split()[3])
            elif img.mode in ("P", "PA"):
                # 调色板模式可能含透明索引，先转 RGBA
                img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[3])
            elif img.mode == "LA":
                img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[3])
            else:
                bg.paste(img.convert("RGB"))
            img = bg
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

        # 智能降采样到 24x24
        resized = self._smart_downscale(img)
        self._update_data(resized, img)
        self.status_var.set(f"已加载 {os.path.basename(path)} ({self._orig_w}×{self._orig_h}) → 24×24  [{self._downscale_mode.get()}]")

    # ── 数据处理 ──────────────────────────────────────────────
    def _update_data(self, resized: Image.Image, original: Image.Image):
        # 保存未吸附调色板的原始 24×24 图像（用于关闭时恢复）
        self._resized_image_orig = resized.copy()

        # 若调色板限制已开启，吸附到调色板
        if self._palette_snap_enabled:
            resized = self._snap_to_palette(resized)

        self._resized_image = resized
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

    # ── 智能降采样 ─────────────────────────────────────────────
    def _smart_downscale(self, img: Image.Image) -> Image.Image:
        """根据当前降采样模式将图像缩放到 24×24"""
        mode = self._downscale_mode.get()
        if mode == "标准":
            return img.resize((PIXEL_SIZE, PIXEL_SIZE), Image.LANCZOS)
        enhanced = img
        if "增强" in mode:
            enhanced = self._edge_enhance(img)
        if "主色" in mode:
            return self._dominant_color(enhanced)
        return enhanced.resize((PIXEL_SIZE, PIXEL_SIZE), Image.LANCZOS)

    @staticmethod
    def _edge_enhance(img: Image.Image) -> Image.Image:
        """灰度边缘引导的轮廓增强（保留色相）"""
        # 1. Unsharp mask 锐化
        sharpened = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
        # 2. 灰度 Sobel 边缘检测
        gray = img.convert('L')
        edges = gray.filter(ImageFilter.FIND_EDGES)
        # 3. 将边缘信息转回 RGB 并叠加
        edges_rgb = edges.convert('RGB')
        base_arr = np.array(sharpened, dtype=np.float32)
        edge_arr = np.array(edges_rgb, dtype=np.float32)
        edge_weight = np.mean(edge_arr, axis=2, keepdims=True) / 255.0
        blend = (base_arr * (1 - edge_weight * 0.25) + edge_arr * edge_weight * 0.25)
        result = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
        # 4. 轻微锐化保持清晰
        result = ImageEnhance.Sharpness(result).enhance(1.2)
        return result

    @staticmethod
    def _dominant_color(img: Image.Image) -> Image.Image:
        """主色量化：每个目标像素取源区域内出现次数最多的颜色"""
        arr = np.array(img)
        h, w, _ = arr.shape
        target = PIXEL_SIZE
        result = np.zeros((target, target, 3), dtype=np.uint8)
        for ty in range(target):
            for tx in range(target):
                y0 = ty * h // target
                y1 = (ty + 1) * h // target
                x0 = tx * w // target
                x1 = (tx + 1) * w // target
                region = arr[y0:y1, x0:x1].reshape(-1, 3)
                if region.size == 0:
                    continue
                # 量化为 32 级以合并相近颜色，再找众数
                quantized = (region // 8) * 8 + 4
                counts = {}
                for pixel in quantized:
                    key = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
                    counts[key] = counts.get(key, 0) + 1
                dominant_q = max(counts, key=counts.get)
                # 从原始像素中取该量化桶的平均色（更精确）
                mask = np.all(quantized == np.array(dominant_q), axis=1)
                result[ty, tx] = region[mask].mean(axis=0).round().astype(np.uint8)
        return Image.fromarray(result)

    def _on_mode_change(self, _event=None):
        """降采样模式切换时重新处理图像"""
        if not hasattr(self, '_original_image') or self._original_image is None:
            return
        resized = self._smart_downscale(self._original_image)
        self._update_data(resized, self._original_image)
        self.status_var.set(f"已切换降采样模式: {self._downscale_mode.get()} → 24×24")

    # ── 调色板吸附 ────────────────────────────────────────────
    @staticmethod
    def _snap_to_palette(img: Image.Image) -> Image.Image:
        """将图像中每个像素吸附到调色板中最近的颜色（加权 RGB 距离）"""
        palette = np.array(PALETTE_COLORS, dtype=np.float32)
        arr = np.array(img, dtype=np.float32)
        h, w, _ = arr.shape
        flat = arr.reshape(-1, 3)                       # (576, 3)
        # 加权 RGB 距离（模拟人眼亮度感知 R:0.299 G:0.587 B:0.114）
        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        diff = flat[:, np.newaxis, :] - palette[np.newaxis, :, :]  # (576, N, 3)
        dist_sq = np.sum(weights * diff ** 2, axis=2)   # (576, N)
        indices = np.argmin(dist_sq, axis=1)             # (576,)
        snapped = palette[indices].reshape(h, w, 3).astype(np.uint8)
        return Image.fromarray(snapped)

    def _on_palette_toggle(self):
        """调色板限制开关切换"""
        self._palette_snap_enabled = self._palette_var.get()
        if self._resized_image_orig is None:
            return

        if self._palette_snap_enabled:
            self._resized_image = self._snap_to_palette(self._resized_image_orig)
            self.status_var.set("调色板限制已开启 — 像素已吸附到调色板颜色")
        else:
            self._resized_image = self._resized_image_orig.copy()
            self.status_var.set("调色板限制已关闭 — 恢复原始颜色")

        # 从当前 _resized_image 重建 pixels / hex_codes 并刷新网格
        self.pixels = []
        self.hex_codes = []
        img = self._resized_image
        for y in range(PIXEL_SIZE):
            row_px = []
            row_hex = []
            for x in range(PIXEL_SIZE):
                r, g, b = img.getpixel((x, y))
                row_px.append((r, g, b))
                row_hex.append(f"#{r:02X}{g:02X}{b:02X}")
            self.pixels.append(row_px)
            self.hex_codes.append(row_hex)
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

    # ── 导出24×24图片 ──────────────────────────────────────────
    def _export_image(self):
        if not hasattr(self, '_resized_image') or self._resized_image is None:
            messagebox.showinfo("提示", "请先选择图片")
            return

        path = filedialog.asksaveasfilename(
            title="导出24×24图片",
            defaultextension=".png",
            filetypes=[
                ("PNG 图片", "*.png"),
                ("BMP 图片", "*.bmp"),
                ("JPEG 图片", "*.jpg"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return

        try:
            self._resized_image.save(path)
            self.status_var.set(f"24×24 图片已导出到: {path}")
            messagebox.showinfo("完成", f"24×24 图片已保存到:\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"保存图片时出错:\n{e}")

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

    # ── 导出方舟数据 ────────────────────────────────────────────
    def _export_ark_json(self):
        """导出 24x24 像素数据为 JSON（供 ark_draw.py 自动绘制使用）"""
        if not self.pixels:
            messagebox.showinfo("提示", "请先选择图片")
            return

        path = filedialog.asksaveasfilename(
            title="导出方舟绘制数据",
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return

        # 扁平化 576 个像素 [r, g, b]
        flat_pixels = []
        for row in self.pixels:
            for r, g, b in row:
                flat_pixels.append([r, g, b])

        data = {
            "size": PIXEL_SIZE,
            "pixels": flat_pixels,
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.status_var.set(f"方舟绘制数据已导出到: {path}")
            messagebox.showinfo("完成", f"方舟绘制数据已保存到:\n{path}\n\n"
                                f"使用方式:\n"
                                f"  以管理员身份运行终端\n"
                                f"  python ark_draw.py \"{path}\"")
        except Exception as e:
            messagebox.showerror("导出失败", f"保存 JSON 时出错:\n{e}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
