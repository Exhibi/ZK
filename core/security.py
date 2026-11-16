
import base64
import ctypes
import os
from ctypes import wintypes


if os.name != "nt":
    raise RuntimeError("当前密码保护功能仅支持 Windows。")


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)

crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptProtectData.restype = wintypes.BOOL

crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptUnprotectData.restype = wintypes.BOOL

kernel32.LocalFree.argtypes = [ctypes.c_void_p]
kernel32.LocalFree.restype = ctypes.c_void_p


def _make_blob(data):
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    )
    return blob, buffer


def _free_blob(blob):
    if blob.pbData:
        kernel32.LocalFree(
            ctypes.cast(blob.pbData, ctypes.c_void_p)
        )
        blob.pbData = None
        blob.cbData = 0


def protect_text(text):
    """使用 Windows DPAPI 加密文本，返回 Base64 字符串。"""

    if not text:
        return ""

    raw = str(text).encode("utf-8")
    source, source_buffer = _make_blob(raw)
    output = DATA_BLOB()

    success = crypt32.CryptProtectData(
        ctypes.byref(source),
        "LDControl Account Password",
        None,
        None,
        None,
        0,
        ctypes.byref(output)
    )

    if not success:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        encrypted = ctypes.string_at(
            output.pbData,
            output.cbData
        )
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        _free_blob(output)


def unprotect_text(encrypted_text):
    """解密 protect_text() 生成的密码。"""

    if not encrypted_text:
        return ""

    try:
        encrypted = base64.b64decode(
            encrypted_text,
            validate=True
        )
    except Exception as exc:
        raise ValueError("密码密文不是有效的 Base64 数据") from exc

    source, source_buffer = _make_blob(encrypted)
    output = DATA_BLOB()
    description = wintypes.LPWSTR()

    success = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        ctypes.byref(description),
        None,
        None,
        None,
        0,
        ctypes.byref(output)
    )

    if not success:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        raw = ctypes.string_at(
            output.pbData,
            output.cbData
        )
        return raw.decode("utf-8")
    finally:
        _free_blob(output)

        if description:
            kernel32.LocalFree(
                ctypes.cast(description, ctypes.c_void_p)
            )
