"""Checks of the label rule and feature helpers.  Run: ../../.venv/Scripts/python.exe -m pytest test_data.py"""
import csv

import numpy as np
import pytest

import data

FIELDS = ["uuid", "start_date", "end_date", "duration_days", "area_km2", "lon", "lat", "pakistan_share", "centroid_cell", "cells_overlapped", "cells"]


@pytest.fixture
def events(tmp_path, monkeypatch):
    path = tmp_path / "events.csv"
    monkeypatch.setattr(data, "EVENTS", path)

    def write(rows):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in FIELDS})
    return write


def event(start, end, cells, area=5.0, centroid=None):
    listing = ";".join(f"{cell}:{share}:0.01" for cell, share in cells)
    return {"start_date": start, "end_date": end, "area_km2": area, "cells": listing, "centroid_cell": centroid if centroid is not None else cells[0][0]}


DATES = np.arange(np.datetime64("2022-07-01"), np.datetime64("2022-07-21"), dtype="datetime64[D]")


def test_onset_is_labelled_and_following_days_are_masked(events):
    events([event("2022-07-05", "2022-07-06", [(1, 1.0)])])
    label, used, _ = data.build_labels(DATES, 3)
    assert used == 1
    assert label[4, 1] == 1
    assert list(label[5:8, 1]) == [-1, -1, -1]      # ongoing day and the 3-day gap after onset
    assert label[8, 1] == 0
    assert label[4, 0] == 0 and label[4, 2] == 0


def test_repeat_report_inside_the_gap_is_not_a_new_onset(events):
    events([event("2022-07-05", "2022-07-05", [(1, 1.0)]), event("2022-07-07", "2022-07-07", [(1, 1.0)])])
    label, _, _ = data.build_labels(DATES, 3)
    assert label[4, 1] == 1
    assert label[6, 1] == -1
    assert (label[:, 1] == 1).sum() == 1


def test_long_large_or_minor_share_reports_are_not_labels(events):
    events([event("2022-07-02", "2022-07-08", [(0, 1.0)]),                      # 7 days: too long
            event("2022-07-03", "2022-07-03", [(1, 1.0)], area=5000.0),         # too coarse
            event("2022-07-04", "2022-07-04", [(2, 0.6), (0, 0.1)], centroid=2)])
    label, used, dropped = data.build_labels(DATES, 3)
    assert used == 1
    assert dropped["too_long"] == 1 and dropped["too_large_or_unlocated"] == 1
    assert label[3, 2] == 1 and label[3, 0] == 0                                # 10 % share is not enough


def test_lagged_sum_skips_windows_with_missing_days():
    values = np.arange(1, 11, dtype=np.float32)[:, None]
    values[6, 0] = np.nan
    out = data.lagged_sum(values, 1, 3)
    assert np.isnan(out[2, 0])                       # needs days -1..1
    assert out[3, 0] == 1 + 2 + 3
    assert out[6, 0] == 4 + 5 + 6
    assert np.isnan(out[7, 0]) and np.isnan(out[9, 0])   # windows containing the missing day 6
    assert data.lagged_sum(values, 1, 2)[9, 0] == 8 + 9


def test_shift_does_not_leak_the_target_day():
    values = np.arange(5, dtype=np.float32)[:, None]
    shifted = data.shift(values, 1)
    assert np.isnan(shifted[0, 0]) and shifted[3, 0] == 2
