"""Capability manifest generated from executable read registrations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .schema import CAPABILITY_MANIFEST_VERSION, ContractError


@dataclass(frozen=True)
class Capability:
    name: str
    version: str
    local_only: bool
    read_only: bool
    input_schema: dict
    emits: dict
    bounds: dict
    needs_figures: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version,
                "local_only": self.local_only, "read_only": self.read_only,
                "input_schema": dict(self.input_schema),
                "emits": dict(self.emits), "bounds": dict(self.bounds),
                "needs_figures": self.needs_figures}


@dataclass(frozen=True)
class CapabilityManifest:
    capabilities: tuple[Capability, ...]
    query_sources: tuple[dict, ...] = ()
    query_operators: tuple[dict, ...] = ()
    known_intents: tuple[dict, ...] = ()
    manifest_version: str = CAPABILITY_MANIFEST_VERSION

    @classmethod
    def from_registry(cls, registry) -> "CapabilityManifest":
        capabilities = []
        for spec in registry.specs():
            if not spec.emits:
                raise ContractError(f"capability {spec.name!r} declares no emissions")
            if not spec.bounds:
                raise ContractError(f"capability {spec.name!r} declares no bounds")
            capabilities.append(Capability(
                name=spec.name, version=registry.descriptions_version,
                local_only=spec.local_only, read_only=spec.read_only,
                input_schema=dict(spec.params), emits=dict(spec.emits),
                bounds=dict(spec.bounds), needs_figures=spec.needs_figures))
        query_executor = getattr(registry, "query_executor", None)
        query_sources = tuple(query_executor.sources.manifest()) if query_executor else ()
        if query_executor:
            from ..query.schema import GENERIC_OPERATORS, operator_manifest
            installed = GENERIC_OPERATORS + query_executor.sources.domain_names()
            query_operators = operator_manifest(installed)
        else:
            query_operators = ()
        from .intents import SemanticFamilyRegistry
        known_intents = SemanticFamilyRegistry().manifest()
        return cls(tuple(capabilities), query_sources, query_operators,
                   known_intents)

    def to_dict(self, *, include_digest: bool = True) -> dict:
        out = {"manifest_version": self.manifest_version,
               "capabilities": [item.to_dict() for item in self.capabilities],
               "query_sources": [dict(item) for item in self.query_sources],
               "query_operators": [dict(item) for item in self.query_operators],
               "known_intents": [dict(item) for item in self.known_intents]}
        if include_digest:
            out["digest"] = self.digest
        return out

    @property
    def digest(self) -> str:
        raw = json.dumps(self.to_dict(include_digest=False), sort_keys=True,
                         separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, name: str) -> Capability | None:
        return next((item for item in self.capabilities if item.name == name), None)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.capabilities)
