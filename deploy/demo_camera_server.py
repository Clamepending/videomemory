#!/usr/bin/env python3
"""Tiny HTTP snapshot server that serves a red-marker demo image.

The frame includes a small animated badge in the corner so VideoMemory sees
non-duplicate frames during end-to-end Docker testing.
"""

import time
from http.server import BaseHTTPRequestHandler, HTTPServer


def _build_demo_ppm(width: int = 320, height: int = 240, *, pulse_on: bool) -> bytes:
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    pixels = bytearray()
    center_x = width // 2
    center_y = height // 2
    radius_sq = 45 * 45

    badge_color = (0, 140, 255) if pulse_on else (255, 220, 0)
    badge_shadow = (40, 40, 40)

    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            if dx * dx + dy * dy <= radius_sq:
                pixels.extend((255, 0, 0))
            elif 70 <= x <= 250 and 80 <= y <= 160:
                pixels.extend((245, 245, 245))
            elif 12 <= x <= 72 and 12 <= y <= 72:
                pixels.extend(badge_color)
            elif 8 <= x <= 76 and 8 <= y <= 76:
                pixels.extend(badge_shadow)
            else:
                pixels.extend((225, 225, 225))
    return header + pixels


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/snapshot.jpg", "/snapshot.png", "/"}:
            self.send_response(404)
            self.end_headers()
            return

        ppm_bytes = _build_demo_ppm(pulse_on=bool(int(time.time()) % 2))

        self.send_response(200)
        self.send_header("Content-Type", "image/x-portable-pixmap")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(ppm_bytes)))
        self.end_headers()
        self.wfile.write(ppm_bytes)

    def log_message(self, format, *args):
        return


def main() -> None:
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
