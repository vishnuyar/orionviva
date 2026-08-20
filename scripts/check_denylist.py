#!/usr/bin/env python3
"""Refuse a tree that carries a denylisted name, from CI rather than from a laptop.

The local pre-commit hook has held this line until now, and a local hook is
opt-in (`core.hooksPath` must be set), skippable (`--no-verify`, which the
hook's own message recommends), and absent entirely from a fresh clone. It was
bypassed, and real merchant and servicer names reached published history.

The denylist itself cannot be committed — it is a list of the very strings that
must not appear — so it arrives as a secret and is written to a file the job
deletes. Everything here is built so the names never reach a public build log:
a match is reported as a pattern *index*, a path and a line number, never as
the matched text and never as the pattern. Read the report next to your local
`.denylist` to learn which name it was.

Usage:
    check_denylist.py --patterns <file>   [--paths a b c]

Exit 0 when the scanned files are clean, 1 when any pattern matches, and 2 when
the run could not be trusted — no pattern file, or an empty one. A scanner that
silently finds nothing because it was given nothing to look for is worse than no
scanner, because the green tick is read as an answer.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

def repo_root() -> pathlib.Path:
    """The tree being scanned: the git root of the working directory.

    Taken from the cwd rather than from this file's location, so the scanner can
    be pointed at a clone or an export and actually scan *that* tree. Resolving
    it from `__file__` would make it silently rescan its own checkout and report
    clean about a tree it never opened."""
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=True).stdout
    return pathlib.Path(root.strip())

# Files whose contents are not prose and would only produce noise. A lockfile
# or a minified bundle cannot carry a merchant name meaningfully, and a hash
# collides with short patterns by chance.
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".pdf",
                  ".woff", ".woff2", ".ttf", ".zip", ".gz", ".tar"}
_SKIP_NAMES = {"package-lock.json", "pnpm-lock.yaml", "Cargo.lock"}


def patterns_from(path: pathlib.Path) -> list[str]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]


def tracked_files(repo: pathlib.Path) -> list[pathlib.Path]:
    listed = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                            capture_output=True, text=True, check=True).stdout
    return [repo / name for name in listed.split("\0") if name]


def scan(paths: list[pathlib.Path], patterns: list[str],
         repo: pathlib.Path) -> list[str]:
    """Every hit, as `path:line  #index`. Never the matched text."""
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    hits: list[str] = []
    for path in paths:
        if path.suffix.lower() in _SKIP_SUFFIXES or path.name in _SKIP_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue          # not text, so not prose carrying a name
        for line_no, line in enumerate(text.splitlines(), 1):
            for index, rx in enumerate(compiled, 1):
                if rx.search(line):
                    rel = os.path.relpath(path, repo)
                    hits.append(f"{rel}:{line_no}  denylist #{index}")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patterns", type=pathlib.Path, required=True,
                        help="file of patterns, one per line, # for comments")
    parser.add_argument("--paths", nargs="*", type=pathlib.Path,
                        help="files to scan (default: every tracked file)")
    args = parser.parse_args()

    if not args.patterns.is_file():
        print(f"no pattern file at {args.patterns}: nothing was scanned. "
              "Set the DENYLIST secret, or this gate reports clean without "
              "having looked.", file=sys.stderr)
        return 2

    patterns = patterns_from(args.patterns)
    if not patterns:
        print(f"{args.patterns} holds no patterns: nothing was scanned.",
              file=sys.stderr)
        return 2

    repo = repo_root()
    paths = args.paths or tracked_files(repo)
    hits = scan(paths, patterns, repo)

    print(f"scanned {len(paths)} files against {len(patterns)} patterns")
    if not hits:
        print("clean")
        return 0

    print(f"\nBLOCKED: {len(hits)} denylisted name(s) present.\n")
    for hit in hits:
        print(f"    {hit}")
    print("\nThe name itself is not printed — this log is public. Look the "
          "index up in your local .denylist.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
