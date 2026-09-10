"""Capture the shared virtual desktop as PNG using Windows GDI (stdlib only)."""

from __future__ import annotations

import ctypes
import os
import struct
import zlib
from dataclasses import dataclass
from typing import Protocol

from neai_mouse import ScreenBounds


SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0


@dataclass(frozen=True)
class ScreenFrame:
    png: bytes
    width: int
    height: int
    bounds: ScreenBounds
    scale: float


class ScreenCaptureNative(Protocol):
    def bounds(self) -> ScreenBounds: ...

    def capture_bgra(self, bounds: ScreenBounds) -> tuple[bytes, int, int]: ...


class GDIScreenCaptureNative:
    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("NeAI screen capture requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user32.GetDC.restype = ctypes.c_void_p
        self.user32.ReleaseDC.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        self.gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        self.gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
        self.gdi32.SelectObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        self.gdi32.SelectObject.restype = ctypes.c_void_p
        self.gdi32.BitBlt.restype = ctypes.c_bool
        self.gdi32.DeleteObject.argtypes = (ctypes.c_void_p,)
        self.gdi32.DeleteDC.argtypes = (ctypes.c_void_p,)
        self.gdi32.GetDIBits.restype = ctypes.c_int

    def bounds(self) -> ScreenBounds:
        from neai_mouse import SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN

        return ScreenBounds(
            self.user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            self.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
        )

    def capture_bgra(self, bounds: ScreenBounds) -> tuple[bytes, int, int]:
        desktop_dc = self.user32.GetDC(None)
        if not desktop_dc:
            raise ctypes.WinError(ctypes.get_last_error())
        memory_dc = self.gdi32.CreateCompatibleDC(desktop_dc)
        bitmap = self.gdi32.CreateCompatibleBitmap(desktop_dc, bounds.width, bounds.height)
        if not memory_dc or not bitmap:
            self._release(desktop_dc, memory_dc, bitmap, None)
            raise RuntimeError("failed to allocate GDI capture resources")
        old_bitmap = self.gdi32.SelectObject(memory_dc, bitmap)
        copied = self.gdi32.BitBlt(
            memory_dc,
            0,
            0,
            bounds.width,
            bounds.height,
            desktop_dc,
            bounds.left,
            bounds.top,
            SRCCOPY,
        )
        if not copied:
            self._release(desktop_dc, memory_dc, bitmap, old_bitmap)
            raise RuntimeError("BitBlt screen capture failed")

        header = struct.pack(
            "<IIIHHIIIIII",
            40,
            bounds.width,
            bounds.height,
            1,
            32,
            BI_RGB,
            0,
            0,
            0,
            0,
            0,
        )
        buffer_size = bounds.width * bounds.height * 4
        pixel_buffer = ctypes.create_string_buffer(buffer_size)
        bitmap_info = header + b"\x00" * 12
        lines = self.gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            bounds.height,
            pixel_buffer,
            bitmap_info,
            DIB_RGB_COLORS,
        )
        self._release(desktop_dc, memory_dc, bitmap, old_bitmap)
        if lines == 0:
            raise RuntimeError("GetDIBits screen capture failed")
        return pixel_buffer.raw, bounds.width, bounds.height

    def _release(self, desktop_dc, memory_dc, bitmap, old_bitmap) -> None:
        if old_bitmap:
            self.gdi32.SelectObject(memory_dc, old_bitmap)
        if bitmap:
            self.gdi32.DeleteObject(bitmap)
        if memory_dc:
            self.gdi32.DeleteDC(memory_dc)
        if desktop_dc:
            self.user32.ReleaseDC(None, desktop_dc)


def bgra_to_rgb(data: bytes, width: int, height: int) -> bytes:
    row_bytes = width * 4
    rgb = bytearray(width * height * 3)
    write = 0
    for row in range(height - 1, -1, -1):
        start = row * row_bytes
        for column in range(width):
            offset = start + column * 4
            rgb[write : write + 3] = data[offset + 2], data[offset + 1], data[offset]
            write += 3
    return bytes(rgb)


def resize_rgb(data: bytes, width: int, height: int, scale: float) -> tuple[bytes, int, int]:
    if scale >= 0.999:
        return data, width, height
    target_width = max(1, round(width * scale))
    target_height = max(1, round(height * scale))
    resized = bytearray(target_width * target_height * 3)
    for y in range(target_height):
        source_y = min(height - 1, round(y / scale))
        for x in range(target_width):
            source_x = min(width - 1, round(x / scale))
            source_index = (source_y * width + source_x) * 3
            target_index = (y * target_width + x) * 3
            resized[target_index : target_index + 3] = data[source_index : source_index + 3]
    return bytes(resized), target_width, target_height


def encode_png(rgb: bytes, width: int, height: int) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = bytearray()
    row_size = width * 3
    for row in range(height):
        raw.append(0)
        start = row * row_size
        raw.extend(rgb[start : start + row_size])
    compressed = zlib.compress(bytes(raw), level=6)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


class ScreenCapture:
    def __init__(self, native: ScreenCaptureNative | None = None) -> None:
        self.native = native or GDIScreenCaptureNative()

    def capture(self, scale: float = 1.0) -> ScreenFrame:
        if not 0.1 <= scale <= 1.0:
            raise ValueError("scale must be between 0.1 and 1.0")
        bounds = self.native.bounds()
        bgra, width, height = self.native.capture_bgra(bounds)
        rgb = bgra_to_rgb(bgra, width, height)
        rgb, out_width, out_height = resize_rgb(rgb, width, height, scale)
        return ScreenFrame(
            png=encode_png(rgb, out_width, out_height),
            width=out_width,
            height=out_height,
            bounds=bounds,
            scale=scale,
        )
