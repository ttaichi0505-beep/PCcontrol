import struct
import unittest
import zlib

from neai_mouse import ScreenBounds
from neai_screen import ScreenCapture, bgra_to_rgb, encode_png, resize_rgb


class FakeScreenNative:
    def bounds(self):
        return ScreenBounds(0, 0, 4, 2)

    def capture_bgra(self, bounds):
        pixels = bytearray(bounds.width * bounds.height * 4)
        for index in range(bounds.width * bounds.height):
            offset = index * 4
            pixels[offset : offset + 4] = (index * 20) % 256, 40, 200, 255
        return bytes(pixels), bounds.width, bounds.height


class ScreenTests(unittest.TestCase):
    def test_png_round_trip_header(self):
        rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
        png = encode_png(rgb, 2, 2)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        length = struct.unpack(">I", png[8:12])[0]
        self.assertEqual(png[12:16], b"IHDR")
        self.assertEqual(length, 13)

    def test_resize_keeps_aspect(self):
        rgb = bytes(range(3 * 4 * 3))
        resized, width, height = resize_rgb(rgb, 4, 3, 0.5)
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(len(resized), 2 * 2 * 3)

    def test_capture_returns_png_frame(self):
        frame = ScreenCapture(native=FakeScreenNative()).capture(scale=1.0)
        self.assertEqual((frame.width, frame.height), (4, 2))
        self.assertTrue(frame.png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(frame.png), 40)

    def test_bgra_to_rgb_flips_rows(self):
        bgra = bytes([0, 0, 255, 255, 0, 255, 0, 255])
        rgb = bgra_to_rgb(bgra, 2, 1)
        self.assertEqual(rgb[:3], b"\xff\x00\x00")
        self.assertEqual(rgb[3:6], b"\x00\xff\x00")
