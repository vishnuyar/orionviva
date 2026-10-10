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
    if not isinstance(mapping, dict) or len(mapping) != 60:
        raise RuntimeError('sidecar admission sources: invalid source map')
    for name, relative in mapping.items():
        if not isinstance(name, str) or not isinstance(relative, str):
            raise RuntimeError('sidecar admission sources: invalid source map')
        ordinary = name.replace('.', '/') + '.py'
        package = name.replace('.', '/') + '/__init__.py'
        if relative not in (ordinary, package) or not all(
                part.isidentifier() for part in name.split('.')):
            raise RuntimeError('sidecar admission sources: invalid source map')

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
