"""The tool registry: typed schemas, validated calls, refusal-first errors.

The registry is the modality-neutral contract. It holds each tool's parameter
schema as pure structure (names, types, enums, required — never prose); the
model-facing description of every tool lives in a versioned prompt file
(``tools-<n>.txt``), loaded by id, so what a model was told about a tool is
recorded and immutable the same way every other prompt is. An adapter may
present the schemas natively (provider tool-calling) or as text; the registry
neither knows nor cares.

A call never raises across the boundary: an unknown tool, an unknown argument,
a wrong type or a value outside an enum comes back as a refusal envelope that
names what would have been accepted.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

from vivacore import promptstore

from .envelope import ToolResult, refusal

PROMPTS = pathlib.Path(__file__).resolve().parent.parent / "prompts"

DESCRIPTIONS_VERSION = "tools-v2"

_SECTION_MARK = "# tool: "


def descriptions(version: str = DESCRIPTIONS_VERSION) -> tuple[dict, str]:
    """`({tool name: description}, version)` from the versioned prompt file.

    Parsed from sections headed ``# tool: <name>``; the version id travels with
    the result so a run can record exactly what the model was told."""
    text = promptstore.load(PROMPTS, version)
    out: dict[str, str] = {}
    name = None
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith(_SECTION_MARK):
            if name is not None:
                out[name] = "\n".join(lines).strip()
            name = line[len(_SECTION_MARK):].strip()
            lines = []
        elif name is not None:
            lines.append(line)
    if name is not None:
        out[name] = "\n".join(lines).strip()
    return out, version


@dataclass
class ToolSpec:
    """One tool: its name, its parameter schema (structure only), and the
    function that runs it. The function takes the validated argument dict and
    returns a ToolResult."""
    name: str
    params: dict
    fn: object
    # Whether the tool reads only local state. Every registered tool must; the
    # flag exists so the guard is a checked property rather than a comment.
    local_only: bool = True
    # Whether this tool reasons over what the run has already established
    # rather than over the vault. Such a tool is handed the run's figure book
    # and the turn's question instead of reading the projection.
    needs_figures: bool = False


_TYPES = {"string": str, "boolean": bool, "integer": int, "object": dict,
          "array": list}


def _validate(schema: dict, args: dict, path: str = "") -> list[str]:
    """Problems with `args` against our schema subset, as sentences. Empty
    means valid. Unknown keys are problems: a misspelled filter must refuse
    rather than silently not filter."""
    problems: list[str] = []
    if "properties" not in schema:
        return problems           # an open object: a map of caller-named keys
    props = schema["properties"]
    for key in args:
        if key not in props:
            problems.append(f"unknown field '{path}{key}' — known: "
                            + ", ".join(sorted(props)))
    for key in schema.get("required", []):
        if key not in args:
            problems.append(f"missing required field '{path}{key}'")
    for key, value in args.items():
        if key not in props:
            continue
        spec = props[key]
        want = _TYPES.get(spec.get("type", ""))
        if want is not None and not isinstance(value, want):
            problems.append(f"'{path}{key}' must be {spec['type']}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"'{path}{key}' must be one of: "
                            + ", ".join(map(str, spec["enum"])))
        if spec.get("type") == "object":
            problems.extend(_validate(spec, value, path=f"{path}{key}."))
    return problems


class Registry:
    """The tools a planner may call, presented as data and called by name."""

    def __init__(self, descriptions_version: str = DESCRIPTIONS_VERSION) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._descriptions, self.descriptions_version = descriptions(
            descriptions_version)

    def register(self, spec: ToolSpec) -> None:
        if not spec.local_only:
            raise ValueError(f"tool {spec.name!r} is not local-only; "
                             "no registered tool may touch the network")
        if spec.name not in self._descriptions:
            raise ValueError(
                f"tool {spec.name!r} has no description in "
                f"{self.descriptions_version} — model-facing text lives in the "
                "prompt file, and a tool without one would reach the model "
                "unexplained")
        self._specs[spec.name] = spec

    def names(self) -> list[str]:
        return sorted(self._specs)

    def schemas(self) -> list[dict]:
        """Every tool as data — name, description (from the versioned file),
        parameter schema. What an adapter presents, natively or as text."""
        return [{"name": s.name,
                 "description": self._descriptions[s.name],
                 "parameters": s.params}
                for _, s in sorted(self._specs.items())]

    def call(self, name: str, args: dict | None = None,
             figures: dict | None = None, question: str = "") -> ToolResult:
        """Validate and run one tool. Refuses rather than raising: the result
        is always an envelope.

        The figure book and the question reach only a tool that declared it
        reasons over them."""
        spec = self._specs.get(name)
        if spec is None:
            return refusal(name, "unknown_tool",
                           f"I have no tool named '{name}'.",
                           known_tools=self.names())
        args = args or {}
        if not isinstance(args, dict):
            return refusal(name, "bad_arguments",
                           "Arguments must be an object of named fields.")
        problems = _validate(spec.params, args)
        if problems:
            return refusal(name, "invalid_arguments",
                           "; ".join(problems), schema=spec.params)
        if spec.needs_figures:
            return spec.fn(args, dict(figures or {}), question)
        return spec.fn(args)
