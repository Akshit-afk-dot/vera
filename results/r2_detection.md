**R2: planted-fault detection [SYNTHETIC]** · 6 faulty batches (156 planted faults) + 4 clean batches (512 channels) · 128 channels each

| Method | Precision | Recall | F1 | Typed F1 | False alarms on clean batches |
|---|---|---|---|---|---|
| Vera rules (robust z, \|z\|>3.5) | 0.98 | 0.93 | 0.95 | 0.95 | 0.39% |
| Baseline: mean/std z-score (\|z\|>3) | 0.81 | 0.47 | 0.60 | 0.52 | 3.32% |
| Baseline: Isolation Forest (untyped) | 0.48 | 0.41 | 0.44 | untyped | 13.28% |

Recall by fault type and severity (Vera rules):

| Fault | Precision | Recall | F1 |
|---|---|---|---|
| LOW_CAPACITY | 1.00 | 0.85 | 0.92 |
| HIGH_IR | 0.94 | 0.70 | 0.80 |
| CURVE_SHAPE | 0.96 | 1.00 | 0.98 |
| CAPACITY_CREEP_UP | 1.00 | 1.00 | 1.00 |
| LOW_CE | 1.00 | 1.00 | 1.00 |
| NOISY_OR_DEAD_CHANNEL | 0.97 | 1.00 | 0.98 |

| Severity level (mildest → strongest) | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Recall | 0.74 | 1.00 | 1.00 | 1.00 |

Threshold sweep (Vera rules, any-fault detection):

| \|z\| threshold | Precision | Recall | False alarms on clean batches |
|---|---|---|---|
| 2.5 | 0.75 | 0.95 | 5.66% |
| 3.0 | 0.92 | 0.94 | 1.76% |
| 3.5 | 0.98 | 0.93 | 0.39% |
| 4.0 | 1.00 | 0.92 | 0.00% |
| 5.0 | 1.00 | 0.90 | 0.00% |
