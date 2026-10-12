from app.display_time import new_york_time

def test_summer_and_date_rollover():
    assert new_york_time('2026-10-12T03:50:00+00:00') == 'Oct 11, 2026 11:50:00 PM EDT'

def test_winter():
    assert new_york_time('2026-12-12T05:01:00Z') == 'Dec 12, 2026 12:01:00 AM EST'

def test_dst_fall_back():
    assert new_york_time('2026-11-01T05:30:00Z').endswith('01:30:00 AM EDT')
    assert new_york_time('2026-11-01T06:30:00Z').endswith('01:30:00 AM EST')

def test_legacy_utc_and_missing():
    assert new_york_time('2026-10-12T04:01:00') == 'Oct 12, 2026 12:01:00 AM EDT'
    assert new_york_time('bad') == 'Not yet'
    assert new_york_time(None) == 'Not yet'
