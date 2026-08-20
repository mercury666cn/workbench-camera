from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def tools_dir() -> Path:
    return project_root() / "tools"


def scrcpy_dir() -> Path:
    return tools_dir() / "scrcpy"


def data_dir() -> Path:
    path = project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def default_output_dir() -> Path:
    docs = Path.home() / "Documents" / "工作台相机"
    docs.mkdir(parents=True, exist_ok=True)
    return docs
