from copy import deepcopy

import pytest

from backend.speaking_visuals import bins, chart_evidence


def measured():
    return {
        "selection": {"start_s": 0, "end_s": 3},
        "chart": {
            "time_s": [i / 20 for i in range(60)],
            "f0_hz": [100] * 20 + [None] * 20 + [200] * 20,
            "semitones": [-3] * 20 + [None] * 20 + [3] * 20,
        },
        "quality": {"valid_frames": 40, "total_frames": 60, "octave_jumps": 0},
        "features": {"pitch_range_st": 6, "ending_delta_st": -2},
        "words": [{"text": "test", "start_s": 0, "end_s": 3}],
    }


def test_observed_figures_preserve_missing_frames_and_real_units():
    current = measured()
    current["reference"] = {"result": measured()}
    figures = chart_evidence(current)
    assert figures["coverage_percent"] == 66.7
    assert [r["median_f0_hz"] for r in figures["regions"]] == [100, None, 200]
    assert figures["contour_mae_st"] == 0
    assert figures["deviations"][1]["value"] is None
    assert bins(current)[25] is None
    assert figures["dimensions"][1]["value"] == 3
    assert figures["dimensions"][3]["value"] == 2


@pytest.mark.parametrize(
    "reason", ["alignment", "reference_alignment", "octave_jumps", "few_frames"]
)
def test_unreliable_reference_has_no_comparison_number(reason):
    current, reference = measured(), measured()
    if reason == "alignment":
        current["words"] = []
    elif reason == "reference_alignment":
        reference["words"] = []
    elif reason == "octave_jumps":
        current["quality"]["octave_jumps"] = 1
    else:
        reference["chart"]["semitones"] = [None] * 59 + [3]
    current["reference"] = {"result": reference}
    figures = chart_evidence(current)
    assert figures["contour_mae_st"] is None
    assert all(p["value"] is None for p in figures["deviations"])
    assert figures["coverage_percent"] == 66.7


def test_no_reference_or_missing_fields_does_not_invent_values():
    figures = chart_evidence(deepcopy(measured()))
    assert figures["contour_mae_st"] is None
    assert all(d["reference"] is None for d in figures["dimensions"])
    assert chart_evidence({"chart": {}})["regions"][0]["median_f0_hz"] is None
