import numpy as np
import pytest
from scipy.stats import norm

from analysis.grading import grade_channel, reference_capacity
from analysis.rules import detect
from analysis.stats import robust_z

TH = dict(capacity_min_pct={"A": 98.0, "B": 95.0, "C": 90.0}, ir_max_pct={"A": 115.0, "B": 130.0, "C": 160.0},
          reject_on_flags=["NOISY_OR_DEAD_CHANNEL"], max_grade_by_severity={"high": "C", "medium": "B"})


def g(cap, ir=38.0, flags=()):
    return grade_channel(cap, ir, flags, reference_capacity_ah=2.0, median_ir_mohm=38.0, **TH)


def test_robust_z_ignores_outlier_in_scale():
    z, med, sigma = robust_z(np.array([1.0, 1.01, 0.99, 1.0, 1.02, 0.98, 5.0]))
    assert med == pytest.approx(1.0)
    assert z[-1] > 100 and abs(z[0]) < 1e-9


def test_robust_z_constant_batch_does_not_divide_by_zero():
    z, _, _ = robust_z(np.ones(10))
    assert np.all(np.isfinite(z)) and np.all(z == 0)


@pytest.mark.parametrize("cap,expected", [(1.97, "A"), (1.95, "B"), (1.85, "C"), (1.79, "REJECT"), (None, "REJECT")])
def test_capacity_bins(cap, expected):
    assert g(cap) == expected


def test_ir_bins_and_flag_caps():
    assert g(2.0, ir=38.0 * 1.2) == "B"
    assert g(2.0, ir=38.0 * 1.7) == "REJECT"
    assert g(2.0, flags=[{"type": "CURVE_SHAPE", "severity": "high"}]) == "C"
    assert g(2.0, flags=[{"type": "LOW_CE", "severity": "medium"}]) == "B"
    assert g(2.0, flags=[{"type": "LOW_CE", "severity": "low"}]) == "A"
    assert g(2.0, flags=[{"type": "NOISY_OR_DEAD_CHANNEL", "severity": "low"}]) == "REJECT"


def test_reference_capacity_bases():
    assert reference_capacity([2.0, 2.1, None, 0.0, 1.9], "batch_median", None) == pytest.approx(2.0)
    assert reference_capacity([], "nominal", 2.5) == 2.5
    with pytest.raises(ValueError):
        reference_capacity([], "nominal", None)


def test_detect_finds_planted_faults_only():
    # Clean channels at evenly spaced normal quantiles (no sampling luck); false-alarm rates on random
    # clean batches are measured in R2, not asserted here.
    ids = [f"ch{i}" for i in range(40)]
    q = norm.ppf((np.arange(40) + 0.5) / 40)
    rng = np.random.default_rng(1)
    cap = 2.0 + 0.01 * rng.permutation(q)
    ir = 40.0 + 1.0 * rng.permutation(q)
    cap[3] = 1.85   # low capacity
    ir[7] = 70.0    # high IR
    cap[9] = 0.01   # dead
    flags = detect(ids, {"capacity_ah": cap.tolist(), "ir_mohm": ir.tolist()})
    flagged = {ch: [f["type"] for f in fs] for ch, fs in flags.items() if fs}
    assert flagged == {"ch3": ["LOW_CAPACITY"], "ch7": ["HIGH_IR"], "ch9": ["NOISY_OR_DEAD_CHANNEL"]}
    assert flags["ch9"][0]["evidence"][0]["robust_z"] is None
