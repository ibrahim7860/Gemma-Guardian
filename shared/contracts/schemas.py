"""Schema loader and validator using jsonschema 4.18+ with referencing.

Loads every shared/schemas/*.json once at import time. Resolves cross-file
$refs into _common.json via a referencing.Registry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"


class ContractError(Exception):
    """Raised by validate_or_raise when a payload fails its contract."""


@dataclass(frozen=True)
class StructuralError:
    rule_id: str
    field_path: str
    message: str


@dataclass(frozen=True)
class ValidationOutcome:
    valid: bool
    errors: list[StructuralError] = field(default_factory=list)


@lru_cache(maxsize=1)
def _load_all() -> dict[str, dict[str, Any]]:
    """Read and parse every shared/schemas/*.json file once per process."""
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(_SCHEMAS_DIR.glob("*.json")):
        out[p.stem] = json.loads(p.read_text())
    return out


@lru_cache(maxsize=1)
def _registry() -> Registry:
    reg = Registry()
    for name, doc in _load_all().items():
        reg = reg.with_resource(
            uri=doc.get("$id", f"local://{name}.json"),
            resource=Resource(contents=doc, specification=DRAFT202012),
        )
    return reg


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    schemas = _load_all()
    if name not in schemas:
        raise KeyError(f"unknown schema: {name!r}")
    return Draft202012Validator(schemas[name], registry=_registry())


def validate(name: str, payload: dict[str, Any]) -> ValidationOutcome:
    """Validate a payload against a named contract schema.

    Returns ValidationOutcome(valid, errors). Errors carry a stable
    rule_id and the failing field path so they can be threaded into
    a corrective prompt.
    """
    validator = _validator(name)
    raw_errors = list(validator.iter_errors(payload))
    if not raw_errors:
        return ValidationOutcome(valid=True)
    errors = [
        StructuralError(
            rule_id="STRUCTURAL_VALIDATION_FAILED",
            field_path="/".join(str(p) for p in e.absolute_path) or "<root>",
            message=e.message,
        )
        for e in raw_errors
    ]
    return ValidationOutcome(valid=False, errors=errors)


def validate_or_raise(name: str, payload: dict[str, Any]) -> None:
    outcome = validate(name, payload)
    if not outcome.valid:
        raise ContractError(f"{name}: {outcome.errors}")


def schema(name: str) -> dict[str, Any]:
    schemas = _load_all()
    if name not in schemas:
        raise KeyError(f"unknown schema: {name!r}")
    return schemas[name]


def all_schemas() -> dict[str, dict[str, Any]]:
    return _load_all()
