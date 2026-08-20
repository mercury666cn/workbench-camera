from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from app.device.adb_phone import AdbPhone
from app.device.scrcpy_camera_client import CameraClientError, ScrcpyCameraClient


FrameCallback = Callable[[np.ndarray], None]
ErrorCallback = Callable[[str], None]


class CameraError(RuntimeError):
    pass


class CameraStream:
    def __init__(self, phone: AdbPhone, camera_id: str | None = None) -> None:
        self.phone = phone
        self.camera_id = camera_id
        self.camera_size = "1920x1080"
        self.camera_fps = 24
        self.camera_zoom = 1.0
        self._client: ScrcpyCameraClient | None = None
        self._on_frame: FrameCallback | None = None
        self._on_error: ErrorCallback | None = None

    @property
    def running(self) -> bool:
        return bool(self._client and self._client.running and self._client.camera_active)

    def set_callbacks(self, on_frame: FrameCallback | None, on_error: ErrorCallback | None) -> None:
        self._on_frame = on_frame
        self._on_error = on_error
        if self._client is not None:
            self._client.set_callbacks(on_frame, on_error)

    def start(self) -> None:
        if self.running:
            return
        if self._client is not None and self._client.running:
            try:
                self._client.resume_camera()
            except CameraClientError as exc:
                raise CameraError(_clean_error(str(exc))) from exc
            return
        if self._client is not None:
            self._client.stop()
            self._client = None
        client = ScrcpyCameraClient(
            self.phone,
            camera_id=self.camera_id or "0",
            camera_size=self.camera_size,
            camera_fps=self.camera_fps,
            camera_zoom=self.camera_zoom,
        )
        client.set_callbacks(self._on_frame, self._on_error)
        try:
            client.start()
        except CameraClientError as exc:
            raise CameraError(_clean_error(str(exc))) from exc
        self._client = client

    def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.pause_camera()
            except CameraClientError as exc:
                raise CameraError(_clean_error(str(exc))) from exc

    def shutdown(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            client.stop()

    def snapshot(self) -> np.ndarray:
        if not self.running or self._client is None:
            raise CameraError("请先开启预览")
        try:
            return self._client.snapshot()
        except CameraClientError as exc:
            raise CameraError(str(exc)) from exc

    def set_zoom(self, zoom: float) -> None:
        self.camera_zoom = max(1.0, min(float(zoom or 1.0), 4.0))
        if self._client is not None:
            self._client.set_zoom(self.camera_zoom)

    def tap_focus(self, nx: float, ny: float) -> None:
        if self._client is not None:
            self._client.tap_focus(nx, ny)

    def refocus(self) -> None:
        if self._client is not None:
            self._client.refocus()


def encode_jpeg(frame: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise CameraError("无法编码图片")
    return buf.tobytes()


def save_jpeg(frame: np.ndarray, path: Path, quality: int = 92) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_jpeg(frame, quality))
    return path


def _clean_error(message: str) -> str:
    text = message.strip()
    if text == "Aborted":
        return "相机服务未完整启动。请点「重新检测」；程序会重新校验并部署服务。"
    if "Could not open camera" in text or "Failed to open camera" in text:
        return "后置相机打不开。华为可能未放行 Camera2 相机源，软件不会点亮屏幕凑合。\n" + text
    return text
