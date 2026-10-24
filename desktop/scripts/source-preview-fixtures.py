"""Create local, fictional originals for the production-browser preview check."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys

from PIL import Image
from viva.ledger.events import document_captured
from viva.vault import Vault


def original_pdf() -> bytes:
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for marker in (b'SOURCE ALPHA PAGE ONE', b'SOURCE BETA PAGE TWO'):
        commands = (b'BT /F1 14 Tf 32 340 Td (' + marker
                    + b') Tj 0 -28 Td (FICTIONAL STATEMENT - ORIGINAL CONTENT CHECK) Tj '
                    + b'0 -28 Td /F1 9 Tf (Small source text remains legible at local preview resolution.) Tj ET')
        objects.append(b'<< /Length ' + str(len(commands)).encode() + b' >>\nstream\n' + commands + b'\nendstream')
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f'{index} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = len(data)
    data.extend(b'xref\n0 8\n' + b'0' * 10 + b' 65535 f \n')
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    return bytes(data)


def main(root: Path) -> None:
    directory = root / 'preview-vault'
    if directory.exists():
        raise ValueError('preview fixture destination already exists')
    image = io.BytesIO()
    Image.new('RGB', (80, 40), (50, 120, 90)).save(image, format='PNG')
    documents = {
        'preview-source.pdf': original_pdf(),
        'preview-text.txt': b'LOCAL TEXT ORIGINAL <script>globalThis.__previewInjection=true</script>\nSecond source line.\n',
        'preview-image.png': image.getvalue(),
    }
    vault = Vault.open(directory, 'synthetic browser phrase', create=True)
    try:
        identities = {}
        for filename, content in documents.items():
            document_id = vault.raw.put(content)
            vault.ledger.append(document_captured(document_id, filename, len(content), 'other', 1.0, '2026-01-31T12:00:00Z'))
            identities[filename] = document_id
        intact, count = vault.ledger.store.verify_chain()
        if not intact or count != len(documents):
            raise ValueError('synthetic preview fixture chain is incomplete')
        print(json.dumps({'vault': str(directory), 'documents': identities}))
    finally:
        vault.close()


if __name__ == '__main__':
    main(Path(sys.argv[1]))
