"""Closed application entry for the bundled, provider-free sample constructor."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

MAX_REQUEST_BYTES = 4096
MAX_REPORT_BYTES = 4000000


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate sample worker field')
        result[key] = value
    return result


def _instance(request):
    from .instances import SampleBuildError, _ordinary
    from .resources import VERSION

    if (type(request) is not dict or set(request) != {'operation', 'instance'}
            or request['operation'] not in ('build', 'restore', 'reopen')
            or type(request['instance']) is not str):
        raise SampleBuildError('invalid sample worker request')
    path = Path(request['instance'])
    if (not path.is_absolute() or path.resolve(strict=True) != path
            or re.fullmatch('[0-9a-f]{32}', path.name) is None
            or path.parent.name != VERSION or path.parent.parent.name != 'sample-vaults'):
        raise SampleBuildError('invalid versioned sample worker path')
    for directory in (path, path.parent, path.parent.parent, path.parent.parent.parent,
                      path/'home', path/'learned', path/'learned/profiles', path/'tmp'):
        _ordinary(directory)
    for name in ('sample-staging.json', 'empty.env'):
        _ordinary(path/name, False)
    if (path/'empty.env').stat().st_size:
        raise SampleBuildError('sample worker environment must be empty')
    receipt = path/'sample-staging.json'
    if receipt.stat().st_size > 512:
        raise SampleBuildError('sample staging receipt exceeds its bound')
    staging = json.loads(receipt.read_bytes(), object_pairs_hook=_closed_object)
    if staging != {'version': VERSION, 'instance_id': path.name}:
        raise SampleBuildError('sample worker staging receipt differs')
    if request['operation'] == 'reopen':
        _ordinary(path/'sample-instance.json', False)
        _ordinary(path/'vault')
        if (path/'sample-instance.json').stat().st_size > MAX_REPORT_BYTES:
            raise SampleBuildError('sample readiness receipt exceeds its bound')
    elif (path/'vault').exists() or (path/'vault').is_symlink():
        raise SampleBuildError('sample construction requires a fresh instance')
    return path


def run_request(encoded):
    if type(encoded) is not bytes or not 0 < len(encoded) <= MAX_REQUEST_BYTES:
        raise ValueError('sample worker request exceeds its bound')
    request = json.loads(encoded.decode('utf-8'), object_pairs_hook=_closed_object)
    instance = _instance(request)
    # Re-establish the same key-free environment even for an explicit manual
    # application invocation. No request field can supply configuration.
    os.environ.clear()
    os.environ.update({'PATH':'/usr/bin:/bin', 'HOME':str(instance/'home'),
        'MERCHANTCORE_HOME':str(instance/'learned'), 'VIVA_PROFILES':str(instance/'learned/profiles'),
        'VIVA_CATALOG':str(instance/'learned/catalog.json'), 'VIVA_ENV_FILE':str(instance/'empty.env'),
        'LANG':'en_US.UTF-8', 'TMPDIR':str(instance/'tmp')})
    from .instances import _worker, _restore_worker, _reopen_worker
    return {'build':_worker, 'restore':_restore_worker, 'reopen':_reopen_worker}[request['operation']](instance)


def main():
    try:
        result = run_request(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
        encoded = json.dumps(result, sort_keys=True).encode('utf-8')
        if len(encoded) > MAX_REPORT_BYTES:
            raise ValueError('sample worker report exceeds its bound')
        sys.stdout.buffer.write(encoded + b'\n')
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        # Detailed construction evidence belongs to the owned instance records.
        print('Sample worker could not complete its closed request.', file=sys.stderr)
        return 1
