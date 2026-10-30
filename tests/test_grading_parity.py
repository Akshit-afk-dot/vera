"""The browser regrades with web/grading.js; it must agree with analysis/grading.py on every channel."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from analysis.grading import grade_channel, reference_capacity

ROOT = Path(__file__).resolve().parent.parent
VARIANTS = [
    {},
    {"capacity_min_pct": {"A": 99.5, "B": 97.0, "C": 92.0}},
    {"ir_max_pct": {"A": 105.0, "B": 110.0, "C": 140.0}},
    {"basis": "nominal", "nominal_capacity_ah": 2.33},
    {"max_grade_by_severity": {"high": "REJECT"}},
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_and_python_grading_agree(tmp_path):
    res = json.loads((ROOT / "contracts" / "fixtures" / "sample_results.json").read_text(encoding="utf-8"))
    variants = [{**res["thresholds"], **v} for v in VARIANTS]
    script = tmp_path / "parity.mjs"
    script.write_text(
        f"import {{ regrade }} from {json.dumps((ROOT / 'web' / 'grading.js').as_uri())};\n"
        f"const res = {json.dumps(res)};\nconst variants = {json.dumps(variants)};\n"
        "console.log(JSON.stringify(variants.map((t) => regrade(res, t))));\n", encoding="utf-8")
    js = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)

    for th, js_grades in zip(variants, js, strict=True):
        ref = reference_capacity([c["capacity_ah"] for c in res["channels"]], th["basis"], th.get("nominal_capacity_ah"))
        py = [grade_channel(c["capacity_ah"], c["ir_mohm"], c["flags"], reference_capacity_ah=ref,
                            median_ir_mohm=res["summary"]["median_ir_mohm"], capacity_min_pct=th["capacity_min_pct"],
                            ir_max_pct=th["ir_max_pct"], reject_on_flags=th["reject_on_flags"],
                            max_grade_by_severity=th["max_grade_by_severity"]) for c in res["channels"]]
        assert js_grades == py, th
