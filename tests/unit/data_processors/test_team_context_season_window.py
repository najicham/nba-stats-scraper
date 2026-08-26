"""The "season average" window must follow the season, not a literal.

`TeamContextCalculator` computes season-average fallbacks used to decide who
counts as a star, which drives `stars_out` context into predictions. Three of
those CTEs filtered on a hardcoded `game_date >= '2025-10-22'`.

Two defects in one literal:

1. **It expires.** From the 2026-10-20 opener the same literal silently means
   "the last TWO seasons". A player with three games in the new season would get
   a season average dominated by last year's 82, so star identification would be
   computed against a blended regime — with no error, no log line, and no
   visible symptom. Stars-out is cross-season-validated at 68.2% HR; quietly
   changing what it measures is a real money path.

2. **It was already wrong.** The 2025-26 season opened 2025-10-21, not the 22nd,
   so opening night was excluded from every season average it ever computed.

These tests live in tests/unit/ rather than beside the processor deliberately:
`tests/processors/analytics/upcoming_player_game_context/conftest.py` stubs the
`google` namespace in `sys.modules`, which leaks session-wide, and in that
directory `TeamContextCalculator` appears only inside `@pytest.mark.skip`
reasons — the class has no executing coverage there at all.
"""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from data_processors.analytics.upcoming_player_game_context.team_context import (
    TeamContextCalculator,
)

# The three methods carrying a season-average fallback CTE.
SEASON_WINDOW_METHODS = [
    'get_star_teammates_out',
    'get_questionable_star_teammates',
    'get_star_tier_out',
]


@pytest.fixture
def calc():
    """Calculator whose BigQuery client records the call and returns no rows.

    The schedule service is disabled so the fallback table is the single source
    of truth; otherwise these assertions would depend on live DB/GCS state.
    """
    client = Mock()
    client.query.return_value.result.return_value = iter([])
    with patch(
        'shared.config.nba_season_dates._get_schedule_service', return_value=None
    ):
        yield TeamContextCalculator(bq_client=client, project_id='test-project')


def _bound(client, name):
    """Value of a named query parameter from the most recent query() call."""
    job_config = client.query.call_args.kwargs['job_config']
    for p in job_config.query_parameters:
        if getattr(p, 'name', None) == name:
            return p.value
    return None


def _sql(client):
    return client.query.call_args.args[0]


@pytest.mark.parametrize('method', SEASON_WINDOW_METHODS)
class TestSeasonWindowFollowsTheSeason:

    def test_new_season_date_uses_the_new_season_opener(self, calc, method):
        """The regression that arrives on 2026-10-20.

        Under the old literal this bound nothing and the SQL read
        `>= '2025-10-22'`, silently averaging two seasons together.
        """
        getattr(calc, method)('LAL', date(2026, 11, 15))
        assert _bound(calc.bq_client, 'season_start') == date(2026, 10, 20)

    def test_prior_season_date_uses_the_prior_season_opener(self, calc, method):
        """A backfill of a 2025-26 date must still get the 2025-26 window.

        Also pins the off-by-one: the real opener was 10-21, not the 10-22 the
        literal claimed, so opening night used to be excluded.
        """
        getattr(calc, method)('LAL', date(2026, 1, 15))
        assert _bound(calc.bq_client, 'season_start') == date(2025, 10, 21)

    def test_no_hardcoded_season_literal_remains(self, calc, method):
        getattr(calc, method)('LAL', date(2026, 11, 15))
        assert '2025-10-22' not in _sql(calc.bq_client)
        assert '@season_start' in _sql(calc.bq_client)


class TestSeasonBoundary:
    """October flips the season; September does not."""

    def test_october_20_is_the_new_season(self, calc):
        calc.get_star_teammates_out('LAL', date(2026, 10, 20))
        assert _bound(calc.bq_client, 'season_start') == date(2026, 10, 20)

    def test_june_still_belongs_to_the_prior_season(self, calc):
        """Finals in June 2026 are the 2025-26 season, not 2026-27."""
        calc.get_star_teammates_out('LAL', date(2026, 6, 10))
        assert _bound(calc.bq_client, 'season_start') == date(2025, 10, 21)


class TestLookupIsMemoized:

    def test_schedule_service_is_not_consulted_per_call(self, calc):
        """These run per team per date; an uncached lookup would be ~90/slate."""
        with patch(
            'data_processors.analytics.upcoming_player_game_context.team_context.'
            'get_season_start_date',
            return_value=date(2026, 10, 20),
        ) as lookup:
            for _ in range(5):
                calc.get_star_teammates_out('LAL', date(2026, 11, 15))
                calc.get_star_tier_out('BOS', date(2026, 12, 1))

        assert lookup.call_count == 1, (
            f'expected one lookup for the 2026 season, got {lookup.call_count}'
        )

    def test_distinct_seasons_are_looked_up_separately(self, calc):
        """Negative test: memoizing must not collapse different seasons."""
        calc.get_star_teammates_out('LAL', date(2026, 11, 15))
        assert _bound(calc.bq_client, 'season_start') == date(2026, 10, 20)
        calc.get_star_teammates_out('LAL', date(2026, 1, 15))
        assert _bound(calc.bq_client, 'season_start') == date(2025, 10, 21)
