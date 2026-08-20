"""Scrcpy 4.1 camera client: video socket + control socket, no scrcpy.exe."""
from __future__ import annotations

import math
import socket
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import av
import numpy as np

from app.device.adb_phone import AdbPhone, AdbError, _no_window_flag


FrameCallback = Callable[[np.ndarray], None]
ErrorCallback = Callable[[str], None]

SERVER_VERSION = "4.1"
DEVICE_NAME_LEN = 64
ZOOM_FACTOR = 1.0 + 1.0 / 16.0
MSG_CAMERA_ZOOM_IN = 19
MSG_CAMERA_ZOOM_OUT = 20
MSG_CAMERA_AF_TAP = 23
CODEC_H264 = 0x68323634


class CameraClientError(RuntimeError):
    pass


class ScrcpyCameraClient:
    def __init__(
        self,
        phone: AdbPhone,
        camera_id: str = "0",
        camera_size: str = "1920x1080",
        camera_fps: int = 24,
        camera_zoom: float = 1.0,
    ) -> None:
        self.phone = phone
        self.camera_id = camera_id or "0"
        self.camera_size = camera_size or "1920x1080"
        self.camera_fps = int(camera_fps or 24)
        self.camera_zoom = _clamp_zoom(camera_zoom)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._ctrl_lock = threading.Lock()
        self._last_frame: np.ndarray | None = None
        self._on_frame: FrameCallback | None = None
        self._on_error: ErrorCallback | None = None
        self._proc: subprocess.Popen | None = None
        self._video: socket.socket | None = None
        self._control: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._local_port = 0
        self._scid = 0
        self._silenced = False
        self.running = False
        self.last_log: list[str] = []

    def set_callbacks(self, on_frame: FrameCallback | None, on_error: ErrorCallback | None) -> None:
        self._on_frame = on_frame
        self._on_error = on_error

    def start(self) -> None:
        if self.running:
            return
        if self.phone.quick_status().offline:
            raise CameraClientError("USB 掉线了，请拔线等 3 秒再插。不要连点重新检测。")
        self._stop.clear()
        self._last_frame = None
        self._silenced = False
        self.last_log = []
        self._scid = int(time.time() * 1000) & 0x7FFFFFFF
        self._local_port = _free_port()
        try:
            self._kill_stale_servers()
            self._push_server()
            self._forward()
            self._proc = self._spawn_server()
            self._video, self._control = self._connect_sockets()
            self._read_video_preamble(self._video)
        except Exception as exc:
            self._cleanup()
            raise CameraClientError(str(exc)) from exc
        self.running = True
        self._thread = threading.Thread(target=self._decode_loop, name="scrcpy-cam-decode", daemon=True)
        self._thread.start()
        threading.Thread(target=self._drain_control, name="scrcpy-cam-ctrl", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.running = False
        self._cleanup()
        with self._lock:
            self._last_frame = None

    def snapshot(self) -> np.ndarray:
        with self._lock:
            if self._last_frame is None:
                raise CameraClientError("还没有画面，请先开启预览")
            return self._last_frame.copy()

    def set_zoom(self, zoom: float) -> None:
        target = _clamp_zoom(zoom)
        sock = self._control
        if sock is None or not self.running:
            self.camera_zoom = target
            return
        delta = _zoom_level(target) - _zoom_level(self.camera_zoom)
        if delta == 0:
            self.camera_zoom = target
            return
        msg = bytes([MSG_CAMERA_ZOOM_IN if delta > 0 else MSG_CAMERA_ZOOM_OUT])
        try:
            with self._ctrl_lock:
                for _ in range(abs(delta)):
                    sock.sendall(msg)
        except OSError as exc:
            self._fail(f"变焦控制中断：{exc}")
            return
        self.camera_zoom = target

    def tap_focus(self, nx: float, ny: float) -> None:
        sock = self._control
        if sock is None or not self.running:
            return
        x = max(0.0, min(1.0, float(nx)))
        y = max(0.0, min(1.0, float(ny)))
        payload = struct.pack(">BHH", MSG_CAMERA_AF_TAP, int(round(x * 65535)), int(round(y * 65535)))
        try:
            with self._ctrl_lock:
                sock.sendall(payload)
        except OSError as exc:
            self._fail(f"对焦控制中断：{exc}")

    def refocus(self) -> None:
        self.tap_focus(0.5, 0.5)

    def _server_jar(self) -> Path:
        path = self.phone.scrcpy_exe.parent / "scrcpy-server"
        if not path.exists():
            raise CameraClientError(f"找不到 scrcpy-server：{path}")
        return path

    def _push_server(self) -> None:
        self.phone.run("push", str(self._server_jar()), "/data/local/tmp/scrcpy-server.jar", timeout=20)

    def _forward(self) -> None:
        name = f"localabstract:scrcpy_{self._scid:08x}"
        self.phone.run("forward", f"tcp:{self._local_port}", name)

    def _remove_forward(self) -> None:
        if not self._local_port:
            return
        self.phone.try_run("forward", "--remove", f"tcp:{self._local_port}")

    def _spawn_server(self) -> subprocess.Popen:
        zoom = _clamp_zoom(self.camera_zoom, hi=10.0)
        args = [
            str(self.phone.adb_exe),
        ]
        if self.phone.serial:
            args += ["-s", self.phone.serial]
        args += [
            "shell",
            "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SERVER_VERSION,
            f"scid={self._scid:08x}",
            "log_level=info",
            "tunnel_forward=true",
            "audio=false",
            "control=true",
            "video_source=camera",
            f"camera_id={self.camera_id}",
            f"camera_size={self.camera_size}",
            f"camera_fps={self.camera_fps}",
            f"camera_zoom={zoom:.2f}",
            "power_on=false",
            "stay_awake=true",
            "clipboard_autosync=false",
            "cleanup=true",
        ]
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=self.phone.env(),
                creationflags=_no_window_flag(),
            )
        except OSError as exc:
            raise CameraClientError(f"无法启动相机服务：{exc}") from exc
        threading.Thread(target=self._read_server_log, args=(proc,), daemon=True).start()
        return proc

    def _read_server_log(self, proc: subprocess.Popen) -> None:
        if proc.stdout is None:
            return
        for raw in proc.stdout:
            try:
                line = raw.decode("utf-8", errors="replace").rstrip()
            except AttributeError:
                line = str(raw).rstrip()
            if not line:
                continue
            self.last_log.append(line)
            if len(self.last_log) > 80:
                del self.last_log[:20]

    def _connect_sockets(self) -> tuple[socket.socket, socket.socket]:
        deadline = time.time() + 10
        video = None
        while time.time() < deadline and not self._stop.is_set():
            if self._proc is not None and self._proc.poll() is not None:
                detail = "\n".join(self.last_log[-8:]) or "相机服务已退出"
                raise CameraClientError(detail)
            try:
                video = socket.create_connection(("127.0.0.1", self._local_port), timeout=1.0)
                video.settimeout(8.0)
                dummy = _recvall(video, 1)
                if dummy != b"\x00":
                    video.close()
                    raise CameraClientError("相机隧道握手失败")
                break
            except OSError:
                if video is not None:
                    try:
                        video.close()
                    except OSError:
                        pass
                    video = None
                time.sleep(0.15)
        if video is None:
            raise CameraClientError("等相机视频口超时。" + ("\n".join(self.last_log[-6:]) if self.last_log else ""))
        try:
            control = socket.create_connection(("127.0.0.1", self._local_port), timeout=4.0)
            control.settimeout(1.0)
        except OSError as exc:
            video.close()
            raise CameraClientError(f"控制口连不上：{exc}") from exc
        return video, control

    def _read_video_preamble(self, video: socket.socket) -> None:
        _recvall(video, DEVICE_NAME_LEN)
        codec = struct.unpack(">I", _recvall(video, 4))[0]
        if codec != CODEC_H264:
            raise CameraClientError(f"相机编码不是 H264：{codec:#x}")

    def _decode_loop(self) -> None:
        video = self._video
        if video is None:
            self._fail("没有视频口")
            return
        video.settimeout(0.8)
        try:
            codec = av.CodecContext.create("h264", "r")
        except Exception as exc:
            self._fail(f"无法创建解码器：{exc}")
            return
        try:
            while not self._stop.is_set():
                try:
                    header = _recvall(video, 12, self._stop)
                except TimeoutError:
                    continue
                except OSError as exc:
                    if not self._stop.is_set():
                        self._fail(f"相机流中断：{exc}")
                    return
                flags = int.from_bytes(header[:8], "big")
                if flags & (1 << 63):
                    continue
                size = int.from_bytes(header[8:12], "big")
                if size <= 0 or size > 8_000_000:
                    self._fail("相机数据包异常")
                    return
                try:
                    payload = _recvall(video, size, self._stop)
                except OSError as exc:
                    if not self._stop.is_set():
                        self._fail(f"相机流中断：{exc}")
                    return
                try:
                    packets = codec.parse(payload)
                    frames = []
                    for packet in packets:
                        frames.extend(codec.decode(packet))
                except Exception as exc:
                    self.last_log.append(f"decode: {exc}")
                    continue
                for frame in frames:
                    image = frame.to_ndarray(format="bgr24")
                    with self._lock:
                        self._last_frame = image
                    if not self._silenced:
                        self._silenced = True
                        threading.Thread(target=self._quiet_once, name="quiet-once", daemon=True).start()
                    if self._on_frame:
                        self._on_frame(image)
        finally:
            try:
                codec.close()
            except Exception:
                pass

    def _drain_control(self) -> None:
        sock = self._control
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                data = sock.recv(256)
            except TimeoutError:
                continue
            except OSError:
                return
            if not data:
                return

    def _quiet_once(self) -> None:
        if self._stop.is_set():
            return
        try:
            self.phone.dim_for_preview()
        except Exception:
            pass

    def _kill_stale_servers(self) -> None:
        try:
            raw = self.phone.try_run("shell", "ps", "-A", timeout=6)
        except AdbError:
            return
        for line in raw.splitlines():
            low = line.lower()
            if "scrcpy" not in low and "genymobile" not in low:
                continue
            parts = line.split()
            if len(parts) < 2 or not parts[1].isdigit():
                continue
            self.phone.try_run("shell", "kill", "-9", parts[1], timeout=4)

    def _cleanup(self) -> None:
        for sock in (self._video, self._control):
            if sock is None:
                continue
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self._video = None
        self._control = None
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._remove_forward()

    def _fail(self, message: str) -> None:
        self.running = False
        if self._on_error:
            self._on_error(message)


def _recvall(sock: socket.socket, n: int, stop: threading.Event | None = None) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        if stop is not None and stop.is_set():
            raise ConnectionError("stopped")
        try:
            chunk = sock.recv(n - len(buf))
        except TimeoutError:
            continue
        if not chunk:
            raise ConnectionError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _clamp_zoom(zoom: float, hi: float = 4.0) -> float:
    return max(1.0, min(float(zoom or 1.0), hi))


def _zoom_level(zoom: float) -> int:
    return int(round(math.log(max(float(zoom), 1.0)) / math.log(ZOOM_FACTOR)))
