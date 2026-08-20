from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


class RecorderError(RuntimeError):
    pass


class VideoRecorder:
    def __init__(self) -> None:
        self._writer: cv2.VideoWriter | None = None
        self._path: Path | None = None
        self._size: tuple[int, int] = (0, 0)
        self._lock = threading.Lock()
        self.recording = False
        self.started_at: datetime | None = None
        self.frame_count = 0

    def start(self, output_dir: Path, size: tuple[int, int], fps: float = 20.0) -> Path:
        if self.recording:
            raise RecorderError("已经在录像")
        stamp = datetime.now().strftime("录像_%Y%m%d_%H%M%S")
        path = output_dir / "工作台" / f"{stamp}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        width, height = size
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
        if not writer.isOpened():
            raise RecorderError("无法创建录像文件")
        self._writer = writer
        self._path = path
        self._size = (width, height)
        self.recording = True
        self.started_at = datetime.now()
        self.frame_count = 0
        return path

    def write(self, frame: np.ndarray) -> None:
        with self._lock:
            if not self.recording or self._writer is None:
                return
            height, width = frame.shape[:2]
            if (width, height) != self._size and self._size[0] > 0:
                frame = cv2.resize(frame, self._size)
            self._writer.write(frame)
            self.frame_count += 1

    def stop(self) -> Path | None:
        with self._lock:
            writer = self._writer
            path = self._path
            self._writer = None
            self._path = None
            self.recording = False
        if writer is not None:
            writer.release()
        return path


def snapshot_path(output_dir: Path, prefix: str = "抓拍") -> Path:
    stamp = datetime.now().strftime(f"{prefix}_%Y%m%d_%H%M%S")
    folder = output_dir / "工作台"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{stamp}.jpg"
