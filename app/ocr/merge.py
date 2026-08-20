from __future__ import annotations

from app.ocr.lmstudio_client import LMStudioClient, LMStudioError


def join_pages(pages: list[str]) -> str:
    blocks = []
    for i, text in enumerate(pages, 1):
        body = (text or "").strip()
        if not body:
            continue
        blocks.append(f"—— 第 {i} 页 ——\n{body}")
    return "\n\n".join(blocks).strip()


def semantic_merge(client: LMStudioClient, pages: list[str]) -> str:
    cleaned = [p.strip() for p in pages if p.strip()]
    if not cleaned:
        raise LMStudioError("没有可整合的已识别文本")
    if len(cleaned) == 1:
        return cleaned[0]
    return client.merge_texts(cleaned)
