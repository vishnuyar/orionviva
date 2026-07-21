"""Document handling: content hashing, PDF/image -> page images, and the
issuer's own embedded text layer.

Pages are rendered to PNG once and cached content-addressed (by the source
file's sha256), so re-runs are cheap and every run record can point at the
exact bytes a model saw. Extracted text is cached the same way, beside them.

On the text layer: a digital PDF already carries the characters the institution
rendered. That is not a reading to be verified — it is what the issuer wrote.
Extracting it is lossless, local, and free, and it removes the OCR error class
outright for documents that have one. Scans have no text layer; ``page_texts``
reports that honestly (empty strings) rather than inventing coverage.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from .config import Document
from .models.base import PageImage

# A page with no text layer is only a problem if something is PRINTED on it.
# "Intentionally left blank" pages and true blanks have no claims to miss; a
# scanned page does. Ink above this fraction of pixels means real content.
_INK_FRACTION_BLANK = 0.005

# Rendering scale: ~200 DPI equivalent. High enough that small print survives,
# low enough that a page stays in the low hundreds of KB.
_RENDER_SCALE = 200 / 72
_MAX_EDGE_PX = 2000  # uniform cap so every candidate sees comparable input


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render_pages(doc: Document, cache_dir: Path) -> list[PageImage]:
    """Render a document's pages to PNGs, cached by source-file hash."""
    if not doc.file.exists():
        raise FileNotFoundError(f"Document '{doc.id}': file not found: {doc.file}")

    src_hash = file_sha256(doc.file)
    doc_cache = cache_dir / src_hash
    doc_cache.mkdir(parents=True, exist_ok=True)

    cached = sorted(doc_cache.glob("page-*.png"))
    if cached:
        return [_page_image(i + 1, p.read_bytes()) for i, p in enumerate(cached)]

    suffix = doc.file.suffix.lower()
    if suffix == ".pdf":
        pngs = _render_pdf(doc.file)
    elif suffix in (".png", ".jpg", ".jpeg", ".webp", ".tiff", ".heic"):
        pngs = [_normalize_image(doc.file.read_bytes())]
    else:
        raise ValueError(
            f"Document '{doc.id}': unsupported file type '{suffix}'. "
            "Supported: PDF and common image formats."
        )

    pages: list[PageImage] = []
    for i, png in enumerate(pngs, start=1):
        (doc_cache / f"page-{i:03d}.png").write_bytes(png)
        pages.append(_page_image(i, png))
    return pages


def page_texts(doc: Document, cache_dir: Path) -> list[str]:
    """The issuer's embedded text, one string per page, cached by source hash.

    Returns one entry per page, in page order. An empty string means this page
    has no usable text layer — a scan. Callers must treat that as a fact about
    the document, never as an extraction failure to paper over.
    """
    if not doc.file.exists():
        raise FileNotFoundError(f"Document '{doc.id}': file not found: {doc.file}")
    if doc.file.suffix.lower() != ".pdf":
        return []                       # images have no text layer, by definition

    doc_cache = cache_dir / file_sha256(doc.file)
    doc_cache.mkdir(parents=True, exist_ok=True)
    cached = sorted(doc_cache.glob("text-*.txt"))
    if cached:
        return [p.read_text(encoding="utf-8") for p in cached]

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(doc.file)
    try:
        texts: list[str] = []
        for i in range(len(pdf)):
            page = pdf[i]
            texts.append(page.get_textpage().get_text_range() or "")
            page.close()
    finally:
        pdf.close()

    for i, text in enumerate(texts, start=1):
        (doc_cache / f"text-{i:03d}.txt").write_text(text, encoding="utf-8")
    return texts


def text_gaps(doc: Document, cache_dir: Path) -> list[int]:
    """Page numbers where a text mode would silently miss printed content.

    A page qualifies only if it has no embedded text AND has ink on it — i.e. a
    scan. Genuinely blank pages ("This Page Intentionally Left Blank") are not
    gaps: there is nothing on them to lose. This is the concrete form of the
    "would we miss data?" risk, checked rather than assumed.
    """
    texts = page_texts(doc, cache_dir)
    if not texts:
        return []
    suspects = [i for i, t in enumerate(texts) if not t.strip()]
    if not suspects:
        return []

    import pypdfium2 as pdfium

    gaps: list[int] = []
    pdf = pdfium.PdfDocument(doc.file)
    try:
        for i in suspects:
            page = pdf[i]
            grey = page.render(scale=1.0).to_pil().convert("L")
            pixels = list(grey.getdata())
            ink = sum(1 for p in pixels if p < 200) / max(len(pixels), 1)
            if ink > _INK_FRACTION_BLANK:
                gaps.append(i + 1)
            page.close()
    finally:
        pdf.close()
    return gaps


def text_coverage(texts: list[str]) -> float:
    """Fraction of pages carrying embedded text. Blank pages count against it,
    so read it alongside ``text_gaps``, which is the one that matters."""
    if not texts:
        return 0.0
    return sum(1 for t in texts if t.strip()) / len(texts)


def _page_image(page_number: int, png: bytes) -> PageImage:
    return PageImage(
        page_number=page_number,
        png_bytes=png,
        sha256=hashlib.sha256(png).hexdigest(),
    )


def _render_pdf(path: Path) -> list[bytes]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        out: list[bytes] = []
        for page in pdf:
            bitmap = page.render(scale=_RENDER_SCALE)
            pil = bitmap.to_pil()
            out.append(_pil_to_capped_png(pil))
            page.close()
        return out
    finally:
        pdf.close()


def _normalize_image(raw: bytes) -> bytes:
    from PIL import Image

    pil = Image.open(io.BytesIO(raw))
    pil = pil.convert("RGB")
    return _pil_to_capped_png(pil)


def _pil_to_capped_png(pil) -> bytes:
    from PIL import Image

    w, h = pil.size
    longest = max(w, h)
    if longest > _MAX_EDGE_PX:
        ratio = _MAX_EDGE_PX / longest
        pil = pil.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    pil.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
