# QC report: fixture-64ch (UI development only)

> SYNTHETIC fixture for UI development. Not a result.

**64 channels**, reference capacity 2.3001 Ah (batch median), median IR 38.04 mOhm.

| Grade | Channels |
|---|---|
| A | 57 |
| B | 1 |
| C | 4 |
| REJECT | 2 |

## Flagged channels

- **A-03** (grade C): low capacity: capacity_ah = 2.17979 Ah versus batch median 2.30083 Ah (robust z -9.57).
- **C-05** (grade REJECT): high ir: ir_mohm = 61.1644 mOhm versus batch median 38.03587 mOhm (robust z 28.21).
- **D-02** (grade C): capacity creep up: capacity_slope_pct_per_cycle = 1.6 %/cycle versus batch median 0.14793 %/cycle (robust z 33.15).
- **E-07** (grade REJECT): noisy or dead channel: capacity_ah = 0.02 Ah versus batch median 2.3001 Ah (capacity < 10% of batch median).
- **F-01** (grade C): curve shape: dqdv_peak_v = 3.46809 V versus batch median 3.42065 V (robust z 12.59).
- **G-06** (grade C): low ce: first_cycle_ce = 0.84  versus batch median 0.88622  (robust z -8.28).
- **H-04** (grade B): low capacity: capacity_ah = 2.22741 Ah versus batch median 2.30083 Ah (robust z -5.8).
