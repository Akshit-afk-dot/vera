import numpy as np
import pandas as pd
import pytest

from analysis.features import channel_features
from synthetic.cell_model import Cell, simulate_cell
from synthetic.generate import PROTOCOL


def one_channel(cell: Cell, cid: str) -> pd.DataFrame:
    df = pd.DataFrame(simulate_cell(cell, PROTOCOL))
    df.insert(0, "channel_id", cid)
    return df


def test_features_recover_simulated_truth():
    cells = [Cell(capacity_ah=2.5 + 0.01 * k, r0_ohm=0.025, r1_ohm=0.015, first_cycle_ce=0.88,
                  creep_pct_per_cycle=0.0, rng=np.random.default_rng(k)) for k in range(6)]
    canon = pd.concat([one_channel(c, f"ch{k}") for k, c in enumerate(cells)], ignore_index=True)
    feats, cycles, curves = channel_features(canon)

    for k, c in enumerate(cells):
        f = feats.loc[f"ch{k}"]
        assert f.capacity_ah == pytest.approx(c.capacity_ah, rel=0.01)       # coulomb counting
        # 1 s step after rest sees R0 + R1(1 - e^-1/60) = 25.25 mOhm; 0.5 mV noise on a 1.25 A step is ~0.6 mOhm
        assert f.ir_mohm == pytest.approx(25.25, abs=2.0)
        assert f.first_cycle_ce == pytest.approx(0.88, abs=0.01)
        assert abs(f.capacity_slope_pct_per_cycle) < 0.5                      # no creep planted
    assert len(cycles["ch0"]) == len(PROTOCOL) and set(curves["ch0"]) == {1, 2, 3, 4}
    assert feats.curve_dist_pct.notna().all()
