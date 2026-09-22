from backend.writing.reliability import assess_reliability


def _results(*scores: int) -> list[dict]:
    return [{"score": score} for score in scores]


def test_stable_dual_rating_passes_gate():
    report = assess_reliability(_results(10, 10, 10), _results(11, 11, 11))
    assert report["stable"] is True
    assert report["review_level"] == "none"


def test_range_catches_outlier_hidden_by_zero_mad():
    report = assess_reliability(_results(8, 8, 15), _results(8, 8, 8))
    assert report["strict"]["mad"] == 0
    assert report["strict"]["range"] == 7
    assert report["stable"] is False
    assert report["review_level"] == "full"
