"""Contract tests for the three roster source handlers.

These decide whether the Oct 1-19 registry seed succeeds. Each handler answers
one question — "which players were on rosters as of this date?" — against a
different table, a different date column, and a different fallback window. Get
the window wrong and the seed silently draws from the wrong day, or from
nothing: the 2026-08-22 rehearsal produced 522 rows from a single source because
NBA.com's 7-day window caught no scrape and BR's data postdated the target.

Why this file exists
--------------------
The previous tests for this logic called `_get_espn_roster_players_strict`,
`_get_nba_official_players_strict` and `_get_basketball_reference_players_strict`
on the processor. Commit 45953cb6 (2026-01-25) moved that logic into these
handler classes with a new API and did not update the tests, so all nine had
been erroring for 209 days — the three handlers on the critical seed path had
ZERO executing coverage for seven months.

So these tests key to the PUBLIC contract, not to method names:

    get_roster_players(season_year, data_date, allow_fallback)
        -> (players: Set[str], actual_date: date | None, matched: bool)

A rename inside a handler cannot silently delete this coverage again; only
changing that contract can, which is the point.

The shared behaviour is parametrized across all three handlers, so a fourth
source added later joins by adding one row to HANDLERS. Per-source specifics
(table, date column, window, is_active) are asserted individually, because those
are exactly the things that differ and exactly the things that break.
"""

from datetime import date
from unittest.mock import Mock

import pandas as pd
import pytest
from google.api_core.exceptions import GoogleAPIError

from data_processors.reference.player_reference.sources.br_source import (
    BRSourceHandler,
    normalize_team_abbr,
)
from data_processors.reference.player_reference.sources.espn_source import ESPNSourceHandler
from data_processors.reference.player_reference.sources.nba_source import NBASourceHandler

PROJECT = 'test-project'
TARGET = date(2026, 10, 5)          # inside the Oct 1-19 seed window
AUTHORITATIVE_WINDOWS = {'nba': 7, 'espn': 30, 'br': 30}

HANDLERS = [
    pytest.param(NBASourceHandler, 'nbac_player_list_current', 'source_file_date', 7, id='nba'),
    pytest.param(ESPNSourceHandler, 'espn_team_rosters', 'roster_date', 30, id='espn'),
    pytest.param(BRSourceHandler, 'br_rosters_current', 'last_scraped_date', 30, id='br'),
]


def _frame(date_col, players, when):
    return pd.DataFrame([{'player_lookup': p, date_col: when} for p in players])


def _empty():
    return pd.DataFrame()


def _client(*frames):
    """A BigQuery client returning `frames` from successive query() calls."""
    client = Mock()
    jobs = []
    for fr in frames:
        job = Mock()
        job.to_dataframe.return_value = fr
        jobs.append(job)
    client.query.side_effect = jobs
    return client


def _sql(client, call_index):
    return client.query.call_args_list[call_index][0][0]


# ---------------------------------------------------------------------------
# Shared contract — every handler must behave identically here
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('handler_cls,table,date_col,window_days', HANDLERS)
class TestSharedContract:

    def test_exact_match_reports_matched_true(self, handler_cls, table, date_col, window_days):
        client = _client(_frame(date_col, ['lebronjames', 'stephencurry'], TARGET))
        players, actual, matched = handler_cls(client, PROJECT).get_roster_players(2026, TARGET)
        assert players == {'lebronjames', 'stephencurry'}
        assert actual == TARGET
        assert matched is True

    def test_strict_mode_returns_nothing_and_issues_no_fallback_query(
        self, handler_cls, table, date_col, window_days
    ):
        """allow_fallback=False must not reach for older data at all."""
        client = _client(_empty())
        players, actual, matched = handler_cls(client, PROJECT).get_roster_players(
            2026, TARGET, allow_fallback=False
        )
        assert players == set()
        assert actual is None
        assert matched is False
        assert client.query.call_count == 1, (
            "strict mode issued a fallback query; it must not look outside the exact date"
        )

    def test_fallback_returns_older_data_and_reports_matched_false(
        self, handler_cls, table, date_col, window_days
    ):
        older = date(2026, 10, 1)
        client = _client(_empty(), _frame(date_col, ['lukadoncic'], older))
        players, actual, matched = handler_cls(client, PROJECT).get_roster_players(
            2026, TARGET, allow_fallback=True
        )
        assert players == {'lukadoncic'}
        assert actual == older
        assert matched is False, (
            "fallback data must report matched=False — callers use this to know the "
            "roster is not as-of the requested date"
        )

    def test_fallback_with_nothing_in_window_returns_empty(
        self, handler_cls, table, date_col, window_days
    ):
        client = _client(_empty(), _empty())
        players, actual, matched = handler_cls(client, PROJECT).get_roster_players(
            2026, TARGET, allow_fallback=True
        )
        assert (players, actual, matched) == (set(), None, False)

    def test_api_error_fails_closed_rather_than_raising(
        self, handler_cls, table, date_col, window_days
    ):
        client = Mock()
        client.query.side_effect = GoogleAPIError('boom')
        players, actual, matched = handler_cls(client, PROJECT).get_roster_players(
            2026, TARGET, allow_fallback=True
        )
        assert (players, actual, matched) == (set(), None, False)

    def test_pandas_timestamp_is_returned_as_a_date(
        self, handler_cls, table, date_col, window_days
    ):
        client = _client(_frame(date_col, ['jaysontatum'], pd.Timestamp('2026-10-05')))
        _, actual, _ = handler_cls(client, PROJECT).get_roster_players(2026, TARGET)
        assert actual == TARGET
        assert not isinstance(actual, pd.Timestamp), 'callers compare this against date objects'

    def test_duplicate_rows_collapse_to_one_player(
        self, handler_cls, table, date_col, window_days
    ):
        dupes = pd.DataFrame([
            {'player_lookup': 'nikolajokic', date_col: TARGET},
            {'player_lookup': 'nikolajokic', date_col: TARGET},
        ])
        players, _, _ = handler_cls(client := _client(dupes), PROJECT).get_roster_players(2026, TARGET)
        assert players == {'nikolajokic'}
        assert client.query.call_count == 1

    # -- SQL shape: the constants that decide whether the seed finds data ----

    def test_exact_query_targets_the_documented_table_and_date_column(
        self, handler_cls, table, date_col, window_days
    ):
        client = _client(_frame(date_col, ['x'], TARGET))
        handler_cls(client, PROJECT).get_roster_players(2026, TARGET)
        sql = _sql(client, 0)
        assert f'nba_raw.{table}' in sql
        assert f'{date_col} = @data_date' in sql

    def test_fallback_window_matches_the_documented_number_of_days(
        self, handler_cls, table, date_col, window_days
    ):
        """The single most consequential constant in the seed path.

        NBA.com is 7 days while ESPN and BR are 30. On 2025-10-20 that difference
        is why NBA.com contributed nothing: its only scrape in a seven-week span
        was 2025-10-01, nineteen days earlier.
        """
        import re
        client = _client(_empty(), _empty())
        handler_cls(client, PROJECT).get_roster_players(2026, TARGET, allow_fallback=True)
        found = re.findall(r'INTERVAL\s+(\d+)\s+DAY', _sql(client, 1))
        assert found, 'fallback query has no INTERVAL bound — it can reach arbitrarily far back'
        assert len(found) == 2, (
            f'expected the window bound in both the outer query and the MAX() '
            f'subquery, found {len(found)}'
        )
        assert set(found) == {str(window_days)}, (
            f'fallback window is {set(found)} days, documented as {window_days}'
        )

    def test_fallback_never_reaches_past_the_requested_date(
        self, handler_cls, table, date_col, window_days
    ):
        """A point-in-time seed must not borrow roster data from the future."""
        client = _client(_empty(), _empty())
        handler_cls(client, PROJECT).get_roster_players(2026, TARGET, allow_fallback=True)
        sql = _sql(client, 1)
        # The bound appears twice - once in the outer WHERE and once inside the
        # MAX() subquery that picks the latest usable date. Both are load-bearing,
        # and asserting mere presence would pass if one were dropped, so count.
        found = sql.count(f'{date_col} <= @data_date')
        assert found == 2, (
            f'expected the upper bound on {date_col} in both the outer query and '
            f'the MAX() subquery, found {found}. Without both, the fallback can '
            f'select roster data recorded after the date being seeded.'
        )


# ---------------------------------------------------------------------------
# Per-source specifics
# ---------------------------------------------------------------------------

class TestNBAOnlyBehaviour:

    def test_both_queries_filter_to_active_players(self):
        """NBA.com's list includes inactive players; the registry must not."""
        client = _client(_empty(), _empty())
        NBASourceHandler(client, PROJECT).get_roster_players(2026, TARGET, allow_fallback=True)
        # Counted, not merely present: the fallback needs the filter in the outer
        # query AND in the MAX() subquery. Dropping either one lets retired or
        # inactive players into the registry, and a presence check would not notice.
        for i, label, expected in ((0, 'exact', 1), (1, 'fallback', 2)):
            found = _sql(client, i).count('is_active = TRUE')
            assert found == expected, (
                f'{label} query has {found} is_active filters, expected {expected}'
            )


class TestAuthorityScores:
    """Precedence when sources disagree: NBA.com official > ESPN > Basketball Reference."""

    def test_scores_are_ordered_nba_then_espn_then_br(self):
        client = Mock()
        nba = NBASourceHandler(client, PROJECT).authority_score
        espn = ESPNSourceHandler(client, PROJECT).authority_score
        br = BRSourceHandler(client, PROJECT).authority_score
        assert nba > espn > br, f'authority order broken: nba={nba} espn={espn} br={br}'


class TestBRTeamNormalization:
    """Basketball Reference uses its own team codes; the registry keys on NBA codes."""

    @pytest.mark.parametrize('br_code,nba_code', [
        ('BRK', 'BKN'), ('CHO', 'CHA'), ('PHO', 'PHX'),
    ])
    def test_known_divergent_codes_are_normalized(self, br_code, nba_code):
        assert normalize_team_abbr(br_code) == nba_code

    @pytest.mark.parametrize('code', ['LAL', 'BOS', 'GSW', 'DEN'])
    def test_matching_codes_pass_through_unchanged(self, code):
        assert normalize_team_abbr(code) == code


class TestWindowsAreNotAccidentallyUniform:
    """NBA.com's stricter window is a deliberate choice, not a copy-paste.

    If someone "tidies" the three handlers into a shared constant, NBA.com's
    7-day bound silently becomes 30 and the registry starts accepting a
    three-week-old official player list as current.
    """

    def test_nba_window_is_stricter_than_the_others(self):
        import re
        windows = {}
        for cls, key in ((NBASourceHandler, 'nba'), (ESPNSourceHandler, 'espn'), (BRSourceHandler, 'br')):
            client = _client(_empty(), _empty())
            cls(client, PROJECT).get_roster_players(2026, TARGET, allow_fallback=True)
            windows[key] = int(re.findall(r'INTERVAL\s+(\d+)\s+DAY', _sql(client, 1))[0])
        assert windows == AUTHORITATIVE_WINDOWS
        assert windows['nba'] < windows['espn']
        assert windows['nba'] < windows['br']
