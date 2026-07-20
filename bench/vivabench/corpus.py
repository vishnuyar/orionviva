"""Document handling: content hashing and PDF/image -> page images.

Pages are rendered to PNG once and cached content-addressed (by the source
file's sha256), so re-runs are cheap and every run record can point at the
exact bytes a model saw.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from .config import Document
from .models.base import PageImage

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
