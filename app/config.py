from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.paths import config_path, default_output_dir


@dataclass
class AppConfig:
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    lmstudio_model: str = ""
    lmstudio_api_key: str = "lm-studio"
    output_dir: str = field(default_factory=lambda: str(default_output_dir()))
    camera_size: str = "1920x1080"
    camera_fps: int = 24
    ocr_max_side: int = 2000
    ocr_timeout_sec: int = 180
    rotation: int = 0
    zoom: float = 1.0
    auto_preview: bool = True

    @classmethod
    def load(cls) -> AppConfig:
        path = config_path()
        if not path.exists():
            cfg = cls()
            cfg.save()
            return cfg
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def output_path(self) -> Path:
        path = Path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path
