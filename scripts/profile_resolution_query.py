"""Paired public25 caller attribution through the normal Vault ingestion path.

Run once per source root in separate processes. Timings include profiler/wrapper
cost and cannot establish an unprofiled end-to-end speedup or 794-document result.
"""
from __future__ import annotations
import ast
import cProfile
import dataclasses
from decimal import Decimal
from datetime import date, datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pstats
import secrets
import signal
import sys
import time

ROOTS = {'baseline': Path('/Users/vishnu/orionviva-consolidated'),
         'candidate': Path('/Users/vishnu/orionviva-resolution-query')}
HELPER = Path('/Users/vishnu/orionviva-consolidated/scripts/profile_normal_sample_import.py')
HELPER_SHA = '34938b3f925e71a1bd4ef097f6c54827c4da16e9d7903baf269d95c77f0e979f'
PINS = Path('/Users/vishnu/OrionViva-Preservation/2026-11-05-consolidation/resolution-query/MEASUREMENT-PINS.json')


def run(mode, output):
    root = ROOTS[mode]
    output = Path(output)
    assert output.is_absolute() and output == output.resolve() and not output.exists()
    assert output.parent == output.parent.resolve()
    output.mkdir(mode=0o700)
    for name in ('home', 'tmp', 'profiles', 'merchant', 'config'):
        (output/name).mkdir(mode=0o700)
    (output/'empty.env').write_bytes(b'')
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin', HOME=str(output/'home'), TMPDIR=str(output/'tmp'),
        VIVA_ENV_FILE=str(output/'empty.env'), VIVA_PROFILES=str(output/'profiles'),
        MERCHANTCORE_HOME=str(output/'merchant'), XDG_CONFIG_HOME=str(output/'config'),
        VIVA_CATALOG=str(output/'catalog.json'), PYTHONDONTWRITEBYTECODE='1')
    paths = json.loads((Path('/Users/vishnu/OrionViva-Preservation/2026-11-05-consolidation')/
        'normal-profile25-invocation45-packet/FROZEN.json').read_text())['import_roots']
    sys.path[:] = [str(root/part) for part in ('product', 'core', 'merchant', 'bench')] + paths[4:]
    pins = json.loads(PINS.read_text())
    source = pins['sources'][mode]
    def identity():
        for path, wanted in {**source, **pins['dependencies']}.items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == wanted
        for name, module in tuple(sys.modules.items()):
            path = getattr(module, '__file__', None)
            if name.split('.')[0] in ('viva', 'vivacore', 'merchantcore') and path:
                assert Path(path).is_relative_to(root) and path in source
    identity()
    forbidden = []
    def audit(event, args):
        if event.startswith(('socket.connect', 'socket.bind', 'socket.getaddrinfo',
                             'subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn', 'os.system', 'os.fork')):
            forbidden.append(event)
            raise RuntimeError('forbidden runtime operation')
    sys.addaudithook(audit)
    def timeout(*args):
        raise TimeoutError('public25 diagnostic watchdog')
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 600)
    assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == HELPER_SHA
    spec = importlib.util.spec_from_file_location('preserved_profile_controls', HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    from viva.vault import Vault
    from viva.ledger import Ledger
    from viva.sample.resources import load_pack
    from viva.sample.curation import CuratedReader
    from viva.sample.instances import verify_replay_agreement
    from viva.ingest import capture_and_ingest, sweep
    from viva.demo import _prepare_demo_read_store
    import viva.env
    viva.env.CONFIG_HOME = output/'config'
    result = dict(mode=mode, source_root=str(root), status='STOP', forbidden=forbidden,
                  label='PROFILED_PAIRED_PUBLIC25_CALLER_ATTRIBUTION', paid_calls=0)
    profiler = cProfile.Profile()
    calls = {}
    publication = dict(calls=0, seconds=0.0)
    original_query, original_publish = Ledger.projection, Ledger._publish_basis
    # Reuse the existing public-answer snapshot without importing test fixtures.
    snapshot_path = root/'product/tests/test_read_store_coverage_register.py'
    tree = ast.parse(snapshot_path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_financial_snapshot')
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(snapshot_path), 'exec'), scope)
    def financial_state(ledger):
        event_ids = {event.event_id: 'event@'+str(i) for i, event in enumerate(ledger.events())}
        def encode(value):
            if dataclasses.is_dataclass(value):
                return ['dataclass', type(value).__qualname__, [[f.name, encode(getattr(value, f.name))] for f in dataclasses.fields(value)]]
            if isinstance(value, dict):
                pairs = [[encode(k), encode(v)] for k, v in value.items()]
                return ['dict', sorted(pairs, key=lambda pair: json.dumps(pair[0], sort_keys=True))]
            if isinstance(value, (tuple, list, set, frozenset)):
                rows = [encode(v) for v in value]
                if isinstance(value, (set, frozenset)):
                    rows.sort(key=lambda item: json.dumps(item, sort_keys=True))
                return [type(value).__name__, rows]
            if isinstance(value, Decimal):
                return ['Decimal', str(value)]
            if isinstance(value, (date, datetime)):
                return [type(value).__name__, value.isoformat()]
            if isinstance(value, str):
                return event_ids.get(value, value)
            if value is None or type(value) in (int, float, bool):
                return value
            raise TypeError('unexpected financial snapshot value type')
        return encode(scope['_financial_snapshot'](ledger.projection()))
    def projection(self):
        caller = sys._getframe(1)
        filename = Path(caller.f_code.co_filename)
        label = (str(filename.relative_to(root)) if filename.is_relative_to(root) else filename.name)
        key = f'{label}:{caller.f_lineno}:{caller.f_code.co_name}'
        start = time.perf_counter()
        try:
            return original_query(self)
        finally:
            row = calls.setdefault(key, dict(calls=0, seconds=0.0))
            row['calls'] += 1
            row['seconds'] += time.perf_counter()-start
    def publish(self):
        start = time.perf_counter()
        try:
            return original_publish(self)
        finally:
            publication['calls'] += 1
            publication['seconds'] += time.perf_counter()-start
    secret = secrets.token_urlsafe(32)
    vault = None
    try:
        pack = load_pack()
        docs = pack.documents[:25]
        reader = CuratedReader(pack)
        result['inputs'] = [[d['id'], d['sha256']] for d in docs]
        vault = Vault.open(output/'vault', secret, start_read_store_worker=False)
        outcomes = []
        Ledger.projection, Ledger._publish_basis = projection, publish
        start = time.perf_counter()
        profiler.enable()
        try:
            for i, document in enumerate(docs, 1):
                outcome = capture_and_ingest(vault.raw, vault.ledger, pack.original(document), reader,
                    filename=document['file'], captured_at='2026-11-05T00:00:00+00:00')
                assert outcome.doc_id == document['sha256']
                outcomes.append([outcome.action, outcome.grade])
                (output/'progress.json').write_text(json.dumps({'completed': i}))
        finally:
            profiler.disable()
            result['ingress_seconds'] = time.perf_counter()-start
            Ledger.projection, Ledger._publish_basis = original_query, original_publish
        result.update(outcomes=outcomes, projection_callers=calls, publication=publication)
        stats = pstats.Stats(profiler)
        edges = []
        for (filename, line, name), value in stats.stats.items():
            if name == 'deepcopy' and Path(filename).name == 'copy.py':
                result['deepcopy'] = dict(primitive_calls=value[0], total_calls=value[1], self_seconds=value[2], cumulative_seconds=value[3])
                for (caller_file, caller_line, caller_name), cost in value[4].items():
                    path = Path(caller_file)
                    label = str(path.relative_to(root)) if path.is_relative_to(root) else path.name
                    edges.append(dict(source=label, line=caller_line, function=caller_name,
                        total_calls=cost[0], primitive_calls=cost[1], self_seconds=cost[2], cumulative_seconds=cost[3]))
        result['deepcopy_direct_caller_edges'] = edges
        result['scalar_profile_rows'] = [dict(source=str(Path(f).relative_to(root)), line=l, function=n,
            primitive_calls=v[0], total_calls=v[1], self_seconds=v[2], cumulative_seconds=v[3])
            for (f, l, n), v in stats.stats.items() if n == 'is_resolved' and Path(f).is_relative_to(root)]
        sweep(vault.ledger)
        _prepare_demo_read_store(vault)
        result['verification'] = helper.conservation(vault, pack, docs)
        assert verify_replay_agreement(vault.ledger)['state'] == 'equal'
        state = financial_state(vault.ledger)
        (output/'financial-state.json').write_text(json.dumps(state, sort_keys=True, allow_nan=False)+'\n')
        result['financial_state_sha256'] = hashlib.sha256((output/'financial-state.json').read_bytes()).hexdigest()
        vault.close()
        vault = Vault.open(output/'vault', secret, create=False, start_read_store_worker=False)
        _prepare_demo_read_store(vault)
        assert helper.conservation(vault, pack, docs) == result['verification']
        assert verify_replay_agreement(vault.ledger)['state'] == 'equal'
        assert financial_state(vault.ledger) == state
        identity()
        assert not forbidden
        result['status'] = 'COMPLETE_PUBLIC25_VERIFIED'
    finally:
        profiler.disable()
        Ledger.projection, Ledger._publish_basis = original_query, original_publish
        if vault is not None:
            vault.close()
        secret = None
        signal.setitimer(signal.ITIMER_REAL, 0)
        (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return 0 if result['status'] == 'COMPLETE_PUBLIC25_VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1], sys.argv[2]))
