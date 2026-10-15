# Twin writing-style validation partitions

## Protected Twin writing-style evaluation splits (schema v6)

New AthenZ writing samples have an immutable **dataset split**:
`train`, `calibration` or `test`. Existing approved writing samples
migrate to `train` without changing their review status, provenance,
or contents; **no old writing becomes a held-out gold reference automatically**.
All samples remain pending until individually reviewed. Approval rejects obvious\nnormalized exact duplicates across splits; semantically paraphrased copies\nare not yet detected and must be screened separately. New examples:

```sh
athenz sample "An owner-written training paragraph" --split train
athenz sample "A separate owner-written evaluation paragraph" --split test
athenz review writing_samples 2 approved
athenz style-readiness
```

`style-readiness` is strictly local/read-only. It outputs aggregate
approved/pending/rejected counts by split and counts obvious normalized
exact-text duplicates across approved splits. Pilot readiness requires
at least three approved training samples, three approved test samples,
and no detected exact normalized cross-split duplicates. **It does not
evaluate personality, semantic similarity, model quality or statistical
independence.** Never put the owner's actual samples into public CI.

Twin prompt assembly and held-out decision-contamination checks read
**only approved `train` writing samples**; even approved calibration/test
writing is withheld. Protected held-out writing does not change the prompt
reference fingerprint; train writing still does. The fingerprint projects
the original pre-v6 writing columns, preserving previous approved-training
comparisons for records that did not change. The v6 backup/restore validator
accepts this new database without exporting private prose to GitHub.

Next milestone: implement an explicitly consented, **blinded owner style
comparison** evaluating outputs on held-out writing tasks, with strong
literal and semantic contamination checks. Only owner judgments on unseen
materials should be reported as actual Twin style fidelity.


### Additional lexical independence protection

Owner review rejects near-duplicate passages *across* writing sample splits,
as well as exact normalized copies. Separate blind-comparison task preflight
also rejects substantial overlap with either approved train writing (which
would favor memorization) or protected test/calibration writing (which
would contaminate the holdout). The screen is lexical, not semantic; avoid
paraphrased copies and personally review task independence before a pilot.
