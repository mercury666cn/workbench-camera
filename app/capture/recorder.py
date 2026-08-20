from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import cv2
import numpy as np


class RecorderError(RuntimeError):
    pass


class VideoRecorder:
    _QUEUE_SIZE = 8
    _ENCODERS = {
        "h264": {
            "auto": ("h264_nvenc", "h264_mf", "libx264"),
            "software": ("libx264",),
        },
        "h265": {
            "auto": ("hevc_nvenc", "hevc_mf", "libx265"),
            "software": ("libx265",),
        },
    }
    _CODEC_LABELS = {"h264": "H.264", "h265": "H.265 (HEVC)"}

    def __init__(self) -> None:
        self._container: Any | None = None
        self._stream: Any | None = None
        self._path: Path | None = None
        self._size: tuple[int, int] = (0, 0)
        self._fps = 0.0
        self._time_base = Fraction(1, 1)
        self._queue: queue.Queue[tuple[np.ndarray, int]] = queue.Queue(
            maxsize=self._QUEUE_SIZE
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._recording = False
        self._actual_encoder: str | None = None
        self._codec_label: str | None = None
        self._frame_count = 0
        self._dropped_frames = 0
        self._worker_error: RecorderError | None = None
        self._clock_start = 0.0
        self._last_slot = -1
        self.started_at: datetime | None = None

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def actual_encoder(self) -> str | None:
        with self._lock:
            return self._actual_encoder

    @property
    def codec_label(self) -> str | None:
        with self._lock:
            return self._codec_label

    @property
    def frame_count(self) -> int:
        with self._lock:
            return self._frame_count

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    @property
    def worker_error(self) -> RecorderError | None:
        with self._lock:
            return self._worker_error

    @property
    def error(self) -> RecorderError | None:
        """Alias for callers that prefer a shorter worker-error property."""
        return self.worker_error

    def start(
        self,
        output_dir: Path,
        size: tuple[int, int],
        fps: float = 20.0,
        codec: str = "h264",
        bitrate_mbps: int = 8,
        encoder_mode: str = "auto",
        output_size: tuple[int, int] | None = None,
    ) -> Path:
        with self._lock:
            if self._recording or self._thread is not None:
                raise RecorderError("已经在录像")
            self._validate_settings(size, output_size, fps, codec, bitrate_mbps, encoder_mode)

            target_size = output_size or size
            if bitrate_mbps == 0:
                bitrate_mbps = self._default_bitrate(target_size, codec)
            path = self._new_output_path(Path(output_dir))
            container, stream, encoder, failures = self._open_encoder(
                path,
                target_size,
                fps,
                codec,
                bitrate_mbps,
                encoder_mode,
            )
            if container is None or stream is None or encoder is None:
                details = "；".join(failures)
                raise RecorderError(f"无法打开可用的 {self._CODEC_LABELS[codec]} 编码器：{details}")

            self._container = container
            self._stream = stream
            self._path = path
            self._size = target_size
            self._fps = fps
            rate = Fraction(str(fps)).limit_denominator(100_000)
            self._time_base = Fraction(rate.denominator, rate.numerator)
            self._queue = queue.Queue(maxsize=self._QUEUE_SIZE)
            self._stop_event = threading.Event()
            self._actual_encoder = encoder
            self._codec_label = self._CODEC_LABELS[codec]
            self._frame_count = 0
            self._dropped_frames = 0
            self._worker_error = None
            self._clock_start = time.monotonic()
            self._last_slot = -1
            self.started_at = datetime.now()
            self._recording = True
            self._thread = threading.Thread(
                target=self._encode_worker,
                name="video-recorder",
                daemon=True,
            )
            self._thread.start()
            return path

    def write(self, frame: np.ndarray) -> None:
        with self._lock:
            if not self._recording or self._worker_error is not None:
                return
            work_queue = self._queue
        image = frame.copy()
        captured_at = time.monotonic()

        with self._lock:
            if (
                not self._recording
                or self._worker_error is not None
                or work_queue is not self._queue
            ):
                return
            slot = int((captured_at - self._clock_start) * self._fps)
            if slot <= self._last_slot:
                self._dropped_frames += 1
                return
            self._last_slot = slot
            try:
                work_queue.put_nowait((image, slot))
            except queue.Full:
                try:
                    work_queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._dropped_frames += 1
                try:
                    work_queue.put_nowait((image, slot))
                except queue.Full:
                    self._dropped_frames += 1

    def stop(self) -> Path | None:
        with self._lock:
            thread = self._thread
            path = self._path
            if thread is None:
                return path
            self._recording = False
            self._stop_event.set()

        thread.join()
        with self._lock:
            error = self._worker_error
            self._worker_error = None
            self._thread = None
            self._container = None
            self._stream = None
            self._path = None
        if error is not None:
            raise error
        return path

    @staticmethod
    def _validate_settings(
        size: tuple[int, int],
        output_size: tuple[int, int] | None,
        fps: float,
        codec: str,
        bitrate_mbps: int,
        encoder_mode: str,
    ) -> None:
        target_size = output_size or size
        if len(size) != 2 or len(target_size) != 2:
            raise RecorderError("画面尺寸必须是 (宽, 高)")
        if any(not isinstance(value, int) or value <= 0 for value in (*size, *target_size)):
            raise RecorderError("画面尺寸必须是正整数")
        if target_size[0] % 2 or target_size[1] % 2:
            raise RecorderError("H.264/H.265 输出宽高必须是偶数")
        if fps <= 0:
            raise RecorderError("帧率必须大于 0")
        if codec not in VideoRecorder._ENCODERS:
            raise RecorderError("codec 只支持 'h264' 或 'h265'")
        if encoder_mode not in ("auto", "software"):
            raise RecorderError("encoder_mode 只支持 'auto' 或 'software'")
        if not isinstance(bitrate_mbps, int) or bitrate_mbps < 0 or bitrate_mbps > 80:
            raise RecorderError("码率必须是自动（0）或 2–80 Mbps")
        if bitrate_mbps == 1:
            raise RecorderError("手动码率最低为 2 Mbps")

    @staticmethod
    def _default_bitrate(size: tuple[int, int], codec: str) -> int:
        pixels = size[0] * size[1]
        if pixels >= 3840 * 2160:
            h264 = 40
        elif pixels >= 1920 * 1080:
            h264 = 12
        elif pixels >= 1280 * 720:
            h264 = 6
        else:
            h264 = 3
        return max(2, round(h264 * (0.7 if codec == "h265" else 1.0)))

    @staticmethod
    def _new_output_path(output_dir: Path) -> Path:
        folder = output_dir / "工作台"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("录像_%Y%m%d_%H%M%S")
        path = folder / f"{stamp}.mp4"
        suffix = 1
        while path.exists():
            path = folder / f"{stamp}_{suffix}.mp4"
            suffix += 1
        return path

    def _open_encoder(
        self,
        path: Path,
        size: tuple[int, int],
        fps: float,
        codec: str,
        bitrate_mbps: int,
        encoder_mode: str,
    ) -> tuple[Any | None, Any | None, str | None, list[str]]:
        failures: list[str] = []
        rate = Fraction(str(fps)).limit_denominator(100_000)
        time_base = Fraction(rate.denominator, rate.numerator)
        for encoder in self._ENCODERS[codec][encoder_mode]:
            container: Any | None = None
            try:
                container = av.open(str(path), mode="w", format="mp4")
                stream = container.add_stream(encoder, rate=rate)
                stream.width, stream.height = size
                stream.pix_fmt = "yuv420p"
                stream.bit_rate = bitrate_mbps * 1_000_000
                stream.time_base = time_base
                stream.codec_context.time_base = time_base
                stream.codec_context.framerate = rate
                if encoder == "libx264":
                    stream.options = {"preset": "veryfast", "tune": "zerolatency"}
                elif encoder == "libx265":
                    # 4K software HEVC is otherwise too slow for live capture
                    # even on high-end desktop CPUs. The configured bitrate
                    # preserves quality while this preset reduces analysis work.
                    stream.options = {"preset": "ultrafast", "tune": "zerolatency"}
                stream.codec_context.open()
                return container, stream, encoder, failures
            except Exception as exc:
                failures.append(f"{encoder}: {exc}")
                if container is not None:
                    try:
                        container.close()
                    except Exception:
                        pass
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return None, None, None, failures

    def _encode_worker(self) -> None:
        with self._lock:
            container = self._container
            stream = self._stream
            work_queue = self._queue
            stop_event = self._stop_event

        try:
            if container is None or stream is None:
                raise RecorderError("录像器尚未正确初始化")
            while not stop_event.is_set() or not work_queue.empty():
                try:
                    image, pts = work_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                height, width = image.shape[:2]
                if (width, height) != self._size:
                    image = cv2.resize(image, self._size, interpolation=cv2.INTER_AREA)
                image = self._as_bgr(image)
                video_frame = av.VideoFrame.from_ndarray(image, format="bgr24")
                video_frame.pts = pts
                video_frame.time_base = self._time_base
                for packet in stream.encode(video_frame):
                    container.mux(packet)
                with self._lock:
                    self._frame_count += 1

            for packet in stream.encode(None):
                container.mux(packet)
        except Exception as exc:
            with self._lock:
                self._worker_error = (
                    exc if isinstance(exc, RecorderError) else RecorderError(f"录像编码失败：{exc}")
                )
                self._recording = False
            stop_event.set()
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception as exc:
                    with self._lock:
                        if self._worker_error is None:
                            self._worker_error = RecorderError(f"关闭录像文件失败：{exc}")
                            self._recording = False

    @staticmethod
    def _as_bgr(frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if frame.ndim == 3 and frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        if frame.ndim == 3 and frame.shape[2] == 3:
            return np.ascontiguousarray(frame)
        raise RecorderError("录像帧必须是灰度、BGR 或 BGRA 图像")


def snapshot_path(output_dir: Path, prefix: str = "抓拍") -> Path:
    stamp = datetime.now().strftime(f"{prefix}_%Y%m%d_%H%M%S")
    folder = output_dir / "工作台"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{stamp}.jpg"
