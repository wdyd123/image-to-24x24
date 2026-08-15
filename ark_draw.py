"""
明日方舟 24×24 像素画自动绘制工具
用法（必须以管理员身份运行终端）：
    python ark_draw.py pixels.json [--delay 50] [--palette-rows 5]
    python ark_draw.py pixels.json --test          # 测试模式：验证坐标
    python ark_draw.py pixels.json --manual-colors  # 手动选色模式
"""

import argparse
import ctypes
import json
import sys
import time

import numpy as np

try:
    import pyautogui
except ImportError:
    print("缺少 pyautogui，请运行: pip install pyautogui")
    sys.exit(1)

try:
    import keyboard
except ImportError:
    print("缺少 keyboard，请运行: pip install keyboard")
    sys.exit(1)

try:
    import win32gui
except ImportError:
    print("缺少 pywin32，请运行: pip install pywin32")
    sys.exit(1)

# ── pyautogui 安全设置 ──
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01

# ── 鼠标事件常量 ──
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_ABSOLUTE = 0x8000

# ── 右键检测 ──
_VK_RBUTTON = 0x02

# ── 窗口内相对坐标（窗口左上角含边框为原点 0,0） ──
GRID_ORIGIN_X = 498
GRID_ORIGIN_Y = 262
# 列方向: 块宽 28/29 交替，间距恒 3px
#   偶数列(0,2…): w=28, gap=3 → pitch=31
#   奇数列(1,3…): w=29, gap=3 → pitch=32
# 行方向: 块高恒 29，间距 3/2 交替
#   偶数行(0,2…): h=29, gap=3 → pitch=32
#   奇数行(1,3…): h=29, gap=2 → pitch=31

PALETTE_ORIGIN_X = 1393
PALETTE_ORIGIN_Y = 444
PALETTE_BLOCK_SIZE = 81
PALETTE_GAP_X = 14
PALETTE_GAP_Y = 13
PALETTE_PITCH_X = PALETTE_BLOCK_SIZE + PALETTE_GAP_X  # 95
PALETTE_PITCH_Y = PALETTE_BLOCK_SIZE + PALETTE_GAP_Y  # 94
PALETTE_COLS = 4
PALETTE_TOTAL_COLORS = 40
PALETTE_TOTAL_ROWS = (PALETTE_TOTAL_COLORS + PALETTE_COLS - 1) // PALETTE_COLS  # 10
PALETTE_TOP_ROWS = 6     # 色板最上方可见 6 行 = 24 色（暖色）
PALETTE_BOTTOM_ROWS = 4  # 色板最下方可见 4 行 = 16 色（冷色）
# 色板最下方时，右下角色块的右下角坐标（窗口相对）
PALETTE_BR_X = 1756
PALETTE_BR_Y = 1015

# ── 调色板颜色 ──
PALETTE_COLORS = [
    (34, 34, 34), (180, 180, 180), (234, 231, 223), (255, 255, 255),
    (211, 47, 54), (156, 10, 0), (214, 12, 74), (230, 150, 141),
    (254, 152, 117), (247, 208, 192), (252, 239, 234), (251, 246, 232),
    (220, 210, 200), (226, 206, 171), (213, 99, 34), (212, 140, 66),
    (242, 153, 0), (249, 201, 51), (252, 228, 153), (179, 180, 122),
    (194, 218, 114), (105, 106, 10), (166, 138, 85), (169, 143, 116),
    (170, 146, 40), (63, 43, 18), (116, 73, 31), (83, 70, 88),
    (40, 35, 67), (57, 69, 153), (90, 69, 157), (186, 163, 215),
    (182, 188, 223), (169, 172, 190), (99, 171, 185), (180, 210, 220),
    (145, 216, 230), (71, 174, 160), (182, 211, 200), (39, 56, 100),
]


# ── 工具函数 ──────────────────────────────────────────────────

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def set_terminal_topmost():
    """将终端窗口设为置顶，确保绘制期间始终可见"""
    try:
        console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if console_hwnd:
            # HWND_TOPMOST = -1, SWP_NOMOVE | SWP_NOSIZE = 0x0003
            ctypes.windll.user32.SetWindowPos(
                console_hwnd, -1, 0, 0, 0, 0, 0x0003)
            print("  [终端已置顶]")
    except Exception:
        pass


def mouse_click(x: int, y: int):
    """使用底层 Windows API 发送鼠标点击"""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    # mouse_event 无 ABSOLUTE 标志时 dx/dy 是相对偏移，传 0 表示在当前位置点击
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.02)
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def mouse_scroll(x: int, y: int, clicks: int):
    """在指定位置执行滚轮操作（正=上滚，负=下滚）"""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    # mouse_event(flags, dx, dy, mouseData, extra)
    # WHEEL 标志下 dx/dy 传 0，滚轮量在 mouseData 参数
    ctypes.windll.user32.mouse_event(0x0800, 0, 0, clicks * 120, 0)


def find_ark_window() -> tuple:
    candidates = ["明日方舟", "Arknights", "arknights"]
    result = [None]

    def _enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        for name in candidates:
            if name.lower() in title.lower():
                rect = win32gui.GetWindowRect(hwnd)
                result[0] = (hwnd, rect[0], rect[1],
                             rect[2] - rect[0], rect[3] - rect[1])
                return

    win32gui.EnumWindows(_enum_cb, None)

    if result[0] is None:
        print("\n[!] 未自动找到明日方舟窗口，当前可见窗口：")
        windows = []

        def _list_cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            rect = win32gui.GetWindowRect(hwnd)
            windows.append((hwnd, title, rect))

        win32gui.EnumWindows(_list_cb, None)
        for i, (hwnd, title, rect) in enumerate(windows):
            print(f"  [{i}] {title}  ({rect[2]-rect[0]}x{rect[3]-rect[1]} @ {rect[0]},{rect[1]})")

        if not windows:
            print("  没有找到任何可见窗口！")
            sys.exit(1)

        choice = input("\n请输入窗口编号: ").strip()
        try:
            idx = int(choice)
            hwnd, title, rect = windows[idx]
            result[0] = (hwnd, rect[0], rect[1],
                         rect[2] - rect[0], rect[3] - rect[1])
        except (ValueError, IndexError):
            print("无效选择")
            sys.exit(1)

    return result[0]


def match_palette_index(rgb: tuple) -> int:
    palette = np.array(PALETTE_COLORS, dtype=np.float32)
    pixel = np.array(rgb, dtype=np.float32)
    weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    diff = pixel[np.newaxis, :] - palette
    dist_sq = np.sum(weights * diff ** 2, axis=1)
    return int(np.argmin(dist_sq))


def load_pixel_data(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    size = data.get("size", 24)
    pixels = data.get("pixels", [])
    if size != 24:
        print(f"[警告] size={size}，预期 24")
    if len(pixels) != size * size:
        print(f"[错误] 像素数量 {len(pixels)} != {size*size}")
        sys.exit(1)
    return data


def group_pixels_by_color(pixels: list, size: int) -> dict:
    groups = {}
    for idx, rgb in enumerate(pixels):
        y, x = divmod(idx, size)
        color_idx = match_palette_index(tuple(rgb))
        if color_idx not in groups:
            groups[color_idx] = []
        groups[color_idx].append((x, y))
    return groups


# ── 绘制器 ────────────────────────────────────────────────────

class ArkDrawer:

    def __init__(self, color_groups: dict,
                 win_left: int, win_top: int,
                 click_delay: float = 0.05,
                 manual_colors: bool = False):
        self.color_groups = color_groups
        self.win_left = win_left
        self.win_top = win_top
        self.click_delay = click_delay
        self.manual_colors = manual_colors

        self._current_color = -1
        self._paused = False
        self._stopped = False

    def _to_screen(self, rel_x, rel_y):
        return self.win_left + rel_x, self.win_top + rel_y

    # ── 画布 ──

    def grid_click_pos(self, gx: int, gy: int) -> tuple:
        # 点击画板方块正中心
        # X: 块宽 28/29 交替，间距 3
        # Y: 块高恒 29，间距 3/2 交替
        rel_x = GRID_ORIGIN_X + self._grid_col_offset(gx) + self._grid_col_size(gx) // 2
        rel_y = GRID_ORIGIN_Y + self._grid_row_offset(gy) + self._grid_row_size(gy) // 2
        return self._to_screen(rel_x, rel_y)

    @staticmethod
    def _grid_col_size(g: int) -> int:
        """偶数列宽 28px，奇数列宽 29px"""
        return 28 if g % 2 == 0 else 29

    @staticmethod
    def _grid_row_size(_g: int) -> int:
        """每行高度恒为 29px"""
        return 29

    @staticmethod
    def _grid_col_offset(g: int) -> int:
        """第 g 列左边缘偏移: 偶数 pitch=31, 奇数 pitch=32, 两组=63"""
        pairs, rem = divmod(g, 2)
        return pairs * 63 + rem * 31

    @staticmethod
    def _grid_row_offset(g: int) -> int:
        """第 g 行上边缘偏移: 偶数 pitch=32, 奇数 pitch=31, 两组=63"""
        pairs, rem = divmod(g, 2)
        return pairs * 63 + rem * 32

    def _click_canvas_safe(self):
        """点击画布中央获取焦点"""
        sx, sy = self.grid_click_pos(12, 12)
        mouse_click(sx, sy)
        time.sleep(0.2)

    # ── 色板 ──

    def palette_click_pos(self, color_idx: int) -> tuple:
        """色板颜色索引 → 屏幕点击坐标
        TOP 区 (idx 0-23): 从左上角 (1393,444) 往下推
        BOTTOM 区 (idx 24-39): 从右下角 (1756,1015) 往上推
        """
        col = color_idx % PALETTE_COLS
        row = color_idx // PALETTE_COLS

        if color_idx < PALETTE_TOP_ROWS * PALETTE_COLS:
            # TOP 区：从左上角原点往下推
            rel_x = PALETTE_ORIGIN_X + col * PALETTE_PITCH_X + PALETTE_BLOCK_SIZE // 2
            rel_y = PALETTE_ORIGIN_Y + row * PALETTE_PITCH_Y + PALETTE_BLOCK_SIZE // 2
        else:
            # BOTTOM 区：从右下角往上推
            bot_row = row - PALETTE_TOP_ROWS  # 0-3
            # idx39 (col=3, bot_row=3) 的右下角 = (PALETTE_BR_X, PALETTE_BR_Y)
            # 中心 X = BR_X - (3-col)*PITCH_X - BLOCK/2
            # 中心 Y = BR_Y - (3-bot_row)*PITCH_Y - BLOCK/2
            rel_x = PALETTE_BR_X - (PALETTE_COLS - 1 - col) * PALETTE_PITCH_X - PALETTE_BLOCK_SIZE // 2
            rel_y = PALETTE_BR_Y - (PALETTE_BOTTOM_ROWS - 1 - bot_row) * PALETTE_PITCH_Y - PALETTE_BLOCK_SIZE // 2

        return self._to_screen(rel_x, rel_y)

    def _auto_scroll_palette_down(self):
        """自动滚动色板到底部：先点击色板区域获取焦点，然后滚轮向下"""
        # 点击色板区域中央，让色板获得滚动焦点
        mid_rel_x = PALETTE_ORIGIN_X + PALETTE_PITCH_X * 1.5
        mid_rel_y = PALETTE_ORIGIN_Y + PALETTE_PITCH_Y * 2.5
        sx, sy = self._to_screen(int(mid_rel_x), int(mid_rel_y))
        mouse_click(sx, sy)
        time.sleep(0.3)

        # 向下滚动 50 次确保到达最底部
        for _ in range(50):
            mouse_scroll(sx, sy, -1)
            time.sleep(0.02)
        time.sleep(0.5)

    def select_color(self, color_idx: int):
        """选择调色板颜色（无自动滚动，需要时提示用户手动滚动）"""
        if color_idx == self._current_color:
            return

        if self.manual_colors:
            self._manual_select_color(color_idx)
            return

        sx, sy = self.palette_click_pos(color_idx)
        row = color_idx // PALETTE_COLS
        col = color_idx % PALETTE_COLS
        print(f"    → 色板[{color_idx}] row={row} col={col} @ ({sx},{sy})", flush=True)
        mouse_click(sx, sy)
        self._current_color = color_idx
        time.sleep(0.3)

    def _manual_select_color(self, color_idx: int):
        """手动选色：提示用户在游戏里手动点选颜色"""
        if color_idx == self._current_color:
            return
        rgb = PALETTE_COLORS[color_idx]
        hex_c = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        row = color_idx // PALETTE_COLS
        col = color_idx % PALETTE_COLS
        print(f"\n  ┌─────────────────────────────────────────┐")
        print(f"  │ 请在色板中选择: [{color_idx}] {hex_c}             │")
        print(f"  │ 位置: 第{row+1}行 第{col+1}列                       │")
        print(f"  └─────────────────────────────────────────┘")
        input("  选好后按 Enter 继续...")
        self._current_color = color_idx

    # ── 测试模式 ──

    def run_test(self):
        """测试模式：依次点击画布四角和色板首尾，验证坐标准确性"""
        print("\n═══ 坐标测试模式 ═══")
        print("将依次点击以下位置，请观察是否正确：")
        print("  1. 画布左上角格子 (0,0)")
        print("  2. 画布右上角格子 (23,0)")
        print("  3. 画布左下角格子 (0,23)")
        print("  4. 画布右下角格子 (23,23)")
        print("  5. 色板第1个色块 (idx=0)")
        print("  6. 色板最后1个色块 (idx=39)")

        input("\n按 Enter 开始测试（请确保游戏窗口在前台）...")
        print("  3 秒后开始...")
        time.sleep(3)

        tests = [
            ("画布(0,0)", self.grid_click_pos(0, 0)),
            ("画布(23,0)", self.grid_click_pos(23, 0)),
            ("画布(0,23)", self.grid_click_pos(0, 23)),
            ("画布(23,23)", self.grid_click_pos(23, 23)),
            ("色板idx0 (TOP)", self.palette_click_pos(0)),
            ("色板idx23 (TOP末)", self.palette_click_pos(23)),
        ]

        for name, pos in tests:
            print(f"  点击 {name} @ {pos}...", end="", flush=True)
            mouse_click(pos[0], pos[1])
            print(f" ✓")
            input("  按 Enter 继续下一个...")

        # 测试 BOTTOM 区
        print("\n  自动滚动色板到底部...")
        self._auto_scroll_palette_down()

        pos24 = self.palette_click_pos(24)
        print(f"  点击 色板idx24 (BOTTOM首) @ {pos24}...", end="", flush=True)
        mouse_click(pos24[0], pos24[1])
        print(f" ✓")
        input("  按 Enter 继续...")

        pos39 = self.palette_click_pos(39)
        print(f"  点击 色板idx39 (BOTTOM末) @ {pos39}...", end="", flush=True)
        mouse_click(pos39[0], pos39[1])
        print(f" ✓")

        print("\n═══ 测试完成 ═══")
        print("如果所有点击位置正确，说明坐标配置无误。")
        print("如果点击位置偏移，请使用 --manual-colors 模式或调整坐标常量。")

    # ── 绘制 ──

    def _draw_color_group(self, color_idx, pixels, i, total_colors,
                           total_pixels, done_pixels):
        """绘制一种颜色的所有像素，返回已绘制像素数"""
        rgb = PALETTE_COLORS[color_idx]
        hex_code = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

        while self._paused and not self._stopped:
            time.sleep(0.1)
        if self._stopped:
            return done_pixels

        self.select_color(color_idx)
        print(f"  [{i+1}/{total_colors}] {hex_code} idx={color_idx}: "
              f"{len(pixels)}px", end="", flush=True)

        for j, (gx, gy) in enumerate(pixels):
            if self._stopped:
                break
            if self._check_mouse_stop():
                break
            while self._paused and not self._stopped:
                time.sleep(0.1)
            if self._stopped:
                break

            sx, sy = self.grid_click_pos(gx, gy)
            mouse_click(sx, sy)
            done_pixels += 1

            if self.click_delay > 0:
                time.sleep(self.click_delay)

            if (j + 1) % 10 == 0 or j == len(pixels) - 1:
                print(f" ({done_pixels}/{total_pixels})", end="\r")

        print(f"  ✓")
        return done_pixels

    def draw(self):
        total_colors = len(self.color_groups)
        total_pixels = sum(len(v) for v in self.color_groups.values())
        done_pixels = 0

        top_end_row = PALETTE_TOP_ROWS  # TOP 区可见 6 行 = 24 色

        print(f"\n开始绘制: {total_colors} 种颜色, {total_pixels} 个像素")
        print(f"窗口偏移: ({self.win_left}, {self.win_top})")
        print(f"点击间隔: {self.click_delay*1000:.0f}ms")
        print(f"选色模式: {'手动' if self.manual_colors else '自动'}")
        print(f"色板: TOP={PALETTE_TOP_ROWS}行({PALETTE_TOP_ROWS*PALETTE_COLS}色) "
              f"BOTTOM={PALETTE_BOTTOM_ROWS}行({PALETTE_BOTTOM_ROWS*PALETTE_COLS}色)")
        print(f"画板: 相对({GRID_ORIGIN_X},{GRID_ORIGIN_Y}) cell=28/29交替 gap=3")
        print(f"色板: 相对({PALETTE_ORIGIN_X},{PALETTE_ORIGIN_Y}) pitch={PALETTE_PITCH_X}×{PALETTE_PITCH_Y}")

        g0 = self.grid_click_pos(0, 0)
        g23 = self.grid_click_pos(23, 23)
        print(f"验证 - 画布(0,0): {g0}, 画布(23,23): {g23}")
        print("-" * 50)

        # ── Phase 1: TOP 区颜色（idx 0-23，色板最上方可见 6 行 24 色） ──
        sorted_indices = sorted(self.color_groups.keys())
        top_indices = [ci for ci in sorted_indices
                       if ci < PALETTE_TOP_ROWS * PALETTE_COLS]
        bottom_indices = [ci for ci in sorted_indices
                          if ci >= PALETTE_TOP_ROWS * PALETTE_COLS]

        if top_indices:
            print(f"\n═══ Phase 1: TOP 区颜色 ({len(top_indices)} 种) ═══")
            print("（色板保持在最上方）")
            for i, color_idx in enumerate(top_indices):
                if self._stopped:
                    break
                done_pixels = self._draw_color_group(
                    color_idx, self.color_groups[color_idx],
                    i, total_colors, total_pixels, done_pixels)

        # ── Phase 2: BOTTOM 区颜色（自动滚动色板到底部） ──
        if bottom_indices and not self._stopped:
            print(f"\n═══ 自动滚动色板到底部... ═══")
            self._auto_scroll_palette_down()

            self._current_color = -1  # 强制重新选色

            print(f"\n═══ Phase 2: BOTTOM 区颜色 ({len(bottom_indices)} 种) ═══")
            for i, color_idx in enumerate(bottom_indices):
                if self._stopped:
                    break
                done_pixels = self._draw_color_group(
                    color_idx, self.color_groups[color_idx],
                    len(top_indices) + i, total_colors,
                    total_pixels, done_pixels)

        if not self._stopped:
            print(f"\n{'='*50}")
            print(f"  绘制完成！共 {done_pixels} 个像素")
            print(f"{'='*50}")

    def toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            print("\n  [已暂停] 按 F9 继续...")
        else:
            print("  [继续绘制]")

    def stop(self):
        self._stopped = True
        self._paused = False

    def _check_mouse_stop(self):
        """检测鼠标右键是否按下，若是则停止绘制"""
        state = ctypes.windll.user32.GetAsyncKeyState(_VK_RBUTTON)
        if state & 0x8000:
            print("\n  [右键检测到，停止绘制]")
            self.stop()
            return True
        return False


# ── 主流程 ────────────────────────────────────────────────────

def countdown(seconds: int):
    for i in range(seconds, 0, -1):
        print(f"  {i}...", flush=True)
        time.sleep(1)
    print("  开始！")


def main():
    parser = argparse.ArgumentParser(
        description="明日方舟 24×24 像素画自动绘制工具",
        epilog="注意：必须以管理员身份运行终端！"
    )
    parser.add_argument("json_file", help="导出的像素 JSON 文件")
    parser.add_argument("--delay", type=int, default=50,
                        help="每次点击间隔（毫秒），默认 50")
    parser.add_argument("--test", action="store_true",
                        help="测试模式：点击画布四角和色板首尾验证坐标")
    parser.add_argument("--manual-colors", action="store_true",
                        help="手动选色模式：脚本提示你手动在色板选色")
    args = parser.parse_args()

    # ── 管理员检查 ──
    if not is_admin():
        print("╔══════════════════════════════════════════════════╗")
        print("║  警告：未检测到管理员权限！                       ║")
        print("║  请右键终端 → 以管理员身份运行，然后重新执行。    ║")
        print("╚══════════════════════════════════════════════════╝")
        resp = input("仍然继续？(y/N): ").strip().lower()
        if resp != "y":
            sys.exit(0)

    # ── 查找游戏窗口 ──
    print("查找明日方舟窗口...")
    hwnd, win_left, win_top, win_w, win_h = find_ark_window()
    title = win32gui.GetWindowText(hwnd)
    print(f"  窗口: \"{title}\"")
    print(f"  位置: ({win_left}, {win_top}), 尺寸: {win_w}×{win_h}")

    try:
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.3)
    except Exception as e:
        print(f"  [警告] 无法置前窗口: {e}")

    # ── 加载像素数据 ──
    print(f"\n加载: {args.json_file}")
    data = load_pixel_data(args.json_file)
    size = data["size"]
    pixels = data["pixels"]
    print(f"  {size}×{size}, {len(pixels)} 像素")

    # ── 按颜色分组 ──
    color_groups = group_pixels_by_color(pixels, size)
    total_pixels = sum(len(v) for v in color_groups.values())
    print(f"  使用 {len(color_groups)} 种颜色, {total_pixels} 有效像素")

    print("\n  颜色分布:")
    for ci in sorted(color_groups.keys()):
        rgb = PALETTE_COLORS[ci]
        hex_c = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        print(f"    [{ci:2d}] {hex_c}: {len(color_groups[ci])} 像素")

    # ── 创建绘制器 ──
    drawer = ArkDrawer(
        color_groups=color_groups,
        win_left=win_left,
        win_top=win_top,
        click_delay=args.delay / 1000.0,
        manual_colors=args.manual_colors,
    )

    # ── 注册热键 ──
    keyboard.add_hotkey("F9", drawer.toggle_pause)
    keyboard.add_hotkey("F10", drawer.stop)

    print("\n快捷键: F9=暂停/继续, F10=紧急停止")
    print("鼠标: 右键=紧急停止, 左上角=安全退出")

    # ── 测试模式 ──
    if args.test:
        drawer.run_test()
        keyboard.unhook_all()
        return

    # ── 正常绘制 ──
    if args.manual_colors:
        print("\n[手动选色模式] 每次换色时请在游戏中手动点选色板，然后按 Enter")
    else:
        print("\n[自动模式] 请确保色板已拉到最上方")

    input("\n按 Enter 开始 3 秒倒计时...")
    countdown(3)

    # 重新获取窗口位置
    try:
        rect = win32gui.GetWindowRect(hwnd)
        drawer.win_left = rect[0]
        drawer.win_top = rect[1]
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.2)
    except Exception:
        pass

    # 终端置顶，确保绘制期间可见
    set_terminal_topmost()

    try:
        drawer.draw()
    except KeyboardInterrupt:
        print("\n\n[Ctrl+C 中断]")
        drawer.stop()
    finally:
        keyboard.unhook_all()
        print("\n热键已解除。")


if __name__ == "__main__":
    main()
