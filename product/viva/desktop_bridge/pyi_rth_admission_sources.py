"""Expose the sidecar's exact admission source resources to inspection."""


def _install():
    import inspect
    import json
    from pathlib import Path
    import sys
    from types import ModuleType

    from pyimod02_importers import PyiFrozenImporter

    if getattr(sys, 'frozen', False) is not True:
        raise RuntimeError('sidecar admission sources: invalid frozen host')
    extraction = Path(sys._MEIPASS)
    if not extraction.is_absolute() or not extraction.is_dir():
        raise RuntimeError('sidecar admission sources: invalid extraction root')
    root = extraction.resolve(strict=True)
    manifest = root / 'admission-source-map.json'
    if not manifest.resolve(strict=True).is_relative_to(root):
        raise RuntimeError('sidecar admission sources: manifest escapes extraction root')
    mapping = json.loads(manifest.read_bytes())
    if not isinstance(mapping, dict) or len(mapping) != 62:
        raise RuntimeError('sidecar admission sources: invalid source map')
    for name, relative in mapping.items():
        if not isinstance(name, str) or not isinstance(relative, str):
            raise RuntimeError('sidecar admission sources: invalid source map')
        ordinary = name.replace('.', '/') + '.py'
        package = name.replace('.', '/') + '/__init__.py'
        if relative not in (ordinary, package) or not all(
                part.isidentifier() for part in name.split('.')):
            raise RuntimeError('sidecar admission sources: invalid source map')

    expected = {
        'viva.answer_program.admission': 'viva/answer_program/admission.py',
        'viva.answer_program.admission_fixture': 'viva/answer_program/admission_fixture.py',
        'viva.answer_program.bind': 'viva/answer_program/bind.py',
        'viva.answer_program.capabilities': 'viva/answer_program/capabilities.py',
        'viva.answer_program.capability_fixture': 'viva/answer_program/capability_fixture.py',
        'viva.answer_program.compiler': 'viva/answer_program/compiler.py',
        'viva.answer_program.eval': 'viva/answer_program/eval.py',
        'viva.answer_program.evidence': 'viva/answer_program/evidence.py',
        'viva.answer_program.execute': 'viva/answer_program/execute.py',
        'viva.answer_program.intents': 'viva/answer_program/intents.py',
        'viva.answer_program.replay': 'viva/answer_program/replay.py',
        'viva.answer_program.runtime': 'viva/answer_program/runtime.py',
        'viva.answer_program.schema': 'viva/answer_program/schema.py',
        'viva.answer_program.validate': 'viva/answer_program/validate.py',
        'viva.ingest.brokerage': 'viva/ingest/brokerage.py',
        'viva.ledger.accounting': 'viva/ledger/accounting.py',
        'viva.ledger.events': 'viva/ledger/events.py',
        'viva.ledger.movement_identity': 'viva/ledger/movement_identity.py',
        'viva.ledger.networth': 'viva/ledger/networth.py',
        'viva.ledger.postings': 'viva/ledger/postings.py',
        'viva.ledger.projection': 'viva/ledger/projection/__init__.py',
        'viva.ledger.projection.accounts': 'viva/ledger/projection/accounts.py',
        'viva.ledger.projection.balances': 'viva/ledger/projection/balances.py',
        'viva.ledger.projection.categories': 'viva/ledger/projection/categories.py',
        'viva.ledger.projection.core': 'viva/ledger/projection/core.py',
        'viva.ledger.projection.current_period': 'viva/ledger/projection/current_period.py',
        'viva.ledger.projection.goals': 'viva/ledger/projection/goals.py',
        'viva.ledger.projection.measurements': 'viva/ledger/projection/measurements.py',
        'viva.ledger.projection.merchants': 'viva/ledger/projection/merchants.py',
        'viva.ledger.projection.movements': 'viva/ledger/projection/movements.py',
        'viva.ledger.projection.obligations': 'viva/ledger/projection/obligations.py',
        'viva.ledger.projection.positions': 'viva/ledger/projection/positions.py',
        'viva.ledger.projection.rhythm': 'viva/ledger/projection/rhythm.py',
        'viva.ledger.scenarios': 'viva/ledger/scenarios.py',
        'viva.ledger.statements': 'viva/ledger/statements.py',
        'viva.ledger.streams': 'viva/ledger/streams.py',
        'viva.quantity': 'viva/quantity.py',
        'viva.read_store.overview': 'viva/read_store/overview.py',
        'viva.render': 'viva/render.py',
        'viva.speak': 'viva/speak.py',
        'viva.surface.overview': 'viva/surface/overview.py',
        'viva.tools': 'viva/tools/__init__.py',
        'viva.tools.boundary': 'viva/tools/boundary.py',
        'viva.tools.compute': 'viva/tools/compute.py',
        'viva.tools.envelope': 'viva/tools/envelope.py',
        'viva.tools.ledger_aggregates': 'viva/tools/ledger_aggregates.py',
        'viva.tools.ledger_common': 'viva/tools/ledger_common.py',
        'viva.tools.ledger_movements': 'viva/tools/ledger_movements.py',
        'viva.tools.ledger_tools': 'viva/tools/ledger_tools.py',
        'viva.tools.ledger_vocabulary': 'viva/tools/ledger_vocabulary.py',
        'viva.tools.measurements': 'viva/tools/measurements.py',
        'viva.tools.projections': 'viva/tools/projections.py',
        'viva.tools.registry': 'viva/tools/registry.py',
        'viva.tools.runner': 'viva/tools/runner.py',
        'viva.tools.runner_binding': 'viva/tools/runner_binding.py',
        'viva.tools.runner_delivery': 'viva/tools/runner_delivery.py',
        'viva.tools.scenarios': 'viva/tools/scenarios.py',
        'viva.tools.shape': 'viva/tools/shape.py',
        'vivacore.models.openai_compat': 'vivacore/models/openai_compat.py',
        'vivacore.models.spec': 'vivacore/models/spec.py',
        'vivacore.verify.arithmetic': 'vivacore/verify/arithmetic.py',
        'vivacore.verify.normalize': 'vivacore/verify/normalize.py',
    }
    if mapping != expected:
        raise RuntimeError('sidecar admission sources: incomplete canonical source map')

    original = inspect.getsourcefile

    def getsourcefile(held):
        if not isinstance(held, ModuleType) or held.__name__ not in mapping:
            return original(held)
        name = held.__name__
        spec = held.__spec__
        loader = held.__loader__
        relative = mapping[name]
        expected = root / (relative + 'c')
        package = relative.endswith('/__init__.py')
        if (sys.modules.get(name) is not held or spec is None or
                spec.name != name or type(loader) is not PyiFrozenImporter or
                spec.loader is not loader or
                (spec.submodule_search_locations is not None) != package or
                held.__file__ != spec.origin or
                held.__file__ != str(extraction / (relative + 'c')) or
                loader.get_filename(name) != held.__file__ or
                loader.is_package(name) != package):
            raise RuntimeError('sidecar admission sources: inconsistent frozen module')
        origin = Path(held.__file__).resolve()
        if origin != expected or not origin.is_relative_to(root):
            raise RuntimeError('sidecar admission sources: origin escapes extraction root')
        source = root / relative
        resolved = source.resolve(strict=True)
        if resolved != source or not resolved.is_relative_to(root) or not resolved.is_file():
            raise RuntimeError('sidecar admission sources: invalid source resource')
        with resolved.open('rb'):
            pass
        return str(resolved)

    inspect.getsourcefile = getsourcefile


_install()
del _install
