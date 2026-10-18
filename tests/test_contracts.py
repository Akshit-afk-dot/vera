import json
from pathlib import Path

from pydantic import TypeAdapter

from analysis.grading import grade_channel
from contracts.models import BatchResults, Event

FIX = Path(__file__).resolve().parent.parent / "contracts" / "fixtures"


def test_event_fixture_validates_and_is_ordered():
    adapter = TypeAdapter(Event)
    lines = (FIX / "sample_run.jsonl").read_text(encoding="utf-8").splitlines()
    events = [adapter.validate_json(line) for line in lines]
    assert events[0].type == "run.started" and events[-1].type == "run.finished"
    assert [e.seq for e in events] == list(range(len(events)))
    assert all(a.ts <= b.ts for a, b in zip(events, events[1:], strict=False))
    assert {e.run_id for e in events} == {events[0].run_id}


def test_results_fixture_grades_match_grading_code():
    res = BatchResults.model_validate_json((FIX / "sample_results.json").read_text(encoding="utf-8"))
    th = res.thresholds
    assert res.data_label == "SYNTHETIC"
    for ch in res.channels:
        expected = grade_channel(
            ch.capacity_ah, ch.ir_mohm, [f.model_dump() for f in ch.flags],
            reference_capacity_ah=res.summary.reference_capacity_ah, median_ir_mohm=res.summary.median_ir_mohm,
            capacity_min_pct=th.capacity_min_pct, ir_max_pct=th.ir_max_pct,
            reject_on_flags=th.reject_on_flags, max_grade_by_severity=th.max_grade_by_severity)
        assert ch.grade == expected, ch.channel_id
    assert sum(res.summary.grade_counts.values()) == res.summary.n_channels == len(res.channels)


def test_every_flag_cites_evidence():
    res = json.loads((FIX / "sample_results.json").read_text(encoding="utf-8"))
    for ch in res["channels"]:
        for f in ch["flags"]:
            assert f["evidence"] and all("value" in e and "batch_median" in e for e in f["evidence"])
