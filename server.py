"""Desktop 键鼠控制 MCP Server（v0.2 · 坐标抽象升级版）

把 default（QwenPaw）的视觉能力（smart-vision）与真实系统级键鼠操作打通，
提供 Computer Agent 风格的"看屏 → 思考 → 真实操控"闭环。

底层：pyautogui（真实系统级输入注入，非浏览器 CDP 模拟）。

v0.2 升级（2026-08-05，借鉴业界 Computer-Use Agent 设计）：
1. Windows DPI 感知：高分屏（125%/150% 缩放）下 pyautogui 坐标不再错位
2. 坐标归一化抽象层：模型可输出 [0,999] 整数 或 [0,1] 浮点（normalized=True），
   由本层投影到真实物理像素 —— 视觉模型不用知道屏幕分辨率
3. 边缘内缩（_FAILSAFE_EDGE_PX=4）：归一化坐标自动避开屏幕边缘 4px，
   防止误触 Windows 热角 / pyautogui FAILSAFE 触发区
4. easeOutQuad 缓动平滑移动 + 点击前先平滑到位（模拟人手，避免瞬移惊吓）
5. 全局串行锁：多 agent 并发调键鼠时排队执行，避免互相抢鼠标

screen_capture 增强（2026-08-06，解决"看不见指针 / 截图太小"）：
6. 默认截全屏并把鼠标指针用红圈+十字在图上标出来（include_cursor=True）
7. 输出按 max_width=1440 缩放：全屏大图且图标标签这类最小字可辨认（可再调小更省token）
8. region="cursor"：以指针为中心截约 70% 屏幕的大图
9. 返回 cursor:{raw, norm, on_screenshot}，norm 可直接配 normalized=True 点击

提供工具（13 个，名称与旧版完全兼容，仅新增 normalized 可选参数）：
- screen_capture      截取全屏 / 指定区域，返回文件路径（配合 view_image 看图）
- screen_size         获取屏幕分辨率
- mouse_position      查询当前鼠标坐标
- mouse_move          平滑移动鼠标
- mouse_click         左键点击坐标
- mouse_double_click  双击
- mouse_right_click   右键
- mouse_drag          拖拽
- mouse_scroll        滚动
- keyboard_write      键入 ASCII 文本
- key_paste           粘贴任意文本（支持中文，经剪贴板）
- key_press           按单个键
- press_hotkey        组合快捷键

安全规约：
- pyautogui.FAILSAFE 开启：鼠标甩到左上角(0,0)可中止脚本
- 所有坐标做屏幕边界夹取，越界拒绝执行
- 破坏性操作需用户明确同意
"""

import sys
import json
import time
import threading
from pathlib import Path
from typing import Optional

import pyautogui

# 真实系统级键鼠：开启极坐标安全（甩到左上角中止）与平滑
pyautogui.PAUSE = 0.12
pyautogui.FAILSAFE = True

# ── Windows DPI 感知（高分屏关键）──
# pyautogui 返回的是物理像素；若进程不声明 DPI awareness，Windows 会
# 虚拟化坐标导致 125%/150% 缩放下点击错位。必须在导入 pyautogui 后立即设置。
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Desktop Control MCP Server")

SCREENSHOT_DIR = Path(__file__).resolve().parent / "shots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

# 全局串行锁：MCP 调用之间互斥，防止多 agent 同时抢键鼠
_ACTION_LOCK = threading.Lock()

# ── 坐标抽象层 ───────────────────────────

_COORD_MAX = 999          # 模型坐标系最大值（视觉模型通用习惯）
_FAILSAFE_EDGE_PX = 4     # 边缘内缩像素：避开 Windows 热角 / FAILSAFE 区


def _screen_size() -> "tuple[int,int]":
    w, h = pyautogui.size()
    return int(w), int(h)


def _clamp_coords(x: int, y: int) -> "tuple[int,int]":
    """把坐标夹进屏幕范围内，防止越界误操作。"""
    w, h = _screen_size()
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    return x, y


def _check_coords(x: int, y: int) -> "tuple[int,int]":
    """坐标校验 + 夹取。负数或越界坐标夹回屏幕内，避免误点任务栏外。"""
    return _clamp_coords(x, y)


def _project_pair(x, y, normalized: bool = False) -> "tuple[int,int]":
    """坐标投影到物理像素。

    normalized=False（默认）：x/y 视为绝对物理像素，仅做边界夹取 —— 与旧版兼容。
    normalized=True：接受视觉模型的抽象坐标：
      - 浮点在 [0,1]  → 按比例放大到物理像素（归一化）
      - 整数/浮点在 [0,999] → 按 999 等比例放大
      投影后再做边缘内缩（inset），避开屏幕 4px 热角与 FAILSAFE 触发区。
    """
    w, h = _screen_size()
    if normalized:
        if (
            isinstance(x, float) and isinstance(y, float)
            and 0 <= x <= 1 and 0 <= y <= 1
        ):
            px = float(x) * max(0, w - 1)
            py = float(y) * max(0, h - 1)
        else:
            px = float(x) * max(0, w - 1) / _COORD_MAX
            py = float(y) * max(0, h - 1) / _COORD_MAX
        # clamp + inset
        px = max(0, min(int(round(px)), w - 1))
        py = max(0, min(int(round(py)), h - 1))
        if w > _FAILSAFE_EDGE_PX * 2:
            px = max(_FAILSAFE_EDGE_PX, min(px, w - 1 - _FAILSAFE_EDGE_PX))
        if h > _FAILSAFE_EDGE_PX * 2:
            py = max(_FAILSAFE_EDGE_PX, min(py, h - 1 - _FAILSAFE_EDGE_PX))
        return px, py
    return _check_coords(x, y)


def _smooth_move_to(x: int, y: int, duration: float = 0.3) -> None:
    """平滑移动 + easeOutQuad 缓动（模拟人手移动，避免瞬移）。"""
    try:
        pyautogui.moveTo(x, y, duration=duration, tween=pyautogui.easeOutQuad)
    except Exception:
        try:
            pyautogui.moveTo(x, y, duration=duration)
        except Exception:
            pass


def _snap_path(tag: str = "snap", ext: str = ".png") -> Path:
    return SCREENSHOT_DIR / f"{tag}_{int(time.time()*1000)}{ext}"


# ---------------- 屏幕 ----------------

_CURSOR_RING_R = 14        # 指针标记外圈半径（在 1440 宽参考图上的像素）
_CURSOR_RING_WIDTH = 3     # 外圈线宽


def _draw_cursor_marker(img, cx: int, cy: int) -> None:
    """在 PIL 图上以 (cx,cy) 为指针尖端画醒目标记：红色外圈 + 十字准星 + 黄色中心点。

    高对比配色保证在任何桌面背景下可见；圈内中心即鼠标指针实际尖端位置。
    """
    from PIL import ImageDraw
    w, h = img.size
    r = max(10, _CURSOR_RING_R)
    lw = max(2, _CURSOR_RING_WIDTH)
    arm = r + 8  # 十字超出圈外的臂长
    # 夹取到图内，避免画到图外
    cx = max(0, min(int(cx), w - 1))
    cy = max(0, min(int(cy), h - 1))
    draw = ImageDraw.Draw(img, "RGBA")
    # 半透明外圈（先画大的淡圈，增强显眼度）
    draw.ellipse([cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4],
                 outline=(255, 0, 0, 90), width=lw + 2)
    # 实心红圈
    draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                 outline=(255, 0, 0, 255), width=lw)
    # 十字准星
    draw.line([cx - arm, cy, cx + arm, cy], fill=(255, 0, 0, 255), width=lw)
    draw.line([cx, cy - arm, cx, cy + arm], fill=(255, 0, 0, 255), width=lw)
    # 中心黄色圆点 = 指针尖端
    dot = max(3, r // 4)
    draw.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=(255, 215, 0, 255))
    # 小三角箭头提示方向（指针尖端默认朝左上，这里做纯标记即可）
    draw.polygon([(cx, cy - r - 4), (cx + 7, cy - r - 16), (cx + 16, cy - r - 7)],
                 outline=(255, 0, 0, 255), fill=(255, 215, 0, 255))


def _cursor_centered_region(ratio: float = 0.7) -> "tuple[int,int,int,int]":
    """以当前鼠标指针为中心，截一个宽高约为屏幕 70% 的大区域（自动夹取到屏内）。"""
    w, h = _screen_size()
    cw = max(1, int(w * max(0.1, min(1.0, ratio))))
    ch = max(1, int(h * max(0.1, min(1.0, ratio))))
    x, y = pyautogui.position()
    left = max(0, min(int(x - cw // 2), w - cw))
    top = max(0, min(int(y - ch // 2), h - ch))
    return left, top, cw, ch


def _resize_for_llm(img, max_width: int):
    """把截图缩到 max_width 宽（保持比例）。局部小图本身不足 max_width 则不放大。

    全屏 2560x1600 → 1440x900 左右：图标名称标签这类最小字仍可辨认，
    且明显省 token；用户可调 max_width 权衡清晰度。
    """
    img_w, img_h = img.size
    if max_width and max_width > 0 and img_w > max_width:
        scale = max_width / img_w
        new_w = int(round(img_w * scale))
        new_h = int(round(img_h * scale))
        return img.resize((new_w, new_h), Image_LANCZOS), scale
    return img, 1.0


# Pillow 的 LANCZOS 常量（12.x 起推荐 Image.Resampling.LANCZOS，兼容旧写法）
try:
    Image_LANCZOS = __import__("PIL.Image", fromlist=["Resampling"]).Resampling.LANCZOS
except Exception:
    Image_LANCZOS = 1  # Image.ANTIALIAS 的旧值


@mcp.tool()
def screen_capture(
    region: str = "full",
    x: int = 0,
    y: int = 0,
    width: int = 0,
    height: int = 0,
    include_cursor: bool = True,
    max_width: int = 1440,
    max_height: int = 0,
    image_format: str = "jpeg",
    quality: int = 80,
    save_path: str = "",
) -> str:
    """截取屏幕（默认全屏，并把鼠标指针用红圈+十字标在图上）。返回图片绝对路径，配合 view_image 看图。

    参数：
      region: "full"（默认，全屏）| "cursor"（以当前鼠标指针为中心截约 70% 屏幕的大图）| "左,上,宽,高"（自定义区域）
      x,y,width,height: 兼容旧调用；当 width,height 均 >0 时按此区域截图，忽略 region
      include_cursor: 是否在图上标记鼠标指针位置（默认 True；红圈中心=指针尖端）
      max_width: 输出图最大宽度，默认 1440。更小=更省 token 但更糊；更大=更清晰。
                 桌面图标名称标签这种小字，1440 宽时基本可辨认。
      max_height: 输出图最大高度，默认 0=不限制。设 720 可显著降低
                  视觉 token 数，截图后模型响应更快；清晰度要求高时不设。
      image_format: 输出格式。"jpeg"（默认，体积小 3~4 倍、视觉编码快）| "png"（无损）。
      quality: jpeg 质量 1~100，默认 80（越低越小越快）。
      save_path: 自定义保存路径（可选，默认存 shots/ 目录）

    返回 JSON：{path, width, height, scale, format, cursor}
      cursor: {raw:[物理像素x,y], norm:[0~1 归一化,可直接配 normalized=True 点击],
               on_screenshot:[图上像素, 指针不在图内则为 null]}
    """
    from PIL import Image
    fmt = (image_format or "jpeg").lower()
    if fmt not in ("jpeg", "png"):
        fmt = "jpeg"
    quality = max(1, min(100, int(quality)))
    with _ACTION_LOCK:
        if width > 0 and height > 0:
            img = pyautogui.screenshot(region=(int(x), int(y), int(width), int(height)))
        elif region == "cursor":
            rx, ry, rw, rh = _cursor_centered_region()
            img = pyautogui.screenshot(region=(rx, ry, rw, rh))
        elif region == "full":
            img = pyautogui.screenshot()
        else:
            # 支持 "left,top,width,height" 字符串形式
            try:
                parts = [int(p.strip()) for p in region.split(",")]
                if len(parts) != 4:
                    raise ValueError
                rx, ry, rw, rh = parts
                img = pyautogui.screenshot(region=(rx, ry, rw, rh))
            except Exception:
                img = pyautogui.screenshot()

        img, scale = _resize_for_llm(img, max_width)
        # 可再限高（比如 720）。长宽比不变，进一步减 token
        if max_height and max_height > 0 and img.height > max_height:
            r = max_height / img.height
            img = img.resize((max(1, int(img.width * r)), max_height), Image_LANCZOS)
            scale *= r

        # 鼠标指针位置
        cw, ch = _screen_size()
        cx_raw, cy_raw = pyautogui.position()
        cx_raw, cy_raw = _clamp_coords(cx_raw, cy_raw)
        cursor_info = {
            "raw": [int(cx_raw), int(cy_raw)],
            "norm": [round(cx_raw / max(1, cw - 1), 4), round(cy_raw / max(1, ch - 1), 4)],
            "on_screenshot": None,
        }
        if include_cursor:
            # 判断指针是否落在截图区域内：全屏必然在；区域截图需换算
            left, top = 0, 0
            if width > 0 and height > 0:
                left, top = int(x), int(y)
            elif region == "cursor":
                left, top, _, _ = _cursor_centered_region()
            elif region != "full":
                try:
                    left, top, _, _ = [int(p.strip()) for p in region.split(",")]
                except Exception:
                    left, top = 0, 0
            img_w, img_h = img.size
            if left <= cx_raw < left + img_w / scale and top <= cy_raw < top + img_h / scale:
                on_img_x = int((cx_raw - left) * scale)
                on_img_y = int((cy_raw - top) * scale)
                _draw_cursor_marker(img, on_img_x, on_img_y)
                cursor_info["on_screenshot"] = [on_img_x, on_img_y]
            else:
                cursor_info["on_screenshot"] = None
        # JPEG 不支持 RGBA：先转 RGB（无损流程下几乎不损失清晰度）
        save_ext = ".jpg" if fmt == "jpeg" else ".png"
        if save_ext == ".jpg" and img.mode == "RGBA":
            img = img.convert("RGB")
        if save_path:
            path = Path(save_path)
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path = _snap_path("screen", ext=save_ext)
        if save_ext == ".jpg":
            img.save(path, quality=quality, optimize=True)
        else:
            img.save(path)
    return json.dumps({
        "path": str(path),
        "width": img.width,
        "height": img.height,
        "scale": round(scale, 4),
        "format": save_ext.lstrip("."),
        "cursor": cursor_info,
        "note": "图上红圈+十字中心=鼠标指针尖端（黄点）；cursor.norm 可直接用于 normalized=True 点击",
    }, ensure_ascii=False)


@mcp.tool()
def screen_size() -> str:
    """获取屏幕分辨率。返回 {width, height}。"""
    w, h = _screen_size()
    return json.dumps({"width": w, "height": h})


# ---------------- 鼠标 ----------------

@mcp.tool()
def mouse_position() -> str:
    """查询当前鼠标坐标。返回 {x, y}。"""
    x, y = pyautogui.position()
    return json.dumps({"x": int(x), "y": int(y)})


@mcp.tool()
def mouse_move(x: int, y: int, duration: float = 0.3, normalized: bool = False) -> str:
    """平滑移动鼠标到 (x, y)。返回目标坐标。

    normalized=False：x/y 为物理像素（默认）。
    normalized=True：x/y 为抽象坐标（[0,999] 整数 或 [0,1] 浮点），自动投影到物理像素。
    """
    with _ACTION_LOCK:
        px, py = _project_pair(x, y, normalized=normalized)
        _smooth_move_to(px, py, duration=duration)
    return json.dumps({"moved_to": [px, py], "normalized": normalized})


@mcp.tool()
def mouse_click(x: int, y: int, button: str = "left", normalized: bool = False) -> str:
    """点击 (x, y) 位置。button: left / right / middle。

    normalized=False：x/y 为物理像素（默认）。
    normalized=True：x/y 为抽象坐标（[0,999] 或 [0,1]），自动投影+边缘内缩。
    点击前会先平滑移动到位（模拟人手）。
    """
    with _ACTION_LOCK:
        px, py = _project_pair(x, y, normalized=normalized)
        _smooth_move_to(px, py)
        pyautogui.click(button=button)
    return json.dumps({"clicked": [px, py], "button": button, "normalized": normalized})


@mcp.tool()
def mouse_double_click(x: int, y: int, normalized: bool = False) -> str:
    """双击 (x, y)。normalized=True 时 x/y 为 [0,999] 或 [0,1] 抽象坐标。"""
    with _ACTION_LOCK:
        px, py = _project_pair(x, y, normalized=normalized)
        _smooth_move_to(px, py)
        pyautogui.doubleClick()
    return json.dumps({"double_clicked": [px, py], "normalized": normalized})


@mcp.tool()
def mouse_right_click(x: int, y: int, normalized: bool = False) -> str:
    """右键点击 (x, y)。normalized=True 时 x/y 为 [0,999] 或 [0,1] 抽象坐标。"""
    with _ACTION_LOCK:
        px, py = _project_pair(x, y, normalized=normalized)
        _smooth_move_to(px, py)
        pyautogui.rightClick()
    return json.dumps({"right_clicked": [px, py], "normalized": normalized})


@mcp.tool()
def mouse_drag(x: int, y: int, duration: float = 0.5, normalized: bool = False) -> str:
    """从当前位置拖拽到 (x, y)。用于选中文字、移动对象。
    normalized=True 时 x/y 为 [0,999] 或 [0,1] 抽象坐标。"""
    with _ACTION_LOCK:
        px, py = _project_pair(x, y, normalized=normalized)
        pyautogui.dragTo(px, py, duration=duration, button="left", tween=pyautogui.easeOutQuad)
    return json.dumps({"dragged_to": [px, py], "normalized": normalized})


@mcp.tool()
def mouse_scroll(clicks: int, x: Optional[int] = None, y: Optional[int] = None, normalized: bool = False) -> str:
    """滚动鼠标。clicks 正数向上、负数向下。可选指定在 (x,y) 处滚动。
    normalized=True 时 x/y 为 [0,999] 或 [0,1] 抽象坐标。"""
    with _ACTION_LOCK:
        if x is not None and y is not None:
            px, py = _project_pair(x, y, normalized=normalized)
            pyautogui.scroll(int(clicks), px, py)
        else:
            pyautogui.scroll(int(clicks))
    return json.dumps({"scrolled": int(clicks)})


# ---------------- 键盘 ----------------

@mcp.tool()
def keyboard_write(text: str) -> str:
    """键入纯 ASCII 文本（英文/数字/符号）。输入中文请用 key_paste。"""
    with _ACTION_LOCK:
        pyautogui.typewrite(text, interval=0.02)
    return json.dumps({"typed": text})


@mcp.tool()
def key_paste(text: str) -> str:
    """粘贴任意文本（支持中文、Unicode），经剪贴板实现。推荐用于中文输入。"""
    with _ACTION_LOCK:
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
    return json.dumps({"pasted": text})


@mcp.tool()
def key_press(key: str) -> str:
    """按下单个按键，如 enter / tab / space / esc / up / down / a。"""
    with _ACTION_LOCK:
        pyautogui.press(key)
    return json.dumps({"pressed": key})


@mcp.tool()
def press_hotkey(keys: list) -> str:
    """按一组组合快捷键，如 ["ctrl","c"]、["ctrl","v"]、["alt","tab"]、["ctrl","shift","s"]。"""
    with _ACTION_LOCK:
        keys = [str(k) for k in keys]
        pyautogui.hotkey(*keys)
    return json.dumps({"hotkey": keys})


# ---------------- OCR 语义操作（CUA Grounding 思路：模型不用算坐标） ----------------

_OCR_READER = None


def _get_ocr_reader():
    """懒加载 easyocr reader（中文+英文）。模型缓存已在 ~/.EasyOCR/model。"""
    global _OCR_READER
    if _OCR_READER is None:
        import easyocr
        _OCR_READER = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
    return _OCR_READER


def _ocr_scan(region: "tuple[int,int,int,int] | None" = None, min_conf: float = 0.3) -> list:
    """截图 + OCR，返回 [{text, raw:[x,y], norm:[x,y], conf, bbox}]。

    raw 为物理像素中心；norm 为 [0,1] 归一化（可直接配 normalized=True 点击）。
    """
    with _ACTION_LOCK:
        if region:
            img = pyautogui.screenshot(region=region)
            offset_x, offset_y = region[0], region[1]
        else:
            img = pyautogui.screenshot()
            offset_x, offset_y = 0, 0
    reader = _get_ocr_reader()
    import numpy as np
    results = reader.readtext(np.array(img))  # [(bbox, text, conf)]，bbox 为 4 角点列表
    w, h = _screen_size()
    items = []
    for bbox, text, conf in results:
        if conf < min_conf or not text or not text.strip():
            continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        cx = int(sum(xs) / len(xs)) + offset_x
        cy = int(sum(ys) / len(ys)) + offset_y
        cx, cy = _clamp_coords(cx, cy)
        items.append({
            "text": text.strip(),
            "raw": [cx, cy],
            "norm": [round(cx / max(1, w - 1), 4), round(cy / max(1, h - 1), 4)],
            "conf": round(float(conf), 3),
            "bbox": [[int(p[0]) + offset_x, int(p[1]) + offset_y] for p in bbox],
        })
    return items


@mcp.tool()
def find_text(text: str, min_conf: float = 0.3) -> str:
    """在屏幕上用 OCR 找包含指定文字的内容，不点击。返回所有匹配项
    （text / 物理像素坐标 raw / 归一化坐标 norm / 置信度 conf / 包围盒 bbox）。
    用于：先在模型脑内确认目标文字在哪，再决定点击哪个。
    例：find_text("发送") → 若返回 norm=[0.42,0.88] 表示屏幕右下方那个"发送"按钮。
    """
    items = [it for it in _ocr_scan(min_conf=min_conf) if text.lower() in it["text"].lower()]
    return json.dumps({"query": text, "count": len(items), "matches": items}, ensure_ascii=False)


@mcp.tool()
def ocr_all(min_conf: float = 0.3) -> str:
    """OCR 扫描全屏，返回当前屏幕所有可识别文字及坐标（用于摸清界面结构，
    不点击）。返回 {count, items:[{text, raw, norm, conf, bbox}]}。
    之后要点击某个文字时用 click_text(text)。"""
    items = _ocr_scan(min_conf=min_conf)
    return json.dumps({"count": len(items), "items": items}, ensure_ascii=False)


@mcp.tool()
def click_text(text: str, index: int = 0, min_conf: float = 0.3, button: str = "left") -> str:
    """【语义点击】按文字点击屏幕上的元素，模型/用户完全不需要算坐标。
    内部用 OCR 找到包含该文字的内容 → 取其中心物理像素 → 平滑移动并点击。
    index: 多个匹配时选第几个（默认 0=第一个），用完一次需重新调用。
    示例：click_text("发送") / click_text("确认") / click_text("Yes")。
    找不到时返回 not_found，可改用 ocr_text 看屏幕上有啥。"""
    found = [it for it in _ocr_scan(min_conf=min_conf) if text.lower() in it["text"].lower()]
    if not found:
        return json.dumps({"clicked": False, "reason": "not_found", "query": text}, ensure_ascii=False)
    idx = max(0, min(index, len(found) - 1))
    target = found[idx]
    with _ACTION_LOCK:
        _smooth_move_to(target["raw"][0], target["raw"][1], duration=0.3)
        pyautogui.click(target["raw"][0], target["raw"][1], button=button)
    return json.dumps({
        "clicked": True,
        "matched": target["text"],
        "raw": target["raw"],
        "norm": target["norm"],
        "conf": target["conf"],
        "total_matches": len(found),
        "index_used": idx,
    }, ensure_ascii=False)


if __name__ == "__main__":
    # torch/easyocr 须在主线程完成首次初始化（MCP worker 线程里首载会卡死）。
    # 预热 reader，让 OCR 工具在调用时只跑 readtext（快）。
    try:
        import threading
        _get_ocr_reader()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] OCR reader prewarm failed: {exc}", file=sys.stderr)
    # stdio 模式 MCP server：QwenPaw 会以 stdio 启动本进程
    mcp.run(transport="stdio")
