"""Opened-vault-only, read-only local source rendition boundary."""
from __future__ import annotations

import json
import os
import base64
import hashlib
from pathlib import Path
import re
import select
import subprocess
import sys
import threading
import time

from .source_preview_worker import MAX_RESPONSE

OPERATION = 'viva.documents.preview.read'
REASONS = frozenset({'invalid_request', 'original_unavailable', 'identity_unverifiable',
                     'unsupported_type', 'unsupported_encoding', 'over_limit',
                     'encrypted_pdf', 'damaged_original', 'page_unavailable',
                     'timed_out', 'renderer_unavailable'})
_ID = re.compile(r'[0-9a-f]{64}\Z')
_SLOT = threading.Lock()
WORKER_TIMEOUT = 10.0


def unavailable(document_id, reason):
    return dict(schema_version=1, status='unavailable', document_id=document_id, reason=reason)


def worker_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--source-preview-worker']
    return [sys.executable, str(Path(__file__).with_name('source_preview_worker.py'))]


def run_worker(data, page):
    """Anonymous pipes, empty environment, fixed command and bounded output.

    A dedicated process avoids handing parser libraries the vault key. This is
    measured process isolation, not network or OS memory sandboxing.
    """
    process = subprocess.Popen(worker_command(), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env={}, cwd='/', close_fds=True)
    def write_input():
        try:
            process.stdin.write(str(page).encode('ascii') + b'\n' + data)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    writer = threading.Thread(target=write_input, daemon=True)
    writer.start()
    output = bytearray()
    deadline = time.monotonic() + WORKER_TIMEOUT
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {'status': 'unavailable', 'reason': 'timed_out'}
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                return {'status': 'unavailable', 'reason': 'timed_out'}
            import os
            chunk = os.read(process.stdout.fileno(), min(65536, MAX_RESPONSE + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > MAX_RESPONSE:
                return {'status': 'unavailable', 'reason': 'over_limit'}
        process.wait(timeout=max(.001, deadline - time.monotonic()))
        if process.returncode != 0:
            return {'status': 'unavailable', 'reason': 'renderer_unavailable'}
        result = json.loads(output)
        if not isinstance(result, dict):
            raise ValueError('invalid worker result')
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        writer.join(timeout=1)


def _valid_rendition(result, page):
    if (result.get('source_kind') not in ('pdf', 'image', 'text') or
            type(result.get('page')) is not int or result['page'] != page or
            type(result.get('page_count')) is not int or
            not page <= result['page_count'] <= 200 or
            not isinstance(result.get('rendition_sha256'), str) or
            not _ID.fullmatch(result['rendition_sha256'])):
        return False
    text = result.get('text')
    if text is not None and (not isinstance(text, str) or len(text.encode('utf-8')) > 256 * 1024):
        return False
    if result['source_kind'] == 'text':
        return (isinstance(text, str) and page == result['page_count'] == 1 and
                all(result.get(key) is None for key in ('png_base64', 'width', 'height')) and
                hashlib.sha256(text.encode('utf-8')).hexdigest() == result['rendition_sha256'])
    if (not isinstance(result.get('png_base64'), str) or
            len(result['png_base64']) > 4 * ((1024 * 1024 + 2) // 3) or
            any(type(result.get(key)) is not int or not 1 <= result[key] <= 2000
                for key in ('width', 'height')) or
            result['width'] * result['height'] > 4000000 or
            (result['source_kind'] == 'image' and (page != 1 or result['page_count'] != 1))):
        return False
    png = base64.b64decode(result['png_base64'], validate=True)
    return (len(png) <= 1024 * 1024 and png.startswith(b'\x89PNG\r\n\x1a\n') and
            hashlib.sha256(png).hexdigest() == result['rendition_sha256'])


def _capture_witness(vault, doc):
    """Hold one authenticated immutable SQL generation through rendering."""
    expected = vault.ledger.store.authenticated_identity()
    if expected[0] is None or expected[1] is None or vault.read_store is None:
        raise ValueError('current source identity unavailable')
    revision = vault.read_store.open_reader()
    try:
        source = vault.read_store.authenticated_source_identity(revision)
        if (source['count'], source['head']) != expected[:2]:
            raise ValueError('stale source identity')
        captured = revision.preview_capture_identity(doc)
        if vault.read_store.authenticated_source_identity(revision) != source:
            raise ValueError('source revision changed')
        if vault.ledger.store.authenticated_identity() != expected:
            raise ValueError('source head changed')
        return captured, (expected, source), revision
    except Exception:
        revision.close()
        raise


def _verify_witness(vault, revision, witness):
    expected, source = witness
    if vault.ledger.store.authenticated_identity() != expected:
        raise ValueError('source head changed')
    if vault.read_store.authenticated_source_identity(revision) != source:
        raise ValueError('source revision changed')
    if vault.ledger.store.authenticated_identity() != expected:
        raise ValueError('source head changed')


def preview_document(vault, payload):
    valid_id = payload.get('document_id') if isinstance(payload, dict) else None
    doc = valid_id if isinstance(valid_id, str) and _ID.fullmatch(valid_id) else ''
    if (not isinstance(payload, dict) or set(payload) != {'document_id', 'page'} or
            not doc or type(payload['page']) is not int or payload['page'] < 1):
        return unavailable('', 'invalid_request')
    if (sys.platform == 'win32' or os.name != 'posix' or
            not all(hasattr(os, flag) for flag in ('O_DIRECTORY', 'O_NOFOLLOW'))):
        return unavailable(doc, 'renderer_unavailable')
    page = payload['page']
    if page > 200:
        return unavailable(doc, 'page_unavailable')
    if not _SLOT.acquire(blocking=False):
        return unavailable(doc, 'timed_out')
    revision = None
    try:
        try:
            captured, witness, revision = _capture_witness(vault, doc)
        except Exception:
            return unavailable(doc, 'identity_unverifiable')
        if captured is None:
            return unavailable(doc, 'original_unavailable')
        try:
            data = vault.raw.get_bounded(doc)
        except FileNotFoundError:
            return unavailable(doc, 'original_unavailable')
        except OverflowError:
            return unavailable(doc, 'over_limit')
        except Exception:
            return unavailable(doc, 'damaged_original')
        result = run_worker(data, page)
        try:
            _verify_witness(vault, revision, witness)
        except Exception:
            return unavailable(doc, 'identity_unverifiable')
        if result.get('status') == 'unavailable':
            reason = result.get('reason')
            return unavailable(doc, reason if reason in REASONS else 'renderer_unavailable')
        required = {'status', 'source_kind', 'page', 'page_count', 'rendition_sha256',
                    'text', 'png_base64', 'width', 'height'}
        if (set(result) != required or result.get('status') != 'ready' or
                not _valid_rendition(result, page)):
            return unavailable(doc, 'renderer_unavailable')
        response = dict(schema_version=1, document_id=doc, original_sha256=doc, **result)
        if len(json.dumps(response, ensure_ascii=True).encode()) > MAX_RESPONSE:
            return unavailable(doc, 'over_limit')
        return response
    except Exception:
        return unavailable(doc, 'renderer_unavailable')
    finally:
        try:
            if revision is not None:
                revision.close()
        except Exception:
            # Never serialize a native close error or file path to the caller.
            pass
        finally:
            _SLOT.release()
