from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from app.ocr.lmstudio_client import LMStudioClient, LMStudioError
from app.scan.document import warp_document


class PageStatus(str, Enum):
    pending = "待识别"
    running = "识别中"
    done = "已完成"
    error = "失败"


@dataclass
class ScanPage:
    index: int
    image_path: Path
    text: str = ""
    status: PageStatus = PageStatus.pending
    error: str = ""


@dataclass
class BatchJob:
    output_dir: Path
    pages: list[ScanPage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def job_dir(self) -> Path:
        stamp = self.created_at.strftime("扫描_%Y%m%d_%H%M%S")
        path = self.output_dir / "扫描" / stamp
        path.mkdir(parents=True, exist_ok=True)
        return path

    def add_frame(self, frame: np.ndarray, auto_warp: bool = True) -> ScanPage:
        image = warp_document(frame) if auto_warp else frame
        index = len(self.pages) + 1
        path = self.job_dir / f"page_{index:03d}.jpg"
        try:
            ok, encoded = cv2.imencode(
                ".jpg",
                image,
                [int(cv2.IMWRITE_JPEG_QUALITY), 95],
            )
            if not ok or encoded.size == 0:
                raise RuntimeError("JPEG 编码失败")
            jpeg = encoded.tobytes()
            written = path.write_bytes(jpeg)
            if written != len(jpeg) or not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError("写入后的图片文件不完整")
        except (cv2.error, OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(f"保存扫描图片失败：{path}（{exc}）") from exc
        page = ScanPage(index=index, image_path=path)
        self.pages.append(page)
        return page

    def run_ocr(
        self,
        client: LMStudioClient,
        max_side: int = 2000,
        on_page=None,
        only_failed: bool = False,
    ) -> None:
        for page in self.pages:
            if only_failed and page.status != PageStatus.error:
                continue
            if page.status == PageStatus.done:
                continue
            page.status = PageStatus.running
            page.error = ""
            if on_page:
                on_page(page)
            try:
                encoded = np.fromfile(page.image_path, dtype=np.uint8)
                image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
            except (cv2.error, OSError, ValueError):
                image = None
            if image is None:
                page.status = PageStatus.error
                page.error = f"读不到页图：{page.image_path}"
                if on_page:
                    on_page(page)
                continue
            try:
                page.text = client.ocr_image(image, max_side=max_side)
                page.status = PageStatus.done
            except LMStudioError as exc:
                page.status = PageStatus.error
                page.error = str(exc)
            if on_page:
                on_page(page)

    def texts(self) -> list[str]:
        return [page.text for page in self.pages if page.status == PageStatus.done]
