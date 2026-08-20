from __future__ import annotations

import time

import cv2
import numpy as np
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel


class PreviewWidget(QLabel):
    tapped = Signal(float, float)

    def __init__(self, placeholder: str = "预览未开启") -> None:
        super().__init__(placeholder)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480, 320)
        self.setStyleSheet("background:#0f1115; border:1px solid #2e3440; border-radius:8px; color:#6b7280;")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._pixmap: QPixmap | None = None
        self._placeholder = placeholder
        self._focus: tuple[float, float, float] | None = None

    def show_frame(self, frame: np.ndarray) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self._pixmap = QPixmap.fromImage(image.copy())
        self._rescale()

    def mark_focus(self, nx: float, ny: float) -> None:
        self._focus = (nx, ny, time.time())
        self._rescale()

    def reset(self, text: str | None = None) -> None:
        self._pixmap = None
        self._focus = None
        self.setText(text or self._placeholder)
        self.setPixmap(QPixmap())

    def mousePressEvent(self, event) -> None:
        mapped = self._map_to_frame(event.position().x(), event.position().y())
        if mapped is None:
            return
        self.mark_focus(*mapped)
        self.tapped.emit(*mapped)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pixmap is not None:
            self._rescale()

    def _map_to_frame(self, px: float, py: float) -> tuple[float, float] | None:
        current = self.pixmap()
        if current is None or current.isNull() or self._pixmap is None:
            return None
        x0 = (self.width() - current.width()) / 2
        y0 = (self.height() - current.height()) / 2
        if px < x0 or py < y0 or px >= x0 + current.width() or py >= y0 + current.height():
            return None
        return (px - x0) / current.width(), (py - y0) / current.height()

    def _rescale(self) -> None:
        if self._pixmap is None:
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if self._focus is not None:
            nx, ny, stamp = self._focus
            if time.time() - stamp < 1.6:
                painter = QPainter(scaled)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(QColor("#fbbf24"), 2))
                size = max(28, min(scaled.width(), scaled.height()) // 10)
                cx = int(nx * scaled.width())
                cy = int(ny * scaled.height())
                painter.drawRect(QRect(cx - size // 2, cy - size // 2, size, size))
                painter.end()
            else:
                self._focus = None
        self.setPixmap(scaled)
        self.setText("")
