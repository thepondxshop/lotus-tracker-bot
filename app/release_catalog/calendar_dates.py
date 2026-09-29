"""Calendar placement only: period endpoints are never exact release dates."""
from __future__ import annotations
import calendar
import re
from datetime import date

SEASONS = {'spring': (3, 5), 'summer': (6, 8), 'autumn': (9, 11), 'fall': (9, 11), 'winter': (12, 2)}
MONTHS = {name.casefold(): i for i in range(1, 13) for name in (calendar.month_name[i], calendar.month_abbr[i])}


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def season_bounds(name, year):
    start_month, end_month = SEASONS[name.casefold()]
    return date(year, start_month, 1), month_end(year + (end_month < start_month), end_month)


def parse_period(label):
    """Parse an explicit date/window field, not arbitrary prose or copyright."""
    label = str(label or '').strip()
    label = re.sub(r'^(?:coming|release(?:s| date)?|launch(?:es)?)\s*:?\s*(?:in\s+)?', '', label, flags=re.I)
    try:
        day = date.fromisoformat(label)
        return {'precision': 'DAY', 'start': day.isoformat(), 'end': day.isoformat(), 'label': label}
    except ValueError:
        pass
    m = re.fullmatch(r'(Q[1-4])\s+(20\d{2})', label, re.I)
    if m:
        year, start_month = int(m[2]), (int(m[1][1])-1)*3+1
        start, end, kind = date(year, start_month, 1), month_end(year, start_month+2), 'QUARTER'
    else:
        m = re.fullmatch(r'(Spring|Summer|Autumn|Fall|Winter)\s+(20\d{2})', label, re.I)
        if m:
            start, end = season_bounds(m[1], int(m[2])); kind = 'SEASON'
        else:
            m = re.fullmatch(r'([A-Za-z]+)\.?\s+(20\d{2})', label)
            if m and m[1].casefold() in MONTHS:
                year, month = int(m[2]), MONTHS[m[1].casefold()]
                start, end, kind = date(year, month, 1), month_end(year, month), 'MONTH'
            elif re.fullmatch(r'20\d{2}', label):
                start, end, kind = date(int(label), 1, 1), date(int(label), 12, 31), 'YEAR'
            else:
                return None
    return {'precision': kind, 'start': start.isoformat(), 'end': end.isoformat(), 'label': label}


def placement(window):
    if not isinstance(window, dict):
        return None
    try:
        start, end = date.fromisoformat(window['start']), date.fromisoformat(window['end'])
    except (KeyError, ValueError, TypeError):
        return None
    kind = str(window.get('precision', '')).upper()
    if start > end or kind not in {'DAY', 'MONTH', 'QUARTER', 'SEASON', 'YEAR'}:
        return None
    if kind == 'DAY' and start != end:
        return None
    return {**window, 'precision': kind, 'anchor': end.isoformat(), 'tba': kind != 'DAY'}


def month_shift(year, month, delta):
    index = year*12 + month-1 + delta
    y, m = divmod(index, 12)
    if not 2000 <= y <= 2099:
        raise ValueError('Choose a month between January 2000 and December 2099.')
    return y, m+1
