"""Raw admission sources remain addressable in the frozen sidecar."""
import ast
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).parents[2]
SPEC = ROOT / 'product/viva/desktop_bridge/viva-desktop-bridge.spec'
HOOK = SPEC.with_name('pyi_rth_admission_sources.py')
BUILTIN = Path(importlib.util.find_spec('PyInstaller').origin).parent / 'hooks/rthooks/pyi_rth_inspect.py'


def source_map():
    tree = ast.parse(SPEC.read_text())
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and
                      any(isinstance(t, ast.Name) and t.id == 'ADMISSION_SOURCES' for t in n.targets))
    sources = eval(compile(ast.Expression(assignment.value), str(SPEC), 'eval'),
                   {'PRODUCT_ROOT': ROOT / 'product', 'REPOSITORY_ROOT': ROOT})
    result = {}
    for source, destination in sources:
        relative = f'{destination}/{source.name}'
        name = relative[:-3].replace('/', '.')
        if name.endswith('.__init__'):
            name = name[:-9]
        result[name] = relative
    return result


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    mapping = source_map()
    (tmp_path / 'admission-source-map.json').write_text(json.dumps(mapping))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(inspect, 'getsourcefile', inspect.getsourcefile)
    import PyInstaller
    loader_root = Path(PyInstaller.__file__).parent / 'loader'

    def load_bootstrap(name):
        spec = importlib.util.spec_from_file_location(name, loader_root / (name + '.py'))
        held = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, held)
        spec.loader.exec_module(held)
        return held

    archive_module = load_bootstrap('pyimod01_archive')
    loader_module = load_bootstrap('pyimod02_importers')
    loader_module.pyz_archive = SimpleNamespace(toc={
        name: (archive_module.PYZ_ITEM_PKG if relative.endswith('/__init__.py')
               else archive_module.PYZ_ITEM_MODULE, 0, 0)
        for name, relative in mapping.items()})
    runpy.run_path(str(BUILTIN))

    def module(name):
        path = tmp_path / mapping[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes('# café\r\nvalue = 1\r\n'.encode())
        held = ModuleType(name)
        loader_path = path.parent.parent if path.name == "__init__.py" else path.parent
        loader = loader_module.PyiFrozenImporter(str(loader_path))
        held.__file__ = str(path) + 'c'
        held.__loader__ = loader
        held.__spec__ = loader.find_spec(name)
        assert held.__spec__.origin == held.__file__
        assert loader.is_package(name) == (path.name == '__init__.py')
        monkeypatch.setitem(sys.modules, name, held)
        return held, path

    return module, mapping


def install():
    if HOOK.exists():
        runpy.run_path(str(HOOK))


def test_all_frozen_admission_sources_preserve_raw_bytes(frozen):
    module, mapping = frozen
    install()
    assert mapping == source_map()
    for name in mapping:
        held, source = module(name)
        metadata = held.__file__, held.__loader__, held.__spec__
        actual = Path(inspect.getsourcefile(held)).read_bytes()
        assert hashlib.sha256(actual).digest() == hashlib.sha256(source.read_bytes()).digest()
        assert actual != source.read_text().encode()
        assert metadata == (held.__file__, held.__loader__, held.__spec__)


def test_builtin_and_early_custom_hook_reproduce_missing_pyc(frozen):
    module, _ = frozen
    held, _ = module('viva.answer_program.intents')
    install()
    runpy.run_path(str(BUILTIN))
    with pytest.raises(FileNotFoundError):
        Path(inspect.getsourcefile(held)).read_bytes()


@pytest.mark.parametrize('defect', ['missing', 'identity', 'name', 'loader', 'origin',
                                    'package', 'loader_filename', 'loader_package', 'loader_subclass',
                                    'escape', 'prefix', 'symlink'])
def test_invalid_frozen_resources_fail_closed(frozen, tmp_path, monkeypatch, defect):
    module, _ = frozen
    held, source = module('viva.answer_program.intents')
    install()
    if defect == 'missing':
        source.unlink()
    elif defect == 'identity':
        monkeypatch.setitem(sys.modules, held.__name__, ModuleType(held.__name__))
    elif defect == 'name':
        held.__spec__.name = 'viva.other'
    elif defect == 'loader':
        held.__spec__.loader = object()
    elif defect == 'origin':
        held.__spec__.origin = str(source)
    elif defect == 'package':
        held.__spec__.submodule_search_locations = []
    elif defect == 'loader_filename':
        held.__loader__.get_filename = lambda name: str(source)
    elif defect == 'loader_package':
        held.__loader__.is_package = lambda name: True
    elif defect == 'loader_subclass':
        class OtherImporter(type(held.__loader__)):
            pass
        held.__loader__ = OtherImporter(held.__loader__._path)
        held.__spec__.loader = held.__loader__
    elif defect in ('escape', 'prefix'):
        held.__file__ = str(tmp_path.parent / (tmp_path.name + '-sibling') / 'intents.pyc')
        held.__spec__.origin = held.__file__
    elif defect == 'symlink':
        outside = tmp_path.parent / 'outside.py'
        outside.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(outside)
    with pytest.raises((RuntimeError, FileNotFoundError)):
        inspect.getsourcefile(held)


def test_changed_resource_bytes_remain_changed(frozen):
    module, _ = frozen
    held, source = module('viva.answer_program.intents')
    install()
    before = hashlib.sha256(Path(inspect.getsourcefile(held)).read_bytes()).digest()
    source.write_bytes(source.read_bytes() + b'\n')
    assert hashlib.sha256(Path(inspect.getsourcefile(held)).read_bytes()).digest() != before


def test_delegation_preserves_returns_errors_and_import_inventory(frozen, monkeypatch, tmp_path):
    normal = ModuleType('synthetic_source')
    normal.__file__ = str(tmp_path / 'normal.py')
    Path(normal.__file__).write_text('value = 1\n')
    sentinel = object()
    failure = TypeError('synthetic inspection failure')
    calls = []

    def original(held):
        calls.append(held)
        if held is sentinel:
            raise failure
        return held.__file__ if held is normal else None

    monkeypatch.setattr(inspect, 'getsourcefile', original)
    inventory = set(sys.modules)
    install()
    assert not any(name.startswith(('viva.', 'vivacore.')) for name in set(sys.modules) - inventory)
    assert inspect.getsourcefile(normal) == normal.__file__
    assert inspect.getsourcefile(lambda: None) is None
    with pytest.raises(TypeError) as caught:
        inspect.getsourcefile(sentinel)
    assert caught.value is failure
    assert calls[0] is normal and calls[2] is sentinel


def order_function():
    tree = ast.parse(SPEC.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and
                    n.name == '_order_inspection_hooks')
    namespace = {'Path': Path}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SPEC), 'exec'), namespace)
    return namespace[function.name]


def test_order_preserves_all_other_entries_and_cached_results(tmp_path):
    order = order_function()
    custom, builtin, program = [tmp_path / x for x in ('custom.py', 'builtin.py', 'main.py')]
    scripts = [('pyi_rth_admission_sources', str(custom), 'PYSOURCE'),
               ('unrelated', str(tmp_path / 'other.py'), 'PYSOURCE'),
               ('pyi_rth_inspect', str(builtin), 'PYSOURCE'),
               ('__main__', str(program), 'PYSOURCE')]
    result = order(scripts, custom, builtin, program)
    assert result == [scripts[1], scripts[2], scripts[0], scripts[3]]
    assert order(result, custom, builtin, program) == result


@pytest.mark.parametrize('target', [0, 1])
@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'type', 'name', 'path'])
def test_order_refuses_inconsistent_hooks(tmp_path, target, defect):
    custom, builtin, program = [tmp_path / x for x in ('custom.py', 'builtin.py', 'main.py')]
    scripts = [('pyi_rth_admission_sources', str(custom), 'PYSOURCE'),
               ('pyi_rth_inspect', str(builtin), 'PYSOURCE'),
               ('__main__', str(program), 'PYSOURCE')]
    if defect == 'missing':
        scripts.pop(target)
    elif defect == 'duplicate':
        scripts.append(scripts[target])
    else:
        held = list(scripts[target])
        held[{'type': 2, 'name': 0, 'path': 1}[defect]] = 'wrong'
        scripts[target] = tuple(held)
    with pytest.raises(SystemExit):
        order_function()(scripts, custom, builtin, program)


def test_real_admission_byte_reader_and_compiler_gate(frozen, monkeypatch):
    import importlib
    from types import SimpleNamespace
    from vivacore import promptstore, versions
    from vivacore.models import ModelSpec
    from viva import speak
    from viva.answer_program import release, AnswerResourcePolicy
    from viva.answer_program.intents import SemanticFamilyRegistry
    from viva.answer_program.compiler import COMPILER_VERSION
    from viva.tools.registry import PACKAGE, PROMPTS
    import viva.answer_program as facade

    module, mapping = frozen
    with monkeypatch.context() as source_host:
        source_host.setattr(sys, 'frozen', False)
        baseline = SemanticFamilyRegistry._admitted_implementation_digests()
    source_bytes = {name: (ROOT / 'product/viva/surface/overview.py').read_bytes()
                    if name == 'viva.surface.overview'
                    else Path(importlib.import_module(name).__file__).read_bytes()
                    for name in mapping}
    install()
    paths = {}
    monkeypatch.delitem(sys.modules, 'viva.surface.overview', raising=False)
    for name in mapping:
        if name == 'viva.surface.overview':
            path = Path(sys._MEIPASS) / mapping[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source_bytes[name])
            paths[name] = path
            continue
        actual = importlib.import_module(name)
        synthetic, path = module(name)
        path.write_bytes(source_bytes[name])
        paths[name] = path
        monkeypatch.setitem(sys.modules, name, actual)
        for field in ('__file__', '__loader__', '__spec__'):
            monkeypatch.setattr(actual, field, getattr(synthetic, field))
    assert SemanticFamilyRegistry._admitted_implementation_digests() == baseline
    assert 'viva.surface.overview' not in sys.modules

    def deterministic():
        return json.dumps(SemanticFamilyRegistry._admitted_implementation_digests(), sort_keys=True)

    expected = deterministic()
    monkeypatch.setattr(release, 'current_contract_digests', lambda *args: {'deterministic_builders': deterministic()})
    policy = AnswerResourcePolicy()
    manifest = SimpleNamespace(digest='synthetic-manifest', manifest_version='synthetic-version')
    spec = ModelSpec(name='synthetic', adapter='synthetic', model='synthetic', base_url='synthetic')
    profile = SimpleNamespace(
        profile_version=release.ADMISSION_PROFILE_VERSION,
        capability_manifest_digest=manifest.digest, capability_manifest_version=manifest.manifest_version,
        prompt_version=COMPILER_VERSION, prompt_digest=promptstore.digest(PROMPTS, COMPILER_VERSION),
        program_schema_version=release.ANSWER_PROGRAM_VERSION,
        program_schema_digest=versions.fingerprint(versions.path_of(PACKAGE, release.ANSWER_PROGRAM_VERSION)),
        resource_policy_digest=facade.resource_policy_digest(policy),
        financial_query_schema_digest='', semantic_request_schema_digest='', semantic_catalog_digest='',
        deterministic_builder_digest=expected, keyed_corpus_digest='', adversarial_corpus_digest='',
        persona_pack_digest='', admission_fixture_digest='', oracle_set_digest='',
        admission_report_digest=facade.admission_report_digest({}), provider='synthetic',
        requested_model='synthetic', endpoint=spec.endpoint_identity(), modality='native-structured',
        locale_family='en', resolved_model='synthetic')
    monkeypatch.setattr(facade, 'validate_admission_report', lambda *args: ())
    monkeypatch.setattr(release, 'validate_admission_report', lambda *args: ())
    monkeypatch.setattr('vivacore.models.adapter_for', lambda spec: SimpleNamespace(converse=lambda: pytest.fail('provider call')))
    created = []
    monkeypatch.setattr(speak, 'AnswerProgramCompiler', lambda *args, **kwargs: created.append(True))
    factory = speak.compiler_factory(spec,
                                     profile=profile, report={}, locale='en-US')
    factory(None, manifest, policy)
    assert created == [True]
    created.clear()
    overview_source = paths['viva.surface.overview']
    overview_source.write_bytes(source_bytes['viva.surface.overview'] + b'\n')
    with pytest.raises(ValueError, match='deterministic_builders_digest_mismatch'):
        factory(None, manifest, policy)
    assert not created
    overview_source.write_bytes(source_bytes['viva.surface.overview'])
    assert 'viva.surface.overview' not in sys.modules
    for name in ('vivacore.models.spec', 'viva.speak'):
        source = paths[name]
        source.write_bytes(source_bytes[name] + b'\n')
        with pytest.raises(ValueError, match='deterministic_builders_digest_mismatch'):
            factory(None, manifest, policy)
        assert not created
        source.write_bytes(source_bytes[name])
    source = paths['viva.answer_program.intents']
    source.write_bytes(source.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='deterministic_builders_digest_mismatch'):
        factory(None, manifest, policy)
    assert not created
    source.unlink()
    with pytest.raises(FileNotFoundError):
        factory(None, manifest, policy)
    assert not created
    runpy.run_path(str(BUILTIN))
    with pytest.raises(FileNotFoundError):
        factory(None, manifest, policy)
    assert not created


@pytest.mark.parametrize('defect', ['manifest_missing', 'manifest_mapping', 'manifest_entry_missing', 'surface_entry_missing', 'replacement_entry', 'host', 'root'])
def test_startup_rejects_invalid_context(frozen, monkeypatch, defect):
    manifest = Path(sys._MEIPASS) / 'admission-source-map.json'
    if defect == 'manifest_missing':
        manifest.unlink()
    elif defect == 'manifest_mapping':
        mapping = json.loads(manifest.read_bytes())
        mapping['viva.answer_program.intents'] = '../outside.py'
        manifest.write_text(json.dumps(mapping))
    elif defect == 'manifest_entry_missing':
        mapping = json.loads(manifest.read_bytes())
        mapping.pop('viva.ledger.networth')
        manifest.write_text(json.dumps(mapping))
    elif defect == 'surface_entry_missing':
        mapping = json.loads(manifest.read_bytes())
        mapping.pop('viva.surface.overview')
        manifest.write_text(json.dumps(mapping))
    elif defect == 'replacement_entry':
        mapping = json.loads(manifest.read_bytes())
        mapping.pop('vivacore.models.spec')
        mapping['viva.synthetic'] = 'viva/synthetic.py'
        manifest.write_text(json.dumps(mapping))
    elif defect == 'host':
        monkeypatch.setattr(sys, 'frozen', False)
    elif defect == 'root':
        monkeypatch.setattr(sys, '_MEIPASS', 'relative-root')
    with pytest.raises((RuntimeError, FileNotFoundError)):
        install()


def test_packaging_inventory_matches_every_admitted_module(monkeypatch):
    from viva.answer_program.intents import SemanticFamilyRegistry
    paths = {}
    sourcefile = inspect.getsourcefile
    def record(module):
        path = Path(sourcefile(module))
        paths[module.__name__] = path
        return str(path)
    monkeypatch.setattr(inspect, 'getsourcefile', record)
    SemanticFamilyRegistry._admitted_implementation_digests()
    assert 'viva.surface.overview' not in paths
    paths['viva.surface.overview'] = ROOT / 'product/viva/surface/overview.py'
    # Exact additional source-only closure: these tiers must be hashed without
    # executing bridge/surface code in the financial engine.
    for relative in ('instrument_claims', 'instrument_evidence', 'instrument_runtime', 'instrument_conversation', 'allocation_target', 'allocation_continuation', 'answer_program/instrument_families', 'read_store/instrument_authority', 'read_store/instrument_authority_contracts', 'read_store/instrument_authority_sql', 'read_store/instrument_math', 'read_store/apr_context_sql', 'ledger/apr_context', 'ledger/instruments', 'ingest/instrument_contracts', 'ingest/instrument_parser', 'ingest/instrument_observations', 'ingest/instrument_effects', 'ingest/instrument_projector', 'ingest/instrument_read', 'ingest/apr_context_contracts', 'ingest/apr_context_parser', 'ingest/apr_context_grounding', 'ingest/apr_context_local', 'ingest/pipeline', 'ingest/reader', 'ingest/registry', 'ingest/pipeline_models', 'rebuild', 'tools/instruments', 'session', 'surface/conversation', 'surface/numerical_receipts', 'desktop_bridge/conversation_actions', 'desktop_bridge/vault_surface', 'read_store/store', 'read_store/instrument_sql', 'read_store/allocation_continuation', 'read_store/document_index', 'read_store/document_sections', 'read_store/documents_page', 'read_store/instrument_review', 'desktop_bridge/documents_page', 'desktop_bridge/surface_read', 'desktop_bridge/rpc', 'surface/capabilities', 'surface/operations'):
        paths['viva.'+relative.replace('/','.')] = ROOT / ('product/viva/'+relative+'.py')
    paths['viva.surface.documents_page']=ROOT/'product/viva/surface/documents_page.py'
    paths['viva.vault']=ROOT/'product/viva/vault.py'
    paths.update({name: ROOT / ("product/"+relative)
                  for name,relative in (('viva.investment', 'viva/investment/__init__.py'), ('viva.investment.authenticated', 'viva/investment/authenticated.py'), ('viva.investment.authority', 'viva/investment/authority.py'), ('viva.investment.composition', 'viva/investment/composition.py'), ('viva.investment.contracts', 'viva/investment/contracts.py'), ('viva.investment.events', 'viva/investment/events.py'), ('viva.investment.extraction', 'viva/investment/extraction.py'), ('viva.investment.funding', 'viva/investment/funding.py'), ('viva.investment.healing', 'viva/investment/healing.py'), ('viva.investment.identity', 'viva/investment/identity.py'), ('viva.investment.lifecycle', 'viva/investment/lifecycle.py'), ('viva.investment.lineage', 'viva/investment/lineage.py'), ('viva.investment.payroll', 'viva/investment/payroll.py'), ('viva.investment.payroll_extraction', 'viva/investment/payroll_extraction.py'), ('viva.investment.projector', 'viva/investment/projector.py'), ('viva.investment.semantic', 'viva/investment/semantic.py'), ('viva.investment.sql', 'viva/investment/sql.py'), ('viva.investment.tool', 'viva/investment/tool.py'), ('viva.investment.units', 'viva/investment/units.py'), ('viva.retirement_funding', 'viva/retirement_funding/__init__.py'), ('viva.retirement_funding.authority', 'viva/retirement_funding/authority.py'), ('viva.retirement_funding.catalog', 'viva/retirement_funding/catalog.py'), ('viva.retirement_funding.contracts', 'viva/retirement_funding/contracts.py'), ('viva.retirement_funding.lineage', 'viva/retirement_funding/lineage.py'), ('viva.retirement_funding.payroll_v2', 'viva/retirement_funding/payroll_v2.py'), ('viva.retirement_funding.population', 'viva/retirement_funding/population.py'), ('viva.retirement_funding.posting_closure', 'viva/retirement_funding/posting_closure.py'), ('viva.retirement_funding.semantic', 'viva/retirement_funding/semantic.py'), ('viva.retirement_funding.sql', 'viva/retirement_funding/sql.py'), ('viva.retirement_funding.tool', 'viva/retirement_funding/tool.py'), ('viva.normalization_context', 'viva/normalization_context.py'), ('viva.ingest.mortgage_known_allocation', 'viva/ingest/mortgage_known_allocation.py'), ('viva.ingest.paystub', 'viva/ingest/paystub.py'), ('viva.ingest.paystub_projector', 'viva/ingest/paystub_projector.py'), ('viva.acquisition', 'viva/acquisition.py'), ('viva.sample', 'viva/sample/__init__.py'), ('viva.sample.curation', 'viva/sample/curation.py'), ('viva.sample.resources', 'viva/sample/resources.py'), ('viva.sample.instances', 'viva/sample/instances.py'), ('viva.sample.activation', 'viva/sample/activation.py'), ('viva.demo', 'viva/demo.py'))})
    paths['viva.sample.worker']=ROOT/'product/viva/sample/worker.py'
    paths['viva.desktop_bridge.bulk_documents']=ROOT/'product/viva/desktop_bridge/bulk_documents.py'
    paths['viva.extraction_responses']=ROOT/'product/viva/extraction_responses.py'
    paths['viva.ledger.projection.coverage']=ROOT/'product/viva/ledger/projection/coverage.py'
    paths['viva.read_store.documents']=ROOT/'product/viva/read_store/documents.py'
    paths.update({name: ROOT / ("product/" + relative)
                  for name, relative in _SELECTED_REPORT_RESOURCES.values()})
    mapping = source_map()
    assert set(mapping) == set(paths)
    for name, relative in mapping.items():
        assert paths[name].as_posix().endswith('/' + relative)


@pytest.mark.parametrize('defect', ['missing', 'symlink', 'directory_symlink', 'mapping_missing',
                                    'mapping_wrong_path', 'mapping_wrong_identity', 'wrong_root',
                                    'manifest_symlink'])
def test_source_only_disclosure_resources_fail_closed(frozen, monkeypatch, tmp_path, defect):
    from viva.answer_program.intents import SemanticFamilyRegistry
    module, mapping = frozen
    module('viva.answer_program.intents')
    resource = Path(sys._MEIPASS) / mapping['viva.surface.overview']
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_bytes(b'# fabricated disclosure source\r\n')
    install()
    assert SemanticFamilyRegistry._admitted_source_only_paths()['financial_surface_overview'] == resource
    manifest = Path(sys._MEIPASS) / 'admission-source-map.json'
    if defect == 'missing':
        resource.unlink()
    elif defect == 'symlink':
        other = tmp_path / 'other.py'
        other.write_bytes(resource.read_bytes())
        resource.unlink()
        resource.symlink_to(other)
    elif defect == 'directory_symlink':
        original = resource.parent
        moved = tmp_path / 'relocated-surface'
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
    elif defect == 'mapping_missing':
        current = json.loads(manifest.read_bytes())
        current.pop('viva.surface.overview')
        manifest.write_text(json.dumps(current))
    elif defect == 'mapping_wrong_path':
        current = json.loads(manifest.read_bytes())
        current['viva.surface.overview'] = 'viva/surface/other.py'
        manifest.write_text(json.dumps(current))
    elif defect == 'mapping_wrong_identity':
        current = json.loads(manifest.read_bytes())
        current.pop('viva.surface.overview')
        current['viva.surface.invalid-name'] = 'viva/surface/invalid-name.py'
        manifest.write_text(json.dumps(current))
    elif defect == 'wrong_root':
        monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'elsewhere'))
    elif defect == 'manifest_symlink':
        other = tmp_path / 'other-map.json'
        other.write_bytes(manifest.read_bytes())
        manifest.unlink()
        manifest.symlink_to(other)
    with pytest.raises((RuntimeError, FileNotFoundError)):
        SemanticFamilyRegistry._admitted_source_only_paths()


def test_admission_authenticates_overview_without_importing_the_surface():
    import os
    import subprocess
    code = """
import sys
class NoSurface:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'viva.surface' or fullname.startswith('viva.surface.'):
            raise AssertionError('engine attempted to load surface code')
sys.meta_path.insert(0, NoSurface())
from viva.answer_program.intents import SemanticFamilyRegistry
values = SemanticFamilyRegistry._admitted_implementation_digests()
assert 'financial_surface_overview' in values
assert not any(name == 'viva.surface' or name.startswith('viva.surface.') for name in sys.modules)
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': os.pathsep.join(sys.path)}, timeout=30)
    assert result.returncode == 0, result.stderr


def test_source_only_resource_uses_the_existing_hooks_canonical_extraction_root(frozen, monkeypatch, tmp_path):
    from viva.answer_program.intents import SemanticFamilyRegistry
    module, mapping = frozen
    name = 'viva.answer_program.intents'
    held, _anchor = module(name)
    resource = Path(sys._MEIPASS) / mapping['viva.surface.overview']
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_bytes(b'# fabricated disclosure source\r\n')
    alias = tmp_path / 'extraction-alias'
    alias.symlink_to(Path(sys._MEIPASS), target_is_directory=True)
    monkeypatch.setattr(sys, '_MEIPASS', str(alias))
    held.__spec__ = held.__loader__.find_spec(name)
    held.__file__ = held.__spec__.origin
    assert held.__file__ == str(alias / (mapping[name] + 'c'))
    assert held.__loader__.get_filename(name) == held.__file__
    install()
    assert SemanticFamilyRegistry._admitted_source_only_paths() == {
        'financial_surface_overview': resource}


_METADATA_RESOURCES = {
    'instrument_dependency:viva.ledger.projection.coverage':
        ('viva.ledger.projection.coverage', 'viva/ledger/projection/coverage.py'),
    'instrument_dependency:viva.read_store.documents':
        ('viva.read_store.documents', 'viva/read_store/documents.py'),
}


def test_metadata_resources_independently_change_actual_candidate_identity(monkeypatch,tmp_path):
    from viva.answer_program.intents import SemanticFamilyRegistry
    original=SemanticFamilyRegistry._admitted_source_only_paths
    baseline=SemanticFamilyRegistry._admitted_implementation_digests()
    assert len(baseline)==160
    for key,(module,relative) in _METADATA_RESOURCES.items():
        assert baseline[key]==hashlib.sha256((ROOT/'product'/relative).read_bytes()).hexdigest()[:16]
        changed_source=tmp_path/(module.replace('.','_')+'.py')
        changed_source.write_bytes((ROOT/'product'/relative).read_bytes()+b'\n# synthetic dependency mutation\n')
        def replaced(resources=None,*,chosen=key,path=changed_source):
            paths=original(resources)
            if resources is not None:
                assert chosen in paths
                paths={**paths,chosen:path}
            return paths
        monkeypatch.setattr(SemanticFamilyRegistry,'_admitted_source_only_paths',staticmethod(replaced))
        changed=SemanticFamilyRegistry._admitted_implementation_digests()
        assert set(changed)==set(baseline)
        assert changed[key]==hashlib.sha256(changed_source.read_bytes()).hexdigest()[:16]
        assert changed[key]!=baseline[key]
        assert all(changed[name]==value for name,value in baseline.items() if name!=key)


def test_metadata_packaged_map_roundtrip_has_exact_two_real_additions():
    mapping=source_map()
    assert len(mapping)==160
    assert len(set(mapping.values()))==160
    for module,relative in _METADATA_RESOURCES.values():
        assert mapping[module]==relative
        assert (ROOT/'product'/relative).is_file()
    assert json.loads(json.dumps(mapping))==mapping


@pytest.mark.parametrize('guard',['hook','source_only'])
@pytest.mark.parametrize('size',[153,154,155,156,157,158,159,161])
def test_metadata_strict_map_rejects_old_missing_and_extra_cardinalities(frozen,monkeypatch,guard,size):
    from viva.answer_program.intents import SemanticFamilyRegistry
    module,mapping=frozen
    module('viva.answer_program.intents')
    for name,relative in _METADATA_RESOURCES.values():
        module(name)
    install()
    assert len(mapping)==160
    assert set(SemanticFamilyRegistry._admitted_source_only_paths(_METADATA_RESOURCES))==set(_METADATA_RESOURCES)
    changed=dict(mapping)
    while len(changed)>size:changed.pop(next(reversed(changed)))
    while len(changed)<size:
        name='viva.public_extra_'+str(len(changed));changed[name]=name.replace('.','/')+'.py'
    (Path(sys._MEIPASS)/'admission-source-map.json').write_text(json.dumps(changed))
    with pytest.raises(RuntimeError,match='source map'):
        if guard=='hook':install()
        else:SemanticFamilyRegistry._admitted_source_only_paths(_METADATA_RESOURCES)


@pytest.mark.parametrize('guard',['hook','source_only'])
@pytest.mark.parametrize('target',list(_METADATA_RESOURCES))
@pytest.mark.parametrize('defect',['remove','substitute','duplicate_path'])
def test_each_metadata_resource_identity_is_required(frozen,guard,target,defect):
    from viva.answer_program.intents import SemanticFamilyRegistry
    module,mapping=frozen;module('viva.answer_program.intents')
    for name,relative in _METADATA_RESOURCES.values():module(name)
    install()
    changed=dict(mapping);name,relative=_METADATA_RESOURCES[target]
    if defect=='remove':changed.pop(name)
    elif defect=='substitute':
        changed.pop(name);changed['viva.public_replacement']='viva/public_replacement.py'
    else:changed['viva.answer_program.compiler']=relative
    (Path(sys._MEIPASS)/'admission-source-map.json').write_text(json.dumps(changed))
    with pytest.raises(RuntimeError,match='source map|canonical resource mapping'):
        if guard=='hook':install()
        else:SemanticFamilyRegistry._admitted_source_only_paths(_METADATA_RESOURCES)


@pytest.mark.parametrize('target',list(_METADATA_RESOURCES))
def test_spec_rejects_duplicate_metadata_admission_source(target):
    tree=ast.parse(SPEC.read_text())
    loop=next(node for node in tree.body if isinstance(node,ast.For)
              and any(isinstance(child,ast.Constant) and child.value=='sidecar build: duplicate admission module'
                      for child in ast.walk(node)))
    sources=[(ROOT/'product'/relative,str(Path(relative).parent))
             for module,relative in _METADATA_RESOURCES.values()]
    module,relative=_METADATA_RESOURCES[target]
    sources.append((ROOT/'product'/relative,str(Path(relative).parent)))
    namespace={'ADMISSION_SOURCES':sources,'source_map':{}}
    with pytest.raises(SystemExit,match='duplicate admission module'):
        exec(compile(ast.Module(body=[loop],type_ignores=[]),str(SPEC),'exec'),namespace)



def test_vault_is_exact_additive_source_resource_and_mutation_changes_only_its_digest(monkeypatch,tmp_path):
    from viva.answer_program.intents import SemanticFamilyRegistry
    key='foundation_dependency:viva.vault'
    baseline=SemanticFamilyRegistry._admitted_implementation_digests()
    assert len(baseline)==160 and key in baseline
    mapping=source_map()
    assert len(mapping)==160 and mapping['viva.vault']=='viva/vault.py'
    assert len({k:v for k,v in mapping.items() if k!='viva.vault'})==159
    assert len({k:v for k,v in baseline.items() if k!=key})==159
    source=ROOT/'product/viva/vault.py'
    assert baseline[key]==hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    original=SemanticFamilyRegistry._admitted_source_only_paths
    changed=tmp_path/'vault.py';changed.write_bytes(source.read_bytes()+b'\n# public source-byte mutation\n')
    def paths(resources=None):
        result=original(resources)
        return {**result,key:changed} if resources is not None and key in result else result
    monkeypatch.setattr(SemanticFamilyRegistry,'_admitted_source_only_paths',staticmethod(paths))
    altered=SemanticFamilyRegistry._admitted_implementation_digests()
    assert altered[key]!=baseline[key]
    assert all(altered[k]==v for k,v in baseline.items() if k!=key)
    monkeypatch.setattr(SemanticFamilyRegistry,'_admitted_source_only_paths',staticmethod(original))
    assert SemanticFamilyRegistry._admitted_implementation_digests()==baseline


@pytest.mark.parametrize('guard',['hook','source_only'])
@pytest.mark.parametrize('defect',['remove','substitute','duplicate_path','misname'])
def test_vault_binding_is_required_in_hook_and_source_resource(frozen,guard,defect):
    from viva.answer_program.intents import SemanticFamilyRegistry
    module,mapping=frozen
    module('viva.answer_program.intents');module('viva.vault');install()
    changed=dict(mapping)
    if defect=='remove':changed.pop('viva.vault')
    elif defect=='substitute':changed['viva.vault']='viva/other.py'
    elif defect=='misname':changed['viva.other']=changed.pop('viva.vault')
    else:changed['viva.vault']=changed['viva.acquisition']
    (Path(sys._MEIPASS)/'admission-source-map.json').write_text(json.dumps(changed))
    with pytest.raises(RuntimeError):
        if guard=='hook':install()
        else:SemanticFamilyRegistry._admitted_source_only_paths({'foundation_dependency:viva.vault':('viva.vault','viva/vault.py')})


_SELECTED_REPORT_RESOURCES = {
    'selected_balance_dependency:viva.answer_program.selected_balances':
        ('viva.answer_program.selected_balances', 'viva/answer_program/selected_balances.py'),
    'selected_balance_dependency:viva.tools.account_balances':
        ('viva.tools.account_balances', 'viva/tools/account_balances.py'),
    'selected_balance_dependency:viva.ledger.ledger':
        ('viva.ledger.ledger', 'viva/ledger/ledger.py'),
}


def test_selected_report_and_exact_owner_sources_are_in_the_actual_frozen_admission_map(frozen):
    from viva.answer_program.intents import SemanticFamilyRegistry
    module, mapping = frozen
    module('viva.answer_program.intents')
    for name, relative in _SELECTED_REPORT_RESOURCES.values():
        _, path = module(name)
        path.write_bytes((ROOT / 'product' / relative).read_bytes())
    install()
    paths = SemanticFamilyRegistry._admitted_source_only_paths(_SELECTED_REPORT_RESOURCES)
    assert set(paths) == set(_SELECTED_REPORT_RESOURCES)
    for key, (name, relative) in _SELECTED_REPORT_RESOURCES.items():
        assert mapping[name] == relative
        assert paths[key].read_bytes() == (ROOT / 'product' / relative).read_bytes()
