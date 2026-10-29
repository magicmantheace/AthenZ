# Batch authoring for held-out decision cases (scaffolding)

The Twin evaluation needs **30 owner-approved, independent held-out decision
cases** (see TWIN_EVALUATION_WORKFLOW.md). Adding them one `athenz decision`
call at a time is slow and error-prone, so `athenz-heldout-import` validates
an owner-written JSON batch as a whole before anything is stored.

## Format

A JSON array of 1–200 case objects. Private — keep the file in your private
profile area, never in a Git checkout.

```json
[
  {
    "scenario": "A complete, specific decision situation...",
    "choice": "The option you actually chose",
    "rationale": "Why, in your own words",
    "options": ["First option", "The option you actually chose", "Third option"],
    "exception": "Optional caveat",
    "source_ref": "Optional private reference"
  }
]
```

## Use

```powershell
# Validate only — writes nothing, reports fixed error categories by case index:
athenz-heldout-import --home "$env:USERPROFILE\.athenz" cases.json --split test
# Insert as PENDING decisions after a clean validation:
athenz-heldout-import --home "$env:USERPROFILE\.athenz" cases.json --split test --confirm
```

## Boundaries

- Only `calibration` and `test` splits. Cases are inserted **pending** with
  source `owner:heldout-import`; approval stays a separate per-case owner
  act (`athenz decision-status`), and readiness counts only approved cases.
- The whole batch is refused if any case is malformed, has a choice outside
  its 2–6 options, exactly duplicates an existing scenario (any split,
  case/Unicode-insensitive), contains or is contained in an existing
  scenario as a distinctive phrase, or is a ≥88% token-set near-duplicate
  of an existing or in-batch scenario — the evaluation module's own lexical
  leakage standards. Lexical screening is not semantic independence proof;
  genuinely distinct decisions remain the author's responsibility.
- Errors and reports never echo scenario text — only case indexes and
  categories. The tool never calls a model, approves anything, or starts
  an evaluation.
- If an insert fails partway (for example a concurrent change), the partial
  batch is removed again: a set is only ever stored exactly as screened.
