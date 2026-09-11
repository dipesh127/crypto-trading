from datetime import datetime, timezone
from app.dashboard.lttb import lttb
from app.dashboard.service import encode_cursor, decode_cursor, choose_interval


def test_lttb_keeps_endpoints_and_cap():
    pts=[[float(i), float(i*i)] for i in range(100)]
    out=lttb(pts,10)
    assert len(out)==10
    assert out[0]==pts[0]
    assert out[-1]==pts[-1]


def test_cursor_roundtrip():
    ts=datetime(2026,1,2,3,4,5,tzinfo=timezone.utc)
    c=encode_cursor(ts,'12345')
    got_ts,got_id=decode_cursor(c)
    assert got_ts==ts and got_id=='12345'


def test_visible_range_resolution():
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    assert choose_interval(start, start.replace(hour=2))=='1 minute'
    assert choose_interval(start, start.replace(day=10))=='15 minutes'

def test_dashboard_response_caps_are_constants():
    from app.dashboard.service import MAX_POINTS, MAX_ROWS
    assert MAX_POINTS == 2500
    assert MAX_ROWS == 250
