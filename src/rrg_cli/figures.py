"""Resolve a question's figures, with fallbacks.

Primary: standalone image files whose name carries the question number (`q1_fig2.png`),
searched recursively (so appendix/sub-folders are covered). Fallback 1: figures the
question's text references by token (e.g. `` `q1_fig2` ``). Fallback 2: when no figure
files exist but the origin report is a PDF (figures live in its appendix), pull the
matching figure out of the PDF — figure N for question N.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_REF_TOKEN = re.compile(r"[qQ]\d+[_-]?fig[\w-]*")


def _boundary(question: int) -> re.Pattern[str]:
    return re.compile(rf"(?:^|[^A-Za-z0-9])[qQ]0*{question}(?:[^0-9]|$)")


def _file_figures(root: Path, question: int, text: str) -> list[Path]:
    if not root.is_dir():
        return []
    boundary = _boundary(question)
    found: list[Path] = []
    images = [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    for path in images:
        if boundary.search(str(path.relative_to(root))):
            found.append(path)
    tokens = {token.lower() for token in _REF_TOKEN.findall(text or "")}
    if tokens:
        for path in images:
            if path not in found and any(token in path.name.lower() for token in tokens):
                found.append(path)
    return list(dict.fromkeys(found))


def _encode_path(path: Path, root: Path) -> dict[str, Any] | None:
    if path.stat().st_size > MAX_IMAGE_BYTES:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "name": str(path.relative_to(root)),
        "data_url": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}",
        "source": "file",
    }


_WORD = re.compile(r"[a-z]{4,}")
# Generic / boilerplate words that don't distinguish one figure from another.
_STOP = {
    "given","that","this","with","than","have","from","value","conclude","there","movies",
    "movie","rated","ratings","rating","significant","significantly","different","differently",
    "difference","those","more","high","higher","low","lower","which","each","both","people",
    "plus","median","mean","conclusion","versus","status","effects","across","between","result",
    "results","test","analysis","question","figure","appendix","data","sample","group","groups",
    "compared","compare","whether","does","prefer","enjoy","like","watch","watching","other",
    "their","they","them","what","when","were","will","would","about","into","over","under",
}


def _stem(word: str) -> str:
    for suffix in ("ing", "ers", "er", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    return {_stem(word) for word in _WORD.findall((text or "").lower()) if word not in _STOP}


def _pdf_caption_figures(report: Path) -> list[dict[str, Any]]:
    """Each appendix figure with its number, caption, and embedded image, paired per page."""
    try:
        import pypdf
    except ImportError:
        return []
    try:
        reader = pypdf.PdfReader(str(report))
    except Exception:
        return []
    pages_text: list[str] = []
    num_to_image: dict[int, Any] = {}
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages_text.append(text)
        numbers = [int(match.group(1)) for match in re.finditer(r"Figure\s+(\d+)", text)]
        try:
            page_images = list(page.images)
        except Exception:
            page_images = []
        for offset, image in enumerate(page_images):
            number = numbers[offset] if offset < len(numbers) else (numbers[-1] if numbers else None)
            if number is not None and number not in num_to_image:
                num_to_image[number] = image
    full = "\n".join(pages_text)
    captions: dict[int, str] = {}
    for match in re.finditer(r"Figure\s+(\d+)[)\.:]?\s*([^\n]{0,180})", full):
        number = int(match.group(1))
        caption = re.sub(r"\s+", " ", match.group(2)).strip()
        if caption and (number not in captions or len(caption) > len(captions[number])):
            captions[number] = caption
    return [
        {"figure_no": number, "caption": captions.get(number, ""), "image": image}
        for number, image in sorted(num_to_image.items())
    ]


def _encode_pdf_image(report: Path, figure: dict[str, Any]) -> dict[str, Any] | None:
    image = figure["image"]
    data = getattr(image, "data", b"")
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    name = (getattr(image, "name", "") or "").lower()
    mime = "image/jpeg" if name.endswith((".jpg", ".jpeg")) else "image/png"
    caption = figure["caption"]
    label = f"{report.name} · figure {figure['figure_no']}" + (f": {caption[:70]}" if caption else "")
    return {
        "name": label,
        "data_url": f"data:{mime};base64,{base64.b64encode(data).decode()}",
        "source": "pdf",
    }


def _match_pdf_figures(report: Path, query: str, limit: int = 4) -> list[dict[str, Any]]:
    """Figures whose caption best matches the question text. Returns the top scorers
    (so 1-to-many is fine) and nothing when there is no real overlap."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    scored = []
    for figure in _pdf_caption_figures(report):
        score = len(query_tokens & _tokens(figure["caption"]))
        if score >= 1:
            scored.append((score, figure))
    if not scored:
        return []
    top = max(score for score, _ in scored)
    winners = sorted((figure for score, figure in scored if score == top), key=lambda f: f["figure_no"])
    # One or two weak (single-token) matches are plausible; more than that is just noise.
    if top < 2 and len(winners) > 2:
        return []
    chosen = winners[:limit]
    out = []
    for figure in chosen:
        encoded = _encode_pdf_image(report, figure)
        if encoded:
            out.append(encoded)
    return out


def resolve_figures(
    root: Path,
    question: int,
    text: str = "",
    report_path: Path | None = None,
    match_text: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for path in _file_figures(root, question, text)[:limit]:
        encoded = _encode_path(path, root)
        if encoded:
            figures.append(encoded)
    if not figures and report_path and report_path.is_file() and report_path.suffix.lower() == ".pdf":
        figures.extend(_match_pdf_figures(report_path, match_text or text))
    return figures
