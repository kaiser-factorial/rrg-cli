"""Resolve a question's figures, with fallbacks.

Primary: standalone image files whose name carries the question number (`q1_fig2.png`),
searched recursively (so appendix/sub-folders are covered). Fallback 1: figures the
question's text references by token (e.g. `` `q1_fig2` ``). Fallback 2: when no figure
files exist but the origin report is a PDF (figures live in its appendix), pull the
matching figure out of the PDF — figure N for question N.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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


# "Figure 4", "Fig. 4", "Appendix A", "Appendix, Figure 4", "see Appendix B" — label = number or single letter.
# Figure branch is tried first; the Appendix branch only matches a standalone label (so
# "Appendix, Figure 4" resolves to "4", not the "F" of Figure).
_LABEL_REF = re.compile(
    r"(?:(?:Figure|Fig\.?)\s*[,:]?\s*(\d{1,3}|[A-Z])|Appendix\s*[,:]?\s*([A-Z]|\d{1,3}))\b",
    re.IGNORECASE,
)


def _label_of(match: re.Match[str]) -> str:
    return (match.group(1) or match.group(2)).upper()


def _label_sort_key(label: str) -> tuple[int, Any]:
    return (0, int(label)) if label.isdigit() else (1, label)


def _pdf_caption_figures(report: Path) -> list[dict[str, Any]]:
    """Each appendix figure with its label (number or letter), the body text around the
    reference to it, and the embedded image (paired per page)."""
    try:
        import pypdf
    except ImportError:
        logger.warning("pypdf is not installed; cannot extract figures from %s", report.name)
        return []
    try:
        reader = pypdf.PdfReader(str(report))
    except Exception as exc:
        logger.warning("could not open PDF %s for figure extraction: %s", report.name, exc)
        return []
    pages_text: list[str] = []
    label_to_image: dict[str, Any] = {}
    images_failed = False  # log the recurring per-page failure (e.g. Pillow missing) only once
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages_text.append(text)
        labels = [_label_of(match) for match in _LABEL_REF.finditer(text)]
        try:
            page_images = list(page.images)
        except Exception as exc:
            if not images_failed:
                logger.warning(
                    "image extraction from %s failed — figures will be missing "
                    "(if this is 'pillow is required', run: pip install pillow): %s",
                    report.name,
                    exc,
                )
                images_failed = True
            page_images = []
        for offset, image in enumerate(page_images):
            label = labels[offset] if offset < len(labels) else (labels[-1] if labels else None)
            if label is not None and label not in label_to_image:
                label_to_image[label] = image
    full = "\n".join(pages_text)
    # Context = a window around each reference (the question being discussed), richest kept.
    contexts: dict[str, str] = {}
    for match in _LABEL_REF.finditer(full):
        label = _label_of(match)
        line = full[match.end() :].split("\n", 1)[0]  # the rest of the label's own line = its caption
        window = re.sub(r"\s+", " ", line).strip()[:180]
        if label not in contexts or len(window) > len(contexts[label]):
            contexts[label] = window
    return [
        {"label": label, "caption": contexts.get(label, ""), "image": image}
        for label, image in sorted(label_to_image.items(), key=lambda kv: _label_sort_key(kv[0]))
    ]


def _encode_pdf_image(report: Path, figure: dict[str, Any]) -> dict[str, Any] | None:
    image = figure["image"]
    data = getattr(image, "data", b"")
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    name = (getattr(image, "name", "") or "").lower()
    mime = "image/jpeg" if name.endswith((".jpg", ".jpeg")) else "image/png"
    caption = figure["caption"]
    label = f"{report.name} · figure {figure['label']}" + (f": {caption[:70]}" if caption else "")
    return {
        "name": label,
        "data_url": f"data:{mime};base64,{base64.b64encode(data).decode()}",
        "source": "pdf",
    }


def _match_pdf_figures(report: Path, query: str, limit: int = 4) -> list[dict[str, Any]]:
    """Figures whose referencing text best matches the question. Returns the top scorers
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
    winners = sorted((figure for score, figure in scored if score == top), key=lambda f: _label_sort_key(f["label"]))
    # One or two weak (single-token) matches are plausible; more than that is just noise.
    if top < 2 and len(winners) > 2:
        return []
    out = []
    for figure in winners[:limit]:
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
