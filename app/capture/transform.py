from __future__ import annotations

import cv2
import numpy as np


def unrotate_norm(nx: float, ny: float, rotation: int) -> tuple[float, float]:
    """把预览点击坐标从旋转后画面还原到相机原图。"""
    x = max(0.0, min(1.0, float(nx)))
    y = max(0.0, min(1.0, float(ny)))
    angle = int(rotation) % 360
    if angle == 90:
        return y, 1.0 - x
    if angle == 180:
        return 1.0 - x, 1.0 - y
    if angle == 270:
        return 1.0 - y, x
    return x, y


def apply_view(frame: np.ndarray, rotation: int = 0, zoom: float = 1.0) -> np.ndarray:
    # zoom 留给旧调用兼容；变焦已改走相机 --camera-zoom，这里不再裁切。
    _ = zoom
    return _rotate(frame, rotation)


def _rotate(frame: np.ndarray, rotation: int) -> np.ndarray:
    angle = int(rotation) % 360
    if angle == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame
