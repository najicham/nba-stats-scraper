"""The season label and the season window must name the same season.

The publishing layer carried two different season boundaries:

  label   `month >= 10`                     -> flips in October
  window  `date(year, 11, 1)`, `month >= 11` -> flips on November 1

They agree for 354 days a year. For the eleven days from opening night to
October 31 they do not, and the failure is silent and public: an exporter stamps
`season: '2026-27'` on a query window beginning 2025-11-01, so the site shows the
**previous** season's picks and W-L record under the **new** season's name,
during opening week — the exact stretch when a reader is most likely to check.

Measured 2026-08-26: 203 rows in `signal_best_bets_picks` and 92 in
`best_bets_published_picks` fall in that window. (The handoff's "~650" is the
2025-26 final graded record, 415-235; the tables these exporters actually read
hold far fewer.)

The Nov-1 literal was never a deliberate "skip early season" rule — no comment
or test anywhere justified it, and since real openers fall in October it also
truncated opening week from every season record it computed.

Fixed by deriving both halves from `get_season_window()`, so they cannot drift
apart again. These tests pin the invariant rather than the implementation.
"""

import pathlib
import re
from datetime import date, timedelta

import pytest

from shared.config.nba_season_dates import (
    get_season_start_date,
    get_season_window,
    get_season_year_from_date,
)

REPO = pathlib.Path(__file__).resolve().parents[3]
PUBLISHING = REPO / 'data_processors' / 'publishing'


def _label_season_year(label: str) -> int:
    return int(label.split('-')[0])


class TestLabelAndWindowNameTheSameSeason:

    def test_every_day_across_the_flip_agrees(self):
        """Sept 1 2026 -> Dec 31 2026, day by day. The old code broke Oct 20-31."""
        d, end, mismatches = date(2026, 9, 1), date(2026, 12, 31), []
        while d <= end:
            start, label = get_season_window(d)
            if get_season_year_from_date(start) != _label_season_year(label):
                mismatches.append((d, start, label))
            d += timedelta(days=1)
        assert not mismatches, (
            f'{len(mismatches)} dates label a window from another season, '
            f'first: {mismatches[:3]}'
        )

    @pytest.mark.parametrize('day', range(20, 32))
    def test_opening_window_uses_the_new_season(self, day):
        """The eleven broken days. Old code returned 2025-11-01 for all of them."""
        start, label = get_season_window(date(2026, 10, day))
        assert start == date(2026, 10, 20)
        assert label == '2026-27'
        assert start.year == 2026, 'must not reach back into the prior season'

    def test_window_starts_on_opening_night_not_november(self):
        """Opening week belongs in the season record."""
        start, _ = get_season_window(date(2026, 11, 15))
        assert start == date(2026, 10, 20)
        assert start != date(2026, 11, 1), 'the Nov-1 stand-in truncated opening week'

    def test_midseason_is_unchanged(self):
        """Negative test: the fix must not move the 354 days that were correct."""
        start, label = get_season_window(date(2026, 2, 1))
        assert label == '2025-26'
        assert start == get_season_start_date(2025)

    def test_september_is_still_the_prior_season(self):
        """Negative test: the off-season must not flip early."""
        _, label = get_season_window(date(2026, 9, 30))
        assert label == '2025-26'


class TestNoExporterReintroducesTheNovemberBoundary:
    """Structural guard. The literal appeared in 9 sites across 7 files.

    It spread by copy-paste — one carried the comment "same logic as
    AllSubsetsPicksExporter" — so the realistic failure mode is someone pasting
    it back, not reasoning their way to it again.
    """

    # `date(<year-ish>, 11, 1)` — a hardcoded November 1 season boundary.
    NOV_FIRST = re.compile(r'date\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*,\s*11\s*,\s*1\s*\)')
    MONTH_11 = re.compile(r'month\s*>=\s*11')

    def _modules(self):
        return sorted(PUBLISHING.glob('*.py'))

    def test_the_guard_sees_the_exporters(self):
        """Guard the guard: a broken glob would make this vacuously pass."""
        mods = self._modules()
        assert len(mods) > 10, f'expected many exporters, found {len(mods)}'

    def test_no_hardcoded_november_first(self):
        hits = [m.name for m in self._modules() if self.NOV_FIRST.search(m.read_text())]
        assert not hits, (
            'hardcoded Nov-1 season window is back — use get_season_window(): '
            f'{hits}'
        )

    def test_no_month_ge_11_season_boundary(self):
        hits = [m.name for m in self._modules() if self.MONTH_11.search(m.read_text())]
        assert not hits, (
            'a `month >= 11` season boundary is back; the label flips in '
            f'October, so this desynchronises them for 11 days: {hits}'
        )
