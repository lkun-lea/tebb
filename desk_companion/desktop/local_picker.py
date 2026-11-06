"""独立进程中的 Windows Common Item Dialog，不锁定桌宠窗口。"""
from __future__ import annotations

import ctypes as C
import json
import sys
import uuid


class GUID(C.Structure):
    _fields_ = [('data', C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def windows_paths(kind, probe=False):
    if kind not in ('file', 'folder'):
        raise ValueError('Unsupported selection type')
    user = C.WinDLL('user32', use_last_error=True)
    ole = C.OleDLL('ole32')
    # 必须在窗口创建之前设置；线程设置兼容宿主已有的进程 DPI 模式。
    user.SetProcessDpiAwarenessContext.argtypes = [C.c_void_p]
    user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    user.SetThreadDpiAwarenessContext.argtypes = [C.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = C.c_void_p
    previous = user.SetThreadDpiAwarenessContext(C.c_void_p(-4))
    ole.CoInitializeEx(None, 2)  # STA
    ole.CoCreateInstance.argtypes = [C.POINTER(GUID), C.c_void_p, C.c_uint32, C.POINTER(GUID), C.POINTER(C.c_void_p)]
    ole.CoTaskMemFree.argtypes = [C.c_void_p]
    dialog = C.c_void_p()
    array = C.c_void_p()

    def call(obj, slot, *arguments):
        types, values = zip(*arguments) if arguments else ((), ())
        table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
        method = C.WINFUNCTYPE(C.c_long, C.c_void_p, *types)(table[slot])
        return method(obj, *values)

    def checked(result):
        if result < 0:
            raise OSError(f'Windows dialog HRESULT 0x{result & 0xffffffff:08x}')

    try:
        cls = GUID.parse('DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7')
        iid = GUID.parse('D57C7288-D4AD-4768-BE02-9D969532D960')
        checked(ole.CoCreateInstance(C.byref(cls), None, 1, C.byref(iid), C.byref(dialog)))
        options = C.c_uint32()
        checked(call(dialog, 10, (C.POINTER(C.c_uint32), C.byref(options))))
        # IFileDialog: FORCEFILESYSTEM | PATHMUSTEXIST；文件夹使用 PICKFOLDERS。
        flags = options.value | 0x40 | 0x800 | (0x20 if kind == 'folder' else 0x200 | 0x1000)
        checked(call(dialog, 9, (C.c_uint32, flags)))
        checked(call(dialog, 17, (C.c_wchar_p, '选择要读取的文件夹' if kind == 'folder' else '选择要读取的文件')))
        if probe:
            user.GetThreadDpiAwarenessContext.restype = C.c_void_p
            user.AreDpiAwarenessContextsEqual.argtypes = [C.c_void_p, C.c_void_p]
            current = user.GetThreadDpiAwarenessContext()
            return {'modern_dialog': True, 'options': flags,
                    'per_monitor_v2': bool(user.AreDpiAwarenessContextsEqual(current, C.c_void_p(-4)))}
        status = call(dialog, 3, (C.c_void_p, None))  # 无桌宠 owner，不禁用主窗，不置顶。
        if status & 0xffffffff == 0x800704c7:
            return []
        checked(status)
        checked(call(dialog, 27, (C.POINTER(C.c_void_p), C.byref(array))))
        count = C.c_uint32()
        checked(call(array, 7, (C.POINTER(C.c_uint32), C.byref(count))))
        paths = []
        for index in range(count.value):
            item = C.c_void_p()
            name = C.c_void_p()
            try:
                checked(call(array, 8, (C.c_uint32, index), (C.POINTER(C.c_void_p), C.byref(item))))
                checked(call(item, 5, (C.c_uint32, 0x80058000), (C.POINTER(C.c_void_p), C.byref(name))))
                paths.append(C.wstring_at(name))
            finally:
                if name: ole.CoTaskMemFree(name)
                if item: call(item, 2)
        return paths
    finally:
        if array: call(array, 2)
        if dialog: call(dialog, 2)
        ole.CoUninitialize()
        if previous: user.SetThreadDpiAwarenessContext(previous)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(windows_paths(sys.argv[-1], probe='--probe' in sys.argv), ensure_ascii=False))
