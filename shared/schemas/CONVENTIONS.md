# `shared/schemas/` Conventions

This directory hosts the locked JSON Schema definitions referenced by
[Contract 1](../../docs/20-integration-contracts.md#contract-1-json-schema-locking).
Every schema in here is part of the agreed-upon Day-1 contract surface.
Do not change shapes without a contract-revision sign-off.

## `$id` Convention

Every top-level schema file MUST set an absolute `$id`:

```json
{
  "$id": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/<file>.json",
  ...
}
```

`v1` is the contract version. If we ever ship a `v2`, it goes in a
sibling directory and the `$id` base updates accordingly.

## `$ref` Convention

All `$ref` values are RELATIVE. There are two shapes:

### Internal refs (within the same file)

Use a fragment-only ref:

```json
{"$ref": "#/$defs/finding_approval"}
```

### Cross-file refs

Use the relative file name + fragment:

```json
{"$ref": "_common.json#/$defs/iso_timestamp_utc_ms"}
{"$ref": "drone_state.json"}
```

DO NOT use absolute URIs in `$ref`:

```json
// WRONG — DO NOT DO THIS
{"$ref": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/iso_timestamp_utc_ms"}
```

## Why Relative

JSON Schema 2020-12 resolves relative refs against the enclosing
schema's `$id` base. Because every schema's `$id` shares the same
`v1/` base, a relative ref like `_common.json#/$defs/foo` resolves
to `https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/foo`
correctly.

The benefit: if we ever rename the GitHub org, change the path, or
migrate to a different schema host, we only update the `$id` lines.
The `$ref` values are stable.

If we used absolute `$ref` URIs instead, every rename would require a
search-and-replace across every schema, with the risk of missing one.

## Adding a New Schema

1. Pick a filename: `<purpose>.json` (e.g., `peer_broadcast.json`).
2. Set `$id` to `https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/<filename>.json`.
3. Use relative `$ref` for any cross-file references.
4. Add fixtures under `shared/schemas/fixtures/valid/` and `fixtures/invalid/`.
5. Add a test under `shared/tests/test_<purpose>.py` that loads the
   schema, validates the fixtures, and references RuleIDs from
   `docs/20-integration-contracts.md`.

## Verifying Convention Compliance

Run from the repo root:

```bash
# All cross-file refs must use relative paths (no http://)
grep -h '"\$ref"' shared/schemas/*.json | grep -E '"http' && echo "FAIL: absolute \$ref found" || echo "PASS"

# Every top-level schema must have an absolute $id
for f in shared/schemas/*.json; do
  grep -q '"\$id".*"https://' "$f" || echo "MISSING \$id: $f"
done
```

Both should print `PASS` / no missing-`$id` lines.
