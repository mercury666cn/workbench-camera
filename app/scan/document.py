from __future__ import annotations

import cv2
import numpy as np


def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def detect_document(frame: np.ndarray) -> np.ndarray | None:
    ratio = 800 / max(frame.shape[:2])
    if ratio > 1:
        ratio = 1
    small = cv2.resize(frame, None, fx=ratio, fy=ratio) if ratio < 1 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, None, iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:8]
    area_min = small.shape[0] * small.shape[1] * 0.12
    for contour in contours:
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(approx) >= area_min:
            pts = approx.reshape(4, 2).astype(np.float32) / ratio
            return order_points(pts)
    return None


def warp_document(frame: np.ndarray, quad: np.ndarray | None = None) -> np.ndarray:
    if quad is None:
        quad = detect_document(frame)
    if quad is None:
        return enhance(frame)
    tl, tr, br, bl = quad
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    width = int(max(width_a, width_b))
    height = int(max(height_a, height_b))
    width = max(width, 200)
    height = max(height, 200)
    dest = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(quad.astype(np.float32), dest)
    warped = cv2.warpPerspective(frame, matrix, (width, height))
    return enhance(warped)


def enhance(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_ch = clahe.apply(l_ch)
    merged = cv2.merge((l_ch, a_ch, b_ch))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def overlay_quad(frame: np.ndarray, quad: np.ndarray | None) -> np.ndarray:
    if quad is None:
        return frame
    drawn = frame.copy()
    pts = quad.astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(drawn, [pts], True, (61, 139, 253), 3)
    return drawn


def resize_max_side(image: np.ndarray, max_side: int) -> np.ndarray:
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
