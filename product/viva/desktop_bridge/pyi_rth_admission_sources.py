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
    if not isinstance(mapping, dict) or len(mapping) != 160:
        raise RuntimeError('sidecar admission sources: invalid source map')
    for name, relative in mapping.items():
        if not isinstance(name, str) or not isinstance(relative, str):
            raise RuntimeError('sidecar admission sources: invalid source map')
        ordinary = name.replace('.', '/') + '.py'
        package = name.replace('.', '/') + '/__init__.py'
        if relative not in (ordinary, package) or not all(
                part.isidentifier() for part in name.split('.')):
            raise RuntimeError('sidecar admission sources: invalid source map')

    expected = {'viva.answer_program.selected_balances': 'viva/answer_program/selected_balances.py',
 'viva.tools.account_balances': 'viva/tools/account_balances.py',
 'viva.ledger.ledger': 'viva/ledger/ledger.py', 'viva.vault': 'viva/vault.py', 'viva.ledger.projection.coverage': 'viva/ledger/projection/coverage.py',
 'viva.read_store.documents': 'viva/read_store/documents.py',
 'viva.acquisition': 'viva/acquisition.py',
 'viva.allocation_continuation': 'viva/allocation_continuation.py',
 'viva.allocation_target': 'viva/allocation_target.py',
 'viva.answer_program.admission': 'viva/answer_program/admission.py',
 'viva.answer_program.admission_fixture': 'viva/answer_program/admission_fixture.py',
 'viva.answer_program.bind': 'viva/answer_program/bind.py',
 'viva.answer_program.capabilities': 'viva/answer_program/capabilities.py',
 'viva.answer_program.capability_fixture': 'viva/answer_program/capability_fixture.py',
 'viva.answer_program.compiler': 'viva/answer_program/compiler.py',
 'viva.answer_program.eval': 'viva/answer_program/eval.py',
 'viva.answer_program.evidence': 'viva/answer_program/evidence.py',
 'viva.answer_program.execute': 'viva/answer_program/execute.py',
 'viva.answer_program.instrument_families': 'viva/answer_program/instrument_families.py',
 'viva.answer_program.intents': 'viva/answer_program/intents.py',
 'viva.answer_program.replay': 'viva/answer_program/replay.py',
 'viva.answer_program.runtime': 'viva/answer_program/runtime.py',
 'viva.answer_program.schema': 'viva/answer_program/schema.py',
 'viva.answer_program.validate': 'viva/answer_program/validate.py',
 'viva.demo': 'viva/demo.py',
 'viva.desktop_bridge.conversation_actions': 'viva/desktop_bridge/conversation_actions.py',
 'viva.desktop_bridge.documents_page': 'viva/desktop_bridge/documents_page.py',
 'viva.desktop_bridge.rpc': 'viva/desktop_bridge/rpc.py',
 'viva.desktop_bridge.surface_read': 'viva/desktop_bridge/surface_read.py',
 'viva.desktop_bridge.vault_surface': 'viva/desktop_bridge/vault_surface.py',
 'viva.ingest.apr_context_contracts': 'viva/ingest/apr_context_contracts.py',
 'viva.ingest.apr_context_grounding': 'viva/ingest/apr_context_grounding.py',
 'viva.ingest.apr_context_local': 'viva/ingest/apr_context_local.py',
 'viva.ingest.apr_context_parser': 'viva/ingest/apr_context_parser.py',
 'viva.ingest.brokerage': 'viva/ingest/brokerage.py',
 'viva.ingest.instrument_contracts': 'viva/ingest/instrument_contracts.py',
 'viva.ingest.instrument_effects': 'viva/ingest/instrument_effects.py',
 'viva.ingest.instrument_observations': 'viva/ingest/instrument_observations.py',
 'viva.ingest.instrument_parser': 'viva/ingest/instrument_parser.py',
 'viva.ingest.instrument_projector': 'viva/ingest/instrument_projector.py',
 'viva.ingest.instrument_read': 'viva/ingest/instrument_read.py',
 'viva.ingest.mortgage_known_allocation': 'viva/ingest/mortgage_known_allocation.py',
 'viva.ingest.paystub': 'viva/ingest/paystub.py',
 'viva.ingest.paystub_projector': 'viva/ingest/paystub_projector.py',
 'viva.ingest.pipeline': 'viva/ingest/pipeline.py',
 'viva.ingest.pipeline_models': 'viva/ingest/pipeline_models.py',
 'viva.ingest.reader': 'viva/ingest/reader.py',
 'viva.ingest.registry': 'viva/ingest/registry.py',
 'viva.instrument_claims': 'viva/instrument_claims.py',
 'viva.instrument_conversation': 'viva/instrument_conversation.py',
 'viva.instrument_evidence': 'viva/instrument_evidence.py',
 'viva.instrument_runtime': 'viva/instrument_runtime.py',
 'viva.investment': 'viva/investment/__init__.py',
 'viva.investment.authenticated': 'viva/investment/authenticated.py',
 'viva.investment.authority': 'viva/investment/authority.py',
 'viva.investment.composition': 'viva/investment/composition.py',
 'viva.investment.contracts': 'viva/investment/contracts.py',
 'viva.investment.events': 'viva/investment/events.py',
 'viva.investment.extraction': 'viva/investment/extraction.py',
 'viva.investment.funding': 'viva/investment/funding.py',
 'viva.investment.healing': 'viva/investment/healing.py',
 'viva.investment.identity': 'viva/investment/identity.py',
 'viva.investment.lifecycle': 'viva/investment/lifecycle.py',
 'viva.investment.lineage': 'viva/investment/lineage.py',
 'viva.investment.payroll': 'viva/investment/payroll.py',
 'viva.investment.payroll_extraction': 'viva/investment/payroll_extraction.py',
 'viva.investment.projector': 'viva/investment/projector.py',
 'viva.investment.semantic': 'viva/investment/semantic.py',
 'viva.investment.sql': 'viva/investment/sql.py',
 'viva.investment.tool': 'viva/investment/tool.py',
 'viva.investment.units': 'viva/investment/units.py',
 'viva.ledger.accounting': 'viva/ledger/accounting.py',
 'viva.ledger.apr_context': 'viva/ledger/apr_context.py',
 'viva.ledger.events': 'viva/ledger/events.py',
 'viva.ledger.instruments': 'viva/ledger/instruments.py',
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
 'viva.normalization_context': 'viva/normalization_context.py',
 'viva.quantity': 'viva/quantity.py',
 'viva.read_store.allocation_continuation': 'viva/read_store/allocation_continuation.py',
 'viva.read_store.apr_context_sql': 'viva/read_store/apr_context_sql.py',
 'viva.read_store.document_index': 'viva/read_store/document_index.py',
 'viva.read_store.document_sections': 'viva/read_store/document_sections.py',
 'viva.read_store.documents_page': 'viva/read_store/documents_page.py',
 'viva.read_store.instrument_authority': 'viva/read_store/instrument_authority.py',
 'viva.read_store.instrument_authority_contracts': 'viva/read_store/instrument_authority_contracts.py',
 'viva.read_store.instrument_authority_sql': 'viva/read_store/instrument_authority_sql.py',
 'viva.read_store.instrument_math': 'viva/read_store/instrument_math.py',
 'viva.read_store.instrument_review': 'viva/read_store/instrument_review.py',
 'viva.read_store.instrument_sql': 'viva/read_store/instrument_sql.py',
 'viva.read_store.overview': 'viva/read_store/overview.py',
 'viva.read_store.store': 'viva/read_store/store.py',
 'viva.rebuild': 'viva/rebuild.py',
 'viva.render': 'viva/render.py',
 'viva.retirement_funding': 'viva/retirement_funding/__init__.py',
 'viva.retirement_funding.authority': 'viva/retirement_funding/authority.py',
 'viva.retirement_funding.catalog': 'viva/retirement_funding/catalog.py',
 'viva.retirement_funding.contracts': 'viva/retirement_funding/contracts.py',
 'viva.retirement_funding.lineage': 'viva/retirement_funding/lineage.py',
 'viva.retirement_funding.payroll_v2': 'viva/retirement_funding/payroll_v2.py',
 'viva.retirement_funding.population': 'viva/retirement_funding/population.py',
 'viva.retirement_funding.posting_closure': 'viva/retirement_funding/posting_closure.py',
 'viva.retirement_funding.semantic': 'viva/retirement_funding/semantic.py',
 'viva.retirement_funding.sql': 'viva/retirement_funding/sql.py',
 'viva.retirement_funding.tool': 'viva/retirement_funding/tool.py',
 'viva.sample': 'viva/sample/__init__.py',
 'viva.sample.activation': 'viva/sample/activation.py',
 'viva.sample.curation': 'viva/sample/curation.py',
 'viva.sample.instances': 'viva/sample/instances.py',
 'viva.sample.worker': 'viva/sample/worker.py',
 'viva.extraction_responses': 'viva/extraction_responses.py',
 'viva.desktop_bridge.bulk_documents': 'viva/desktop_bridge/bulk_documents.py',
 'viva.sample.resources': 'viva/sample/resources.py',
 'viva.session': 'viva/session.py',
 'viva.speak': 'viva/speak.py',
 'viva.surface.capabilities': 'viva/surface/capabilities.py',
 'viva.surface.conversation': 'viva/surface/conversation.py',
 'viva.surface.documents_page': 'viva/surface/documents_page.py',
 'viva.surface.numerical_receipts': 'viva/surface/numerical_receipts.py',
 'viva.surface.operations': 'viva/surface/operations.py',
 'viva.surface.overview': 'viva/surface/overview.py',
 'viva.tools': 'viva/tools/__init__.py',
 'viva.tools.boundary': 'viva/tools/boundary.py',
 'viva.tools.compute': 'viva/tools/compute.py',
 'viva.tools.envelope': 'viva/tools/envelope.py',
 'viva.tools.instruments': 'viva/tools/instruments.py',
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
 'vivacore.verify.normalize': 'vivacore/verify/normalize.py'}
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
