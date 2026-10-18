import zipfile

import numpy as np
import pytest
from openpyxl import Workbook
from scipy.io import savemat

from agent.ingest.peek import peek, safe_extract


def test_mat_struct_array_groups_record_variants(tmp_path):
    charge = {"type": "charge", "data": {"Voltage": np.linspace(3.0, 4.2, 50), "Time": np.arange(50.0)}}
    discharge = {"type": "discharge", "data": {"Voltage": np.linspace(4.2, 3.0, 40), "Capacity": 1.85}}
    cycles = np.empty((1, 3), dtype=object)
    cycles[0, :] = [charge, discharge, charge]
    path = tmp_path / "cell.mat"
    savemat(path, {"B01": {"cycle": cycles}})

    s = peek(path)
    rec = s["tree"]["B01"]["cycle"]
    assert s["kind"] == "mat" and rec["records"] == 3
    assert {v["string_values"]["type"].popitem()[0] for v in rec["variants"]} == {"charge", "discharge"}


def test_text_sniffs_semicolon_and_keeps_preamble(tmp_path):
    path = tmp_path / "export.csv"
    path.write_text("Tester: LAB-07\nRec;Cyc;Volts (mV)\n1;1;3412,5\n2;1;3501,2\n", encoding="utf-8")
    s = peek(path)
    assert s["kind"] == "text" and s["sniffed_delimiter"] == ";" and s["first_lines"][0] == "Tester: LAB-07"


def test_excel_lists_sheets(tmp_path):
    wb = Workbook()
    wb.active.title = "Channel_1"
    wb.active.append(["Time", "Voltage"])
    wb.create_sheet("Channel_2")
    wb.save(tmp_path / "x.xlsx")
    s = peek(tmp_path / "x.xlsx")
    assert s["kind"] == "excel" and s["sheet_names"] == ["Channel_1", "Channel_2"]


def test_safe_extract_refuses_zip_slip(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        safe_extract(bad, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()
