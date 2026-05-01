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
from jsonschema.exceptions import ValidationError, best_match
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


_DISCRIMINATOR_FIELDS = ("function", "command", "type", "broadcast_type")


def _is_discriminator_mismatch(sub: ValidationError) -> bool:
    """An error is a discriminator-const mismatch iff it's a `const` failure
    whose absolute_path is exactly the single discriminator field."""
    return (
        sub.validator == "const"
        and len(sub.absolute_path) == 1
        and sub.absolute_path[0] in _DISCRIMINATOR_FIELDS
    )


def _drill_into_oneof(error: ValidationError) -> ValidationError:
    """Drill into a oneOf failure to find the most informative sub-error.

    With our discriminator-const pattern, the top-level oneOf failure carries
    one sub-error per branch in `error.context`. We group sub-errors by branch
    index (from `schema_path[0]=="oneOf", schema_path[1]==idx`). The "winning
    branch" is the one whose discriminator const matched the payload, i.e.
    the branch whose error tree contains NO discriminator-const mismatch.

      - Exactly one winning branch: drill into its errors (the real problem
        is past the discriminator — e.g. `arguments/severity > 5`).
      - Zero winning branches: the payload's discriminator value matches no
        branch — report a discriminator-mismatch error so the caller can say
        "function 'fly_to_moon' is not allowed."
      - More than one (rare): the discriminator wasn't required on every
        branch — fall back to plain best_match.
    """
    while error.context:
        branches: dict[Any, list[ValidationError]] = {}
        for sub in error.context:
            sp = list(sub.schema_path)
            if sp and isinstance(sp[0], int):
                branches.setdefault(sp[0], []).append(sub)
            else:
                branches.setdefault(None, []).append(sub)
        winning_branches = [
            (idx, errs) for idx, errs in branches.items()
            if not any(_is_discriminator_mismatch(e) for e in errs)
        ]
        if len(winning_branches) == 1:
            chosen = best_match(winning_branches[0][1])
        elif len(winning_branches) == 0:
            disc_errors = [e for errs in branches.values() for e in errs
                           if _is_discriminator_mismatch(e)]
            chosen = best_match(disc_errors) if disc_errors else best_match(list(error.context))
        else:
            chosen = best_match(list(error.context))
        if chosen is None or chosen is error:
            break
        error = chosen
    return error


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
    errors = []
    for e in raw_errors:
        resolved = _drill_into_oneof(e)
        errors.append(StructuralError(
            rule_id="STRUCTURAL_VALIDATION_FAILED",
            field_path="/".join(str(p) for p in resolved.absolute_path) or "<root>",
            message=resolved.message,
        ))
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
