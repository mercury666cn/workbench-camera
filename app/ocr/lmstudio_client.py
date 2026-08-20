from __future__ import annotations

import base64
import re

import cv2
import httpx
import numpy as np

from app.scan.document import resize_max_side


PAGE_PROMPT = (
    "请把这张资料照片转写成原文。只输出正文，保持原有标题和段落。"
    "看不清的地方标［无法识别］。不要总结，不要翻译，不要加解释。"
)

MERGE_PROMPT = (
    "下面是一份资料按页识别出的文本。请整合成一篇连贯文稿："
    "接上跨页被截断的句子，去掉重复页眉页脚，统一标题层级。"
    "不要新增内容，不要总结。只输出整合后的正文。\n\n"
)


class LMStudioError(RuntimeError):
    pass


class LMStudioClient:
    def __init__(self, base_url: str, model: str = "", api_key: str = "lm-studio", timeout: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._resolved_model = model

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=8.0),
            headers={"Authorization": f"Bearer {self.api_key}"},
        )

    def list_models(self) -> list[str]:
        try:
            with self._client() as client:
                resp = client.get("/models")
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._response_excerpt(exc.response)
            raise LMStudioError(
                f"LM Studio 模型列表请求失败（HTTP {exc.response.status_code}）：{detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise LMStudioError(f"连不上 LM Studio：{exc}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise LMStudioError("LM Studio 模型列表返回的 JSON 无法解析") from exc
        if not isinstance(data, dict):
            raise LMStudioError("LM Studio 模型列表返回的 JSON 格式异常")
        items = data.get("data") or []
        if not isinstance(items, list):
            raise LMStudioError("LM Studio 模型列表返回的 JSON 格式异常")
        names = [
            item["id"]
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
        ]
        if not names:
            raise LMStudioError("LM Studio 已通，但没有已加载的模型")
        return names

    def health(self) -> tuple[bool, str, list[str]]:
        try:
            names = self.list_models()
        except LMStudioError as exc:
            return False, str(exc), []
        if self.model and self.model not in names:
            return True, f"已连通，但指定模型不在列表里：{self.model}", names
        active_model = self._resolve_model(names)
        return True, f"LM Studio 已连通 · {active_model}", names

    def ocr_image(self, image: np.ndarray, max_side: int = 2000) -> str:
        prepared = image if max_side <= 0 else resize_max_side(image, max_side)
        ok, buf = cv2.imencode(".jpg", prepared, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not ok:
            raise LMStudioError("无法编码识别图片")
        return self.ocr_jpeg(buf.tobytes())

    def ocr_jpeg(self, jpeg: bytes) -> str:
        b64 = base64.b64encode(jpeg).decode("ascii")
        return self._chat(
            [
                {"type": "text", "text": PAGE_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                },
            ]
        )

    def merge_texts(self, pages: list[str]) -> str:
        body = "\n\n".join(f"## 第 {i} 页\n{text}" for i, text in enumerate(pages, 1))
        return self._chat([{"type": "text", "text": MERGE_PROMPT + body}])

    def _chat(self, content: list[dict]) -> str:
        payload = {
            "model": self._resolve_model(),
            "temperature": 0.1,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": content}],
        }
        try:
            with self._client() as client:
                resp = client.post("/chat/completions", json=payload)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._response_excerpt(exc.response)
            raise LMStudioError(
                f"LM Studio 识别失败（HTTP {exc.response.status_code}）：{detail}"
            ) from exc
        except httpx.RequestError as exc:
            raise LMStudioError(f"连不上 LM Studio：{exc}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise LMStudioError("LM Studio 返回的 JSON 无法解析") from exc
        if not isinstance(data, dict):
            raise LMStudioError("LM Studio 返回的 JSON 格式异常")
        choices = data.get("choices")
        if not choices:
            raise LMStudioError("LM Studio 返回的 choices 为空")
        if not isinstance(choices, list) or not isinstance(choices[0], dict):
            raise LMStudioError("LM Studio 返回的 JSON 格式异常")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise LMStudioError("LM Studio 返回的 JSON 格式异常")
        text = message.get("content")
        if not isinstance(text, str):
            raise LMStudioError("LM Studio 返回的 JSON 格式异常")
        text = text.strip()
        if not text:
            raise LMStudioError("LM Studio 返回空文本")
        return text

    def _resolve_model(self, names: list[str] | None = None) -> str:
        if self._resolved_model:
            return self._resolved_model
        available = names if names is not None else self.list_models()
        self._resolved_model = available[0]
        return self._resolved_model

    @staticmethod
    def _response_excerpt(response: httpx.Response, limit: int = 500) -> str:
        text = response.text.strip() or "响应正文为空"
        text = re.sub(
            r"data:image/[^;,]+;base64,[A-Za-z0-9+/=\s]+",
            "data:image/...;base64,[已省略]",
            text,
        )
        text = " ".join(text.split())
        if len(text) > limit:
            return text[:limit] + "…（已截断）"
        return text
