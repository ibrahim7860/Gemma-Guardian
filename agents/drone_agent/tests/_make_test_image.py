"""Generate a deterministic synthetic 'aerial-view damaged building' image for end-to-end smoke tests.

Output: /tmp/fieldagent_test_image.jpg
"""
from __future__ import annotations

import sys

import cv2
import numpy as np


def make_image(out_path: str = "/tmp/fieldagent_test_image.jpg") -> str:
    rng = np.random.default_rng(42)
    h, w = 720, 1280
    img = np.full((h, w, 3), (110, 130, 110), dtype=np.uint8)
    img += rng.integers(-12, 12, size=img.shape, dtype=np.int16).astype(np.uint8) * 0
    noise = rng.integers(0, 25, size=img.shape, dtype=np.uint8)
    img = cv2.add(img, noise)

    for x in range(0, w, 220):
        cv2.line(img, (x, 0), (x, h), (95, 95, 95), 18)
    for y in range(0, h, 220):
        cv2.line(img, (0, y), (w, y), (95, 95, 95), 18)

    intact = [(150, 80, 360, 280), (820, 80, 1100, 280), (150, 460, 360, 660)]
    for x1, y1, x2, y2 in intact:
        cv2.rectangle(img, (x1, y1), (x2, y2), (190, 175, 155), -1)
        cv2.rectangle(img, (x1, y1), (x2, y2), (60, 50, 40), 3)
        for rx in range(x1 + 20, x2 - 10, 50):
            cv2.line(img, (rx, y1), (rx, y2), (60, 50, 40), 1)

    dx1, dy1, dx2, dy2 = 480, 80, 760, 320
    cv2.rectangle(img, (dx1, dy1), (dx2, dy2), (130, 100, 80), -1)
    for _ in range(40):
        rx = int(rng.integers(dx1 - 20, dx2 + 20))
        ry = int(rng.integers(dy1 - 20, dy2 + 20))
        cv2.circle(img, (rx, ry), int(rng.integers(4, 14)), (70, 60, 50), -1)
    cv2.line(img, (dx1, dy1), (dx2, dy2), (40, 30, 25), 4)
    cv2.line(img, (dx1 + 60, dy1 + 30), (dx2 - 30, dy2 - 50), (40, 30, 25), 4)

    fx, fy, fr = 980, 540, 60
    for r, c in [(fr + 10, (40, 60, 200)), (fr, (60, 110, 230)), (fr - 18, (90, 180, 245)), (fr - 35, (200, 230, 255))]:
        cv2.circle(img, (fx, fy), r, c, -1)
    for _ in range(220):
        sx = fx + int(rng.normal(0, 22))
        sy = fy - int(rng.integers(20, 180))
        cv2.circle(img, (sx, sy), int(rng.integers(8, 22)), (90, 90, 90), -1)

    cv2.imwrite(out_path, img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out_path


if __name__ == "__main__":
    p = make_image(sys.argv[1] if len(sys.argv) > 1 else "/tmp/fieldagent_test_image.jpg")
    print(p)
