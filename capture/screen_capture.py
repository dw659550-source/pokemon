"""
スクリーンキャプチャモジュール。
mss を使って指定ウィンドウ or 画面領域を PIL Image として返す。
"""
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)

try:
    import mss
    import mss.tools
    HAS_MSS = True
except ImportError:
    HAS_MSS = False
    logger.warning("mss not installed. Screen capture unavailable.")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pygetwindow as gw
    HAS_GW = True
except ImportError:
    HAS_GW = False


class WindowInfo(NamedTuple):
    title: str
    left: int
    top: int
    width: int
    height: int


def list_windows() -> list[WindowInfo]:
    """表示中のウィンドウ一覧を返す（タイトルが空のものは除外）"""
    if not HAS_GW:
        return []
    try:
        wins = []
        for w in gw.getAllWindows():
            if w.title and w.width > 0 and w.height > 0:
                wins.append(WindowInfo(
                    title=w.title,
                    left=w.left, top=w.top,
                    width=w.width, height=w.height,
                ))
        return wins
    except Exception as e:
        logger.error("list_windows: %s", e)
        return []


def find_window(title_pattern: str) -> WindowInfo | None:
    """タイトルに部分一致するウィンドウを返す（大文字小文字無視）"""
    pattern = title_pattern.lower()
    for w in list_windows():
        if pattern in w.title.lower():
            return w
    return None


def capture_region(left: int, top: int, width: int, height: int):
    """
    画面の指定領域を PIL Image として返す。
    mss が未インストールの場合は None を返す。
    """
    if not HAS_MSS or not HAS_PIL:
        logger.error("mss / Pillow が未インストールです")
        return None

    try:
        with mss.mss() as sct:
            monitor = {"left": left, "top": top, "width": width, "height": height}
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            return img
    except Exception as e:
        logger.error("capture_region: %s", e)
        return None


def capture_window(window: WindowInfo, padding: int = 0):
    """
    指定ウィンドウ領域を PIL Image として返す。
    """
    left   = max(0, window.left   - padding)
    top    = max(0, window.top    - padding)
    width  = window.width  + padding * 2
    height = window.height + padding * 2
    return capture_region(left, top, width, height)


def capture_primary_monitor():
    """プライマリモニター全体を PIL Image として返す"""
    if not HAS_MSS or not HAS_PIL:
        return None
    try:
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])  # monitors[0]=全画面, [1]=プライマリ
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            return img
    except Exception as e:
        logger.error("capture_primary_monitor: %s", e)
        return None


def capture_window_direct(title: str):
    """
    PrintWindow API でウィンドウの内容を直接キャプチャ。
    他のウィンドウが重なっていても正しく取得できる。
    pywin32 が必要: pip install pywin32
    """
    if not HAS_PIL:
        return None
    try:
        import win32gui
        import win32ui
    except ImportError:
        logger.warning("pywin32 が必要: pip install pywin32")
        return None
    try:
        # タイトル部分一致でHWND検索
        found = []
        def _cb(hwnd, _):
            if title.lower() in win32gui.GetWindowText(hwnd).lower():
                found.append(hwnd)
        win32gui.EnumWindows(_cb, None)
        if not found:
            return None
        hwnd = found[0]

        rect = win32gui.GetClientRect(hwnd)
        w, h = rect[2], rect[3]
        if w <= 0 or h <= 0:
            return None

        hwnd_dc   = win32gui.GetWindowDC(hwnd)
        mfc_dc    = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc   = mfc_dc.CreateCompatibleDC()
        bmp       = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)

        # win32gui.PrintWindow は pywin32 のバージョンによっては未定義のため ctypes で呼ぶ
        import ctypes
        PW_RENDERFULLCONTENT = 0x00000002
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)

        info   = bmp.GetInfo()
        raw    = bmp.GetBitmapBits(True)
        img    = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                                  raw, "raw", "BGRX", 0, 1)

        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        win32gui.DeleteObject(bmp.GetHandle())
        return img
    except Exception as e:
        logger.error("capture_window_direct: %s", e)
        return None
