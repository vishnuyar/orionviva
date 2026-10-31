#!/usr/bin/env python3
"""Build and pin the complete provider-free prepared synthetic vault artifact."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True, help='Fresh private engineering build root')
    parser.add_argument('--output', type=Path, required=True, help='New prepared artifact directory')
    parser.add_argument('--existing-instance', type=Path, help='Reuse an already complete synthetic production build')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root/'product'), str(root/'core'), str(root/'merchant')]
    from viva.sample.instances import build_instance
    from viva.sample.snapshot import export
    if args.existing_instance is None:
        instance, report = build_instance(args.base)
        if report.get('state') != 'ready': raise SystemExit('sample source checks did not complete')
    else:
        instance = args.existing_instance
    digest = export(instance, args.output)
    root = Path(__file__).resolve().parents[1]
    resources = root/'product/viva/sample/resources.py'
    source = resources.read_text()
    updated, count = re.subn(r"SNAPSHOT_MANIFEST_SHA256 = '[^']*'", f"SNAPSHOT_MANIFEST_SHA256 = '{digest}'", source)
    if count != 1: raise SystemExit('sample metadata pin assignment is missing or ambiguous')
    resources.write_text(updated)
    print(f'Prepared sample metadata SHA256: {digest}')


if __name__ == '__main__': main()
