from __future__ import annotations

import os
import re
import subprocess
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
    sizes: str = ""


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
        info = ready[0]
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
        try:
            cmd = [str(self.scrcpy_exe), "--list-cameras"]
            if self.serial:
                cmd += ["--serial", self.serial]
            raw = subprocess.run(
                cmd,
                env=self.env(),
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
                creationflags=_no_window_flag(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [], None, f"无法列出摄像头：{exc}"
        text = (raw.stdout or "") + "\n" + (raw.stderr or "")
        cameras: list[CameraInfo] = []
        for match in re.finditer(
            r"--camera-id=(\S+)\s+\(([^,]+),\s*([^)]+)\)",
            text,
        ):
            cameras.append(
                CameraInfo(
                    camera_id=match.group(1),
                    facing=match.group(2).strip().lower(),
                    sizes=match.group(3).strip(),
                )
            )
        back = next((c.camera_id for c in cameras if "back" in c.facing), None)
        if back is None and cameras:
            back = cameras[0].camera_id
        if not cameras:
            if "ERROR" in text or raw.returncode != 0:
                snippet = text.strip().splitlines()[-1] if text.strip() else "未知错误"
                return [], None, f"后置相机源不可用：{snippet}"
            return [], None, "没有列出摄像头，华为 HAL 可能未放行相机源"
        return cameras, back, ""

    def mute(self) -> None:
        self.try_run("shell", "input", "keyevent", "164")

    def dim_for_preview(self) -> None:
        # 只变暗，不 SLEEP。这台华为熄屏后 USB 会自己掉成 offline。
        self.try_run("shell", "settings", "put", "system", "screen_brightness", "1")
        self.mute()

    def sleep_screen(self) -> None:
        try:
            if self.quick_status().offline:
                return
        except AdbError:
            return
        self.try_run("shell", "input", "keyevent", "KEYCODE_SLEEP")
        self.try_run("shell", "input", "keyevent", "223")

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


def _no_window_flag() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
