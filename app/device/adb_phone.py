from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


class AdbError(RuntimeError):
    pass


@dataclass
class DeviceInfo:
    serial: str
    state: str
    sdk: int = 0
    model: str = ""
    brand: str = ""
    ready: bool = False
    message: str = ""


@dataclass
class CameraInfo:
    camera_id: str
    facing: str
    sensor_size: str = ""
    sizes: list[str] = field(default_factory=list)
    fps: list[int] = field(default_factory=list)


OFFLINE_HINT = "USB 掉线了，请拔线等 3 秒再插。不要连点重新检测。"


@dataclass
class PhoneStatus:
    connected: bool
    info: DeviceInfo | None = None
    cameras: list[CameraInfo] = field(default_factory=list)
    back_camera_id: str | None = None
    message: str = ""
    offline: bool = False


class AdbPhone:
    def __init__(self, adb_exe: Path, scrcpy_exe: Path) -> None:
        self.adb_exe = Path(adb_exe)
        self.scrcpy_exe = Path(scrcpy_exe)
        self.serial: str | None = None
        self._cameras: list[CameraInfo] = []
        self._back_camera_id: str | None = None
        self._listed_cameras = False
        self.server_on_device = False
        self._server_lock = threading.Lock()
        self.display_asleep = False
        self.skip_stale_kill = False

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["ADB"] = str(self.adb_exe)
        return env

    def run(self, *args: str, timeout: int = 12) -> str:
        cmd = [str(self.adb_exe)]
        if self.serial and args[:1] != ("devices",):
            cmd += ["-s", self.serial]
        cmd += list(args)
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                env=self.env(),
                creationflags=_no_window_flag(),
            )
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB 超时：{' '.join(args)}") from exc
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "").strip()
            raise AdbError(err or f"ADB 失败：{' '.join(args)}")
        return completed.stdout

    def try_run(self, *args: str, timeout: int = 8) -> str:
        try:
            return self.run(*args, timeout=timeout)
        except AdbError:
            return ""

    def list_devices(self) -> list[DeviceInfo]:
        raw = self.run("devices", "-l", timeout=8)
        devices: list[DeviceInfo] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            model = _kv(line, "model") or ""
            devices.append(DeviceInfo(serial=serial, state=state, model=model.replace("_", " ")))
        return devices

    def quick_status(self) -> PhoneStatus:
        devices = self.list_devices()
        ready = [d for d in devices if d.state == "device"]
        if not ready:
            unauthorized = [d for d in devices if d.state == "unauthorized"]
            if unauthorized:
                return PhoneStatus(False, message="手机在线但未授权，请在手机上点「始终允许」后重插")
            offline = [d for d in devices if d.state == "offline"]
            if offline:
                self.serial = offline[0].serial
                return PhoneStatus(False, offline=True, message=OFFLINE_HINT)
            return PhoneStatus(False, message="没有检测到已连接的手机")
        if len(ready) > 1:
            names = "、".join(device.model or device.serial for device in ready)
            return PhoneStatus(False, message=f"同时连接了多台手机（{names}），请只保留要使用的一台")
        info = ready[0]
        if self.serial and self.serial != info.serial:
            self._cameras = []
            self._back_camera_id = None
            self._listed_cameras = False
            self.server_on_device = False
            self.display_asleep = False
            self.skip_stale_kill = False
        self.serial = info.serial
        info.ready = True
        info.message = "手机已连接（静默）"
        return PhoneStatus(
            connected=True,
            info=info,
            cameras=self._cameras,
            back_camera_id=self._back_camera_id or "0",
            message=info.message,
        )

    def probe(self, list_cameras: bool = False) -> PhoneStatus:
        status = self.quick_status()
        if not status.connected or status.info is None:
            return status
        info = status.info
        if not info.sdk:
            info.sdk = _as_int(self.try_run("shell", "getprop", "ro.build.version.sdk"))
            info.model = self.try_run("shell", "getprop", "ro.product.model").strip() or info.model
            info.brand = self.try_run("shell", "getprop", "ro.product.brand").strip()
        if info.sdk and info.sdk < 31:
            info.message = f"系统 SDK {info.sdk}，后置相机源需要 31+（Android 12 / 鸿蒙 3）"
            return PhoneStatus(True, info=info, message=info.message)
        if list_cameras or not self._listed_cameras:
            cameras, back_id, cam_msg = self.list_cameras()
            if cameras:
                self._cameras = cameras
                self._back_camera_id = back_id
                self._listed_cameras = True
            elif self._back_camera_id:
                cameras, back_id, cam_msg = self._cameras, self._back_camera_id, ""
            info.message = "手机已连接（静默）"
            message = cam_msg or info.message
            return PhoneStatus(
                connected=True,
                info=info,
                cameras=cameras,
                back_camera_id=back_id or "0",
                message=message,
            )
        return PhoneStatus(
            connected=True,
            info=info,
            cameras=self._cameras,
            back_camera_id=self._back_camera_id or "0",
            message="手机已连接（静默）",
        )

    def recover_offline(self) -> bool:
        # 华为 offline 时不要 adb reconnect，会越救越死。只等用户拔插。
        return False

    def list_cameras(self) -> tuple[list[CameraInfo], str | None, str]:
        """Query Camera2 characteristics with the bundled server.

        This avoids scrcpy.exe's implicit push, which was a major source of
        reconnect failures when opening the settings page.
        """
        try:
            self.ensure_server_uploaded()
            args = [
                str(self.adb_exe),
                *(["-s", self.serial] if self.serial else []),
                "shell",
                "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
                "app_process",
                "/",
                "com.genymobile.scrcpy.Server",
                "4.1",
                "log_level=info",
                "cleanup=false",
                "list_camera_sizes=true",
            ]
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
                env=self.env(),
                creationflags=_no_window_flag(),
            )
            text = (completed.stdout or "") + "\n" + (completed.stderr or "")
            if completed.returncode != 0:
                raise AdbError(text.strip() or "相机能力探测失败")
        except (AdbError, OSError, subprocess.TimeoutExpired) as exc:
            return [], None, f"无法列出摄像头：{exc}"

        cameras: list[CameraInfo] = []
        current: CameraInfo | None = None
        high_speed = False
        for line in text.splitlines():
            match = re.search(
                r"--camera-id=(\S+)\s+\(([^,]+),\s*(\d+x\d+)(?:,\s*fps=\{([^}]*)\})?",
                line,
            )
            if match:
                current = CameraInfo(
                    camera_id=match.group(1),
                    facing=match.group(2).strip().lower(),
                    sensor_size=match.group(3),
                    fps=_parse_fps(match.group(4) or ""),
                )
                cameras.append(current)
                high_speed = False
                continue
            if "High speed capture" in line:
                high_speed = True
                continue
            size = re.search(r"^\s*-\s*(\d+)x(\d+)", line)
            if current is not None and size and not high_speed:
                value = f"{size.group(1)}x{size.group(2)}"
                if value not in current.sizes:
                    current.sizes.append(value)

        back = next((c.camera_id for c in cameras if "back" in c.facing), None)
        if back is None and cameras:
            back = cameras[0].camera_id
        if not cameras:
            if "ERROR" in text:
                snippet = text.strip().splitlines()[-1] if text.strip() else "未知错误"
                return [], None, f"后置相机源不可用：{snippet}"
            return [], None, "没有列出摄像头，华为 HAL 可能未放行相机源"
        return cameras, back, ""

    def ensure_server_uploaded(self) -> None:
        """Ensure the bundled patched server exists on this USB device."""
        with self._server_lock:
            self._ensure_server_uploaded()

    def _ensure_server_uploaded(self) -> None:
        local = self.scrcpy_exe.parent / "scrcpy-server"
        if not local.exists():
            raise AdbError(f"缺少相机服务文件：{local}")
        local_size = local.stat().st_size
        local_hash = hashlib.sha256(local.read_bytes()).hexdigest()
        if self.server_on_device or self._remote_server_ready(local_size, local_hash):
            self.server_on_device = True
            return
        self._stream_server(local)
        if not self._remote_server_ready(local_size, local_hash):
            raise AdbError("相机服务写入后 SHA-256 校验失败，请重新插拔手机")
        self.server_on_device = True

    def _stream_server(self, local: Path) -> None:
        """Write through adb shell stdin, avoiding Huawei's broken sync/push protocol."""
        args = [
            str(self.adb_exe),
            *(["-s", self.serial] if self.serial else []),
            "shell",
            "base64 -d > /data/local/tmp/scrcpy-server.jar.tmp"
            " && mv /data/local/tmp/scrcpy-server.jar.tmp /data/local/tmp/scrcpy-server.jar",
        ]
        try:
            completed = subprocess.run(
                args,
                input=base64.b64encode(local.read_bytes()),
                capture_output=True,
                timeout=25,
                env=self.env(),
                creationflags=_no_window_flag(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdbError(f"相机服务写入失败：{exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="replace").strip()
            raise AdbError(detail or "相机服务写入失败")

    def _remote_server_ready(self, expected_size: int, expected_hash: str) -> bool:
        for attempt in range(3):
            checksum = self.try_run(
                "shell",
                "sha256sum",
                "/data/local/tmp/scrcpy-server.jar",
            ).strip().split()
            if checksum and checksum[0].lower() == expected_hash.lower():
                return True
            raw = self.try_run("shell", "stat", "-c", "%s", "/data/local/tmp/scrcpy-server.jar")
            if raw.strip().isdigit() and int(raw.strip()) != expected_size:
                return False
            if attempt < 2:
                time.sleep(0.25)
        return False

    def back_camera(self) -> CameraInfo | None:
        if self._back_camera_id is None:
            return None
        return next((camera for camera in self._cameras if camera.camera_id == self._back_camera_id), None)

    def mute(self) -> None:
        self.try_run("shell", "input", "keyevent", "164")

    def dim_for_preview(self) -> None:
        """Mute and sleep once per USB session. Reopening preview must not hit ADB again."""
        if self.display_asleep:
            return
        try:
            if self.quick_status().offline:
                return
        except AdbError:
            return
        self.mute()
        self.try_run("shell", "input", "keyevent", "KEYCODE_SLEEP")
        self.display_asleep = True

    def restore_after_preview(self) -> None:
        """Only when quitting the app. Do not run this on every preview stop."""
        try:
            if self.quick_status().offline:
                return
        except AdbError:
            return
        self.try_run("shell", "settings", "put", "system", "screen_brightness_mode", "0")
        self.try_run("shell", "settings", "put", "system", "screen_brightness", "80")
        self.display_asleep = False

    def sleep_screen(self) -> None:
        try:
            if self.quick_status().offline:
                return
        except AdbError:
            return
        self.try_run("shell", "input", "keyevent", "KEYCODE_SLEEP")

    def is_screen_on(self) -> bool:
        power = self.try_run("shell", "dumpsys", "power", timeout=6)
        if not power:
            return False
        if re.search(r"mWakefulness=Asleep", power):
            return False
        if re.search(r"mWakefulness=Dozing", power):
            return False
        if re.search(r"mWakefulness=Awake", power):
            return True
        if re.search(r"Display Power: state=ON", power):
            return True
        return False

    def keep_silent(self) -> None:
        if self.is_screen_on():
            self.sleep_screen()


def _kv(line: str, key: str) -> str:
    match = re.search(rf"{key}:(\S+)", line)
    return match.group(1) if match else ""


def _as_int(text: str) -> int:
    text = (text or "").strip()
    return int(text) if text.isdigit() else 0


def _parse_fps(text: str) -> list[int]:
    values = {int(value) for value in re.findall(r"\d+", text)}
    return sorted(value for value in values if 1 <= value <= 240)


def _no_window_flag() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
