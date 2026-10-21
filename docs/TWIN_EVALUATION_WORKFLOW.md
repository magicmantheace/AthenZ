# Standalone Twin — private evaluation workflow

This is the owner's practical **Twin-first** acceptance gate. No AthenZ–Synveil,
Developmental AI integration, background worker, model promotion, or fine-tuning
is authorized by following these commands.

## 1. Check approved data without using a model

On the actual Windows machine, use the existing, **private** profile directory:

```powershell
athenz-twin-readiness --home "$env:USERPROFILE\.athenz"
```

The output is **aggregate-only**. It reports how many approved owner
facts/preferences and held-out cases are available, the writing sample split
counts, conservative lexical contamination checks, and exact next-action
codes. It doesn't list private memories, case text, options, gold rationales,
model outputs or file paths. It doesn't run Ollama, approve memories, train
weights, or compare model output.

Default target: **30 owner-approved, separately reviewed final-test decision
cases**. These must be genuinely independent across decisions/categories.
The existing parser also checks lexical duplicate/scenario contamination,
choice validity and in-flight dataset changes. Lexical independence does not
prove semantic independence. Hold out the answers, review the split and do
not use the final-test cases when deciding how to tune prompts.

A writing-style pilot additionally needs at least **three reviewed training
writing samples and three distinct held-out writing samples** to start.
The v1 Twin acceptance target remains **20 independently owner-rated writing
prompt comparisons**; 3+3 is *pilot eligibility*, not completion of that
target. Keep private writing samples and judgments out of GitHub.

## 2. Calibrate with a separate split before final evaluation

Use a separate collection of approved calibration scenarios. Start with a
smaller exploratory sample to identify failure patterns and unreliable
abstentions without peeking at final-test cases.

```powershell
athenz-decision-compare --home "$env:USERPROFILE\.athenz" --split calibration --limit 10 --model qwen3.5:2b --allow-abstain --confirm
```

The same **installed local Ollama model** powers Twin and neutral arms, with
identical scenarios and option order. Only the Twin arm sees approved
personal context. Output is aggregate statistics (accuracy per arm, paired
wins/regressions, coverage and abstentions). Do not interpret small-sample
differences as identity transfer or robust personalization.

After freezing the owner-reviewed final-test data and acceptance rules,
use the existing protected frozen-test-plan mechanism. The specific
`--split test`, model tag, limit, seed, abstention settings and any
category-review choices must be identical when freezing and evaluating.
The final comparison has **two local inference calls per held-out case**
(60 for 30 cases at one stability trial). Repeated test-set inspection or
iterating on final outcomes undermines independence.

```powershell
athenz-decision-compare --home "$env:USERPROFILE\.athenz" --split test --limit 30 --model qwen3.5:2b --allow-abstain --freeze-test-plan --confirm
athenz-decision-compare --home "$env:USERPROFILE\.athenz" --split test --limit 30 --model qwen3.5:2b --allow-abstain --use-test-plan --confirm
```

The frozen-plan workflow checks exact settings and evidence; it does
**not** bypass the owner review of case categories or demonstrate real owner
prediction improvement unless actual evaluation is executed.

## 3. Blinded writing preference study

Use distinct prompts written for evaluation, not copied from the held-out
writing examples. Before generation, ensure the local model is installed.

```powershell
athenz-style-compare --home "$env:USERPROFILE\.athenz" start "Write a brief fictional project delay announcement." --model qwen3.5:2b --confirm
athenz-style-compare --home "$env:USERPROFILE\.athenz" show 1
athenz-style-compare --home "$env:USERPROFILE\.athenz" rate 1 A --confirm
athenz-style-compare --home "$env:USERPROFILE\.athenz" report
```

Replace `1` with the returned private comparison ID; replace `A` with
the blind reviewer choice **A**, **B**, or **tie**. Don't infer which side
was Twin from presentation order. Repeat across independent questions,
voice/style contexts and complexity levels. At least **20 valid blinded
ratings** are the roadmap target; the existing comparison reporter separates
model cohorts and stale/invalid data.

## 4. Target-device verification and decision

GitHub Actions passing is **code compatibility evidence**, not local
Ollama or graphics validation. On the actual Windows 11 machine, run
the disposable synthetic lifecycle test, then private owner-driven Twin
chat and evaluation:

```powershell
athenz-chat-smoke --model qwen3.5:2b --twin-lifecycle --confirm
athenz-desktop
```

Collect owner-held-out accuracy versus neutral, coverage, abstention
quality, preferred writing style, failures and available CPU/RAM/GPU/latency
observations. Never publish private prompts or run results containing raw
owner answers. The result can support a narrow practical Twin milestone;
it cannot certify human-level prediction, consciousness or literal mind
copying. No automatic model promotion is authorized.
