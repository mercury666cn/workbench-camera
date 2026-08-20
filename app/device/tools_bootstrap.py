from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from app.paths import project_root, scrcpy_dir, tools_dir


SCRCPY_VERSION = "4.1"
SCRCPY_WIN64_ZIP = f"https://github.com/Genymobile/scrcpy/releases/download/v{SCRCPY_VERSION}/scrcpy-win64-v{SCRCPY_VERSION}.zip"


class ToolsError(RuntimeError):
    pass


def vendor_server() -> Path:
    return project_root() / "tools" / "vendor" / "scrcpy-server"


def restore_patched_server() -> None:
    """Keep our AF-patched 4.1 server after the official zip lands."""
    src = vendor_server()
    if not src.exists():
        return
    dest = scrcpy_dir() / "scrcpy-server"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        return
    shutil.copy2(src, dest)


def find_scrcpy() -> Path | None:
    root = scrcpy_dir()
    if not root.exists():
        return None
    direct = root / "scrcpy.exe"
    if direct.exists():
        return direct
    for exe in root.rglob("scrcpy.exe"):
        return exe
    return None


def find_adb(scrcpy_exe: Path | None = None) -> Path | None:
    if scrcpy_exe is None:
        scrcpy_exe = find_scrcpy()
    if scrcpy_exe is not None:
        sibling = scrcpy_exe.parent / "adb.exe"
        if sibling.exists():
            return sibling
    return None


def ensure_scrcpy(progress=None) -> tuple[Path, Path]:
    exe = find_scrcpy()
    adb = find_adb(exe)
    if not (exe and adb):
        if progress:
            progress("正在下载 scrcpy 4.1（含 ADB）…")
        _download_scrcpy(progress)
        exe = find_scrcpy()
        adb = find_adb(exe)
    if not exe or not adb:
        raise ToolsError("scrcpy 下载完成，但没有找到 scrcpy.exe / adb.exe")
    restore_patched_server()
    return exe, adb


def _download_scrcpy(progress=None) -> None:
    tools_dir().mkdir(parents=True, exist_ok=True)
    if progress:
        progress(f"下载 scrcpy-win64-v{SCRCPY_VERSION}.zip …")
    req = Request(SCRCPY_WIN64_ZIP, headers={"User-Agent": "WorkbenchCamera/1.0"})
    with urlopen(req, timeout=120) as resp:
        payload = resp.read()
    target = scrcpy_dir()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        zf.extractall(target)
    children = [p for p in target.iterdir() if p.is_dir()]
    if not (target / "scrcpy.exe").exists() and len(children) == 1:
        nested = children[0]
        for item in nested.iterdir():
            dest = target / item.name
            if dest.exists():
                continue
            shutil.move(str(item), str(dest))
        shutil.rmtree(nested, ignore_errors=True)
    restore_patched_server()
