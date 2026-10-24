"""Disposable local rendition worker. Receives bytes/page only; no vault imports.

Process isolation and enforced wall/output bounds are not an OS sandbox.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import sys

MAX_INPUT = 8 * 1024 * 1024
MAX_TEXT = 256 * 1024
MAX_PNG = 1024 * 1024
MAX_RESPONSE = 1536 * 1024


class Refusal(Exception):
    def __init__(self, reason):
        self.reason = reason


def text_value(data):
    if len(data) > MAX_TEXT:
        raise Refusal('over_limit')
    try:
        value = data.decode('utf-8', errors='strict')
    except UnicodeError:
        raise Refusal('unsupported_encoding') from None
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise Refusal('unsupported_encoding')
    return value


def png_value(image):
    from PIL import Image
    converted = image.convert('RGB')
    # A fresh pixel-only image prevents Pillow from copying ICC/EXIF/info into
    # the normalized PNG. Conversion alone retains source metadata.
    image = Image.frombytes('RGB', converted.size, converted.tobytes())
    image.thumbnail((2000, 2000))
    for attempt in range(2):
        output = io.BytesIO()
        image.save(output, format='PNG', optimize=False)
        value = output.getvalue()
        if len(value) <= MAX_PNG:
            return value, image.width, image.height
        if not attempt:
            image.thumbnail((1400, 1400))
    raise Refusal('over_limit')


def render(data, page):
    if len(data) > MAX_INPUT:
        raise Refusal('over_limit')
    if data.startswith(b'%PDF-'):
        try:
            import pypdfium2 as pdfium
        except ImportError:
            raise Refusal('renderer_unavailable') from None
        try:
            document = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as error:
            if getattr(error, 'err_code', None) == 4:
                raise Refusal('encrypted_pdf') from None
            raise Refusal('damaged_original') from None
        try:
            count = len(document)
            if count < 1 or count > 200:
                raise Refusal('over_limit')
            if page > count:
                raise Refusal('page_unavailable')
            selected = document[page - 1]
            try:
                width, height = selected.get_size()
                if width <= 0 or height <= 0 or width > 100000 or height > 100000:
                    raise Refusal('over_limit')
                scale = min(2.0, 2000 / max(width, height))
                if int(width * scale + 1) * int(height * scale + 1) > 4000000:
                    raise Refusal('over_limit')
                bitmap = selected.render(scale=scale)
                try:
                    png, width, height = png_value(bitmap.to_pil())
                finally:
                    bitmap.close()
                text_page = selected.get_textpage()
                try:
                    # Avoid an unbounded text allocation before validating it.
                    if text_page.count_chars() > MAX_TEXT:
                        alternative = None
                    else:
                        extracted = text_page.get_text_range()
                        alternative = extracted if len(extracted.encode('utf-8')) <= MAX_TEXT else None
                finally:
                    text_page.close()
            finally:
                selected.close()
        finally:
            document.close()
        kind = 'pdf'
    elif data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff'):
        if page != 1:
            raise Refusal('page_unavailable')
        try:
            from PIL import Image, ImageOps
        except ImportError:
            raise Refusal('renderer_unavailable') from None
        Image.MAX_IMAGE_PIXELS = 4000000
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            try:
                image = Image.open(io.BytesIO(data))
            except (Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise Refusal('over_limit') from None
            try:
                if image.format not in ('PNG', 'JPEG') or getattr(image, 'n_frames', 1) != 1:
                    raise Refusal('unsupported_type')
                if image.width * image.height > 4000000 or max(image.size) > 2000:
                    raise Refusal('over_limit')
                image.load()
                png, width, height = png_value(ImageOps.exif_transpose(image))
            finally:
                image.close()
        kind, count, alternative = 'image', 1, None
    else:
        if page != 1:
            raise Refusal('page_unavailable')
        # Reject recognized active/container formats rather than treat as text.
        if data.lstrip().lower().startswith((b'<!doctype html', b'<html', b'<?xml', b'<svg')) or data.startswith((b'PK\x03\x04', b'GIF8', b'RIFF')):
            raise Refusal('unsupported_type')
        value = text_value(data)
        return dict(source_kind='text', page=1, page_count=1, text=value,
                    png_base64=None, width=None, height=None,
                    rendition_sha256=hashlib.sha256(data).hexdigest())
    return dict(source_kind=kind, page=page, page_count=count, text=alternative,
                png_base64=base64.b64encode(png).decode('ascii'), width=width, height=height,
                rendition_sha256=hashlib.sha256(png).hexdigest())


def main():
    try:
        # Header is a bounded decimal page followed by raw original bytes.
        header = sys.stdin.buffer.readline(16)
        if not header.endswith(b'\n') or not header[:-1].isdigit():
            raise Refusal('invalid_request')
        page = int(header)
        if not 1 <= page <= 200:
            raise Refusal('page_unavailable')
        data = sys.stdin.buffer.read(MAX_INPUT + 1)
        result = {'status': 'ready', **render(data, page)}
    except Refusal as error:
        result = {'status': 'unavailable', 'reason': error.reason}
    except Exception:
        result = {'status': 'unavailable', 'reason': 'damaged_original'}
    encoded = json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode()
    if len(encoded) > MAX_RESPONSE - 512:
        encoded = b'{"status":"unavailable","reason":"over_limit"}'
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
