"""把 pywebview 窗放到 WinForms GUI 线程上显示/移动，避免宠物线程卡住。"""
from __future__ import annotations

import ctypes
import threading
from ctypes import c_int, c_int64, c_uint, c_void_p

# 使用独立 DLL 实例，禁止修改 pywebview 共用的 ctypes.windll.user32 函数签名。
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetWindowPos.argtypes = [c_void_p, c_void_p, c_int, c_int, c_int, c_int, c_uint]
user32.SetWindowPos.restype = ctypes.c_int
user32.SetForegroundWindow.argtypes = [c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_int
user32.GetDpiForWindow.argtypes = [c_void_p]
user32.GetDpiForWindow.restype = c_uint
user32.GetAncestor.argtypes = [c_void_p, c_uint]
user32.GetAncestor.restype = c_void_p

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_TOPMOST = c_void_p(-1)
HWND_NOTOPMOST = c_void_p(-2)
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
GA_ROOT = 2
_IS_64 = ctypes.sizeof(c_void_p) == 8
if _IS_64:
    _get_long = user32.GetWindowLongPtrW
    _set_long = user32.SetWindowLongPtrW
    _get_long.argtypes = [c_void_p, c_int]
    _get_long.restype = c_int64
    _set_long.argtypes = [c_void_p, c_int, c_int64]
    _set_long.restype = c_int64
else:
    _get_long = user32.GetWindowLongW
    _set_long = user32.SetWindowLongW
    _get_long.argtypes = [c_void_p, c_int]
    _get_long.restype = c_int
    _set_long.argtypes = [c_void_p, c_int, c_int]
    _set_long.restype = c_int


_HWND: dict[int, int] = {}


def as_hwnd(hwnd: int) -> int:
    """Win32 HWND 只有低 32 位。符号扩展的 Python int 会让 GetDpiForWindow 返回 0。"""
    return int(hwnd) & 0xFFFFFFFF


def form_of(window):
    if window is None:
        raise RuntimeError("WebView 窗口还不存在。")
    native = window.native
    if native is None:
        raise RuntimeError("WebView 窗口还没有 native 句柄。")
    return native


def form_hwnd(window) -> int:
    handle = form_of(window).Handle
    if hasattr(handle, "ToInt64"):
        return as_hwnd(int(handle.ToInt64()))
    return as_hwnd(int(handle))


def cache_hwnd(window) -> int:
    """必须在 WinForms GUI 线程上调用，供宠物线程只走 Win32。"""
    hwnd = form_hwnd(window)
    _HWND[id(window)] = hwnd
    return hwnd


def cached_hwnd(window) -> int | None:
    if window is None:
        return None
    return _HWND.get(id(window))


def invoke(form, fn, timeout: float = 8) -> None:
    """后台线程只用 BeginInvoke，禁止同步 Invoke（会和 WebView Focus 死锁）。"""
    from System import Action

    if not getattr(form, "InvokeRequired", False):
        fn()
        return
    done = threading.Event()
    box: dict = {"err": None}

    def _wrap() -> None:
        try:
            fn()
        except Exception as exc:
            box["err"] = exc
        finally:
            done.set()

    form.BeginInvoke(Action(_wrap))
    if not done.wait(timeout):
        raise RuntimeError(f"WinForms 在 {timeout:.0f} 秒内没有执行完，判定卡死。")
    if box["err"] is not None:
        raise box["err"]


def _hwnd_of_form(form) -> int:
    handle = form.Handle
    if hasattr(handle, "ToInt64"):
        return as_hwnd(int(handle.ToInt64()))
    return as_hwnd(int(handle))


def hwnd_dpi_scale(hwnd: int) -> float:
    """逻辑 CSS 像素到屏幕物理像素。必须用仍然有效的 HWND（宠物窗，不要用可能被重建的气泡窗）。"""
    if not hwnd:
        raise RuntimeError("没有窗口句柄，无法读取 DPI。")
    dpi = int(user32.GetDpiForWindow(as_hwnd(hwnd)))
    if dpi <= 0:
        raise RuntimeError(f"GetDpiForWindow 返回 {dpi}，无法换算气泡尺寸。")
    return dpi / 96.0


def root_hwnd(hwnd: int) -> int:
    if not hwnd:
        return 0
    root = user32.GetAncestor(hwnd, GA_ROOT)
    return int(root) if root else hwnd


def _apply_exstyle(hwnd: int, style: int) -> None:
    hwnd = as_hwnd(hwnd)
    _set_long(hwnd, GWL_EXSTYLE, style)
    user32.SetWindowPos(
        hwnd,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def apply_tool_window(form) -> None:
    """工具窗：任务栏不出现 Python / 气泡图标。
    改 ShowInTaskbar 可能重建 HWND，调用方必须在这之后重新 cache_hwnd。
    """
    form.ShowInTaskbar = False
    hwnd = _hwnd_of_form(form)
    style = int(_get_long(hwnd, GWL_EXSTYLE))
    style = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    _apply_exstyle(hwnd, style)


def apply_app_window(form) -> None:
    """普通窗：出现在任务栏，可最小化。"""
    form.ShowInTaskbar = True
    hwnd = _hwnd_of_form(form)
    style = int(_get_long(hwnd, GWL_EXSTYLE))
    style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
    _apply_exstyle(hwnd, style)


def prepare_transparent_form(form) -> None:
    """用品红做色键抠掉矩形窗底。WebView2 分层透明不稳定，卡片本身不能再用纯白。"""
    from System.Drawing import Color
    from System.Windows.Forms import FormStartPosition

    key = Color.FromArgb(255, 0, 255)
    form.StartPosition = FormStartPosition.Manual
    form.BackColor = key
    form.TransparencyKey = key
    webview = getattr(form, "webview", None)
    if webview is not None:
        webview.DefaultBackgroundColor = key


def refresh_transparent(form) -> None:
    """改尺寸后重申色键，避免缩小露出白底。"""
    from System import Action
    from System.Drawing import Color

    key = Color.FromArgb(255, 0, 255)

    def _do() -> None:
        form.BackColor = key
        form.TransparencyKey = key
        webview = getattr(form, "webview", None)
        if webview is not None:
            webview.DefaultBackgroundColor = key
        form.Invalidate()

    if getattr(form, "InvokeRequired", False):
        form.BeginInvoke(Action(_do))
        return
    _do()


def show_form(
    window,
    activate: bool = False,
    *,
    tool: bool = True,
    topmost: bool = True,
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> None:
    """显示窗口。位置尺寸必须在 Show 之前写入，否则会先闪到 WinForms 记住的旧坐标。
    tool 仅保留给调用方语义，样式已在 _prepare_form 设过，禁止每次 Show 改 EXSTYLE。
    """
    form = form_of(window)
    placed = None not in (x, y, width, height)

    def _do() -> None:
        if placed:
            from System.Windows.Forms import FormStartPosition

            form.StartPosition = FormStartPosition.Manual
            form.Left = int(x)
            form.Top = int(y)
            form.Width = int(width)
            form.Height = int(height)
        form.Show()
        form.TopMost = bool(topmost)
        hwnd = cache_hwnd(window)
        if placed:
            ok = user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST if topmost else HWND_NOTOPMOST,
                int(x),
                int(y),
                int(width),
                int(height),
                SWP_NOACTIVATE,
            )
            if not ok:
                raise RuntimeError(f"SetWindowPos 失败（GetLastError={ctypes.GetLastError()}）。")
            refresh_transparent(form)
        form.Opacity = 1
        if activate:
            user32.SetForegroundWindow(hwnd)

    invoke(form, _do)


def hide_form(window) -> None:
    form = form_of(window)

    def _do() -> None:
        form.Opacity = 0
        form.Hide()
        form.Visible = False
        cache_hwnd(window)

    invoke(form, _do)


def form_visible(window) -> bool:
    """只查已缓存的 HWND，禁止宠物线程去读 WinForms.Handle。"""
    hwnd = cached_hwnd(window)
    if not hwnd:
        return False
    return bool(user32.IsWindowVisible(as_hwnd(hwnd)))


def move_form(window, x: int, y: int, *, topmost: bool = True) -> None:
    """x/y 是屏幕物理像素。不带 SWP_SHOWWINDOW，避免把已隐藏的窗又拉出来。"""
    hwnd = cached_hwnd(window)
    if not hwnd:
        raise RuntimeError("窗口句柄还没缓存，不能移动。")
    insert = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    ok = user32.SetWindowPos(
        as_hwnd(hwnd),
        insert,
        int(x),
        int(y),
        0,
        0,
        SWP_NOSIZE | SWP_NOACTIVATE,
    )
    if not ok:
        raise RuntimeError(f"SetWindowPos 失败（GetLastError={ctypes.GetLastError()}）。")


def place_form(
    window,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    transparent: bool = False,
) -> None:
    """移动并改尺寸，物理像素。"""
    hwnd = cached_hwnd(window)
    if not hwnd:
        raise RuntimeError("窗口句柄还没缓存，不能改尺寸。")
    ok = user32.SetWindowPos(
        as_hwnd(hwnd),
        HWND_TOPMOST,
        int(x),
        int(y),
        int(width),
        int(height),
        SWP_NOACTIVATE,
    )
    if not ok:
        raise RuntimeError(f"SetWindowPos 失败（GetLastError={ctypes.GetLastError()}）。")
    if transparent:
        refresh_transparent(form_of(window))


def ensure_ready(window, name: str, seconds: float = 15) -> None:
    """等页面就绪。禁止在宠物/回调线程里读 WinForms.Handle。"""
    if window is None:
        raise RuntimeError(f"{name} 窗口还不存在。")
    if not window.events.shown.wait(seconds):
        raise RuntimeError(f"{name} 窗口 {seconds:.0f} 秒内没有 shown。")
    if not window.events._pywebviewready.wait(seconds):
        raise RuntimeError(f"{name} 页面 {seconds:.0f} 秒内没有就绪，无法对话。")


def enable_webview_context_menu(window) -> None:
    """pywebview 把系统右键菜单绑在 debug 上。看板要复制粘贴，必须单独打开。"""
    form = form_of(window)

    def _do() -> None:
        browser = getattr(form, "browser", None)
        control = getattr(browser, "webview", None) if browser is not None else None
        if control is None:
            raise RuntimeError("看板没有 WebView2 控件，无法打开右键菜单。")
        core = control.CoreWebView2
        if core is None:
            raise RuntimeError("看板 WebView2 核心还没就绪，无法打开右键菜单。")
        core.Settings.AreDefaultContextMenusEnabled = True

    invoke(form, _do)
