from app.core.git_date import format_git_date_kst


def test_naive_git_date_is_treated_as_utc():
    assert format_git_date_kst("2026-09-03 23:52:27") == "2026-09-04 08:52:27"


def test_git_ci_offset_is_honored():
    assert format_git_date_kst("2026-09-03 23:52:27 +0000") == "2026-09-04 08:52:27"
    assert format_git_date_kst("2026-09-04 08:52:27 +0900") == "2026-09-04 08:52:27"


def test_strict_iso_is_converted():
    assert format_git_date_kst("2026-09-03T23:52:27Z") == "2026-09-04 08:52:27"
    assert format_git_date_kst("2026-09-03T23:52:27+00:00") == "2026-09-04 08:52:27"


def test_empty_and_invalid_passthrough():
    assert format_git_date_kst("") == ""
    assert format_git_date_kst("  ") == ""
    assert format_git_date_kst("not-a-date") == "not-a-date"
