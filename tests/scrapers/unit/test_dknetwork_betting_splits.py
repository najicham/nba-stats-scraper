"""Unit tests for scrapers/external/dknetwork_betting_splits.py

Focus: NBA tricode/matchup parsing (`resolve_team` + `_parse_event`).

WHY THIS EXISTS
---------------
The DK Network scraper was built and live-validated against the *MLB* betting-
splits widget (matchup format `"DET Tigers @ TEX Rangers"`). The NBA matchup
format `"LAL Lakers @ BOS Celtics"` was only *assumed* — never exercised,
because the NBA is off-season with 0 live games. This test makes the FIRST live
game day NOT the first time the NBA parsing path runs.

FIXTURE / FORMAT ASSUMPTION
---------------------------
The HTML structure is taken from the scraper's own module docstring
(server-rendered `div.tb-se` blocks). The NBA matchup string format
(`"<CODE> <Nickname> @ <CODE> <Nickname>"`) is the DOCUMENTED assumption; if the
first live scrape shows DK renders NBA differently (e.g. bare "LA Lakers", or a
city-only prefix), update TEAM_MAP / this fixture accordingly. `resolve_team`'s
resilience does NOT depend on the prefix code — it keys off the team NICKNAME,
which DK always includes.

Path: tests/scrapers/unit/test_dknetwork_betting_splits.py
Created: 2026-07-03
"""

import pytest
from bs4 import BeautifulSoup

from scrapers.external.dknetwork_betting_splits import (
    DKNetworkBettingSplitsScraper,
    resolve_team,
)


# ---------------------------------------------------------------------------
# resolve_team — NBA matchup halves
# ---------------------------------------------------------------------------

class TestResolveTeamNBA:
    """resolve_team must map every NBA matchup-half to the correct tricode."""

    # (input matchup-half, expected tricode). Covers the assumed DK NBA format
    # "<CODE> <Nickname>" plus whitespace, slang nicknames, multi-word cities,
    # and the LA disambiguation (Lakers vs Clippers share the city).
    ALL_30_CODE_NICKNAME = [
        ("ATL Hawks", "ATL"),
        ("BOS Celtics", "BOS"),
        ("BKN Nets", "BKN"),
        ("CHA Hornets", "CHA"),
        ("CHI Bulls", "CHI"),
        ("CLE Cavaliers", "CLE"),
        ("DAL Mavericks", "DAL"),
        ("DEN Nuggets", "DEN"),
        ("DET Pistons", "DET"),
        ("GSW Warriors", "GSW"),
        ("HOU Rockets", "HOU"),
        ("IND Pacers", "IND"),
        ("LAC Clippers", "LAC"),
        ("LAL Lakers", "LAL"),
        ("MEM Grizzlies", "MEM"),
        ("MIA Heat", "MIA"),
        ("MIL Bucks", "MIL"),
        ("MIN Timberwolves", "MIN"),
        ("NOP Pelicans", "NOP"),
        ("NYK Knicks", "NYK"),
        ("OKC Thunder", "OKC"),
        ("ORL Magic", "ORL"),
        ("PHI 76ers", "PHI"),
        ("PHX Suns", "PHX"),
        ("POR Trail Blazers", "POR"),
        ("SAC Kings", "SAC"),
        ("SAS Spurs", "SAS"),
        ("TOR Raptors", "TOR"),
        ("UTA Jazz", "UTA"),
        ("WAS Wizards", "WAS"),
    ]

    @pytest.mark.parametrize("matchup_half,expected", ALL_30_CODE_NICKNAME)
    def test_all_30_teams_code_nickname_format(self, matchup_half, expected):
        assert resolve_team(matchup_half) == expected

    def test_all_30_teams_covered(self):
        """Guard: this table really does exercise all 30 franchises."""
        assert len({t for _, t in self.ALL_30_CODE_NICKNAME}) == 30

    @pytest.mark.parametrize("matchup_half,expected", [
        # split("@") leaves leading/trailing whitespace on each half.
        ("LAL Lakers ", "LAL"),
        (" BOS Celtics", "BOS"),
        (" LAC Clippers ", "LAC"),
    ])
    def test_whitespace_from_matchup_split(self, matchup_half, expected):
        assert resolve_team(matchup_half) == expected

    @pytest.mark.parametrize("matchup_half,expected", [
        # LA city is shared — nickname must disambiguate, not the "LA" token.
        ("LA Lakers", "LAL"),
        ("LA Clippers", "LAC"),
    ])
    def test_la_disambiguation(self, matchup_half, expected):
        assert resolve_team(matchup_half) == expected

    @pytest.mark.parametrize("matchup_half,expected", [
        # Slang nicknames DK/broadcasts sometimes use.
        ("Cavs", "CLE"), ("Mavs", "DAL"), ("Wolves", "MIN"),
        ("Blazers", "POR"), ("Trailblazers", "POR"), ("Sixers", "PHI"),
    ])
    def test_slang_nicknames(self, matchup_half, expected):
        assert resolve_team(matchup_half) == expected

    @pytest.mark.parametrize("matchup_half,expected", [
        # If DK ever spells out the full name with no code prefix.
        ("Golden State Warriors", "GSW"),
        ("New Orleans Pelicans", "NOP"),
        ("Portland Trail Blazers", "POR"),
        ("Oklahoma City Thunder", "OKC"),
    ])
    def test_full_name_no_prefix(self, matchup_half, expected):
        assert resolve_team(matchup_half) == expected

    def test_word_match_not_substring(self):
        """'nets' must not match inside 'hornets' (the docstring guarantee)."""
        assert resolve_team("CHA Hornets") == "CHA"

    def test_bare_tricode_prefix_only(self):
        """If DK ever gives just a code with no nickname, first-token fallback."""
        assert resolve_team("LAL") == "LAL"


# ---------------------------------------------------------------------------
# _parse_event — full HTML → game dict (NBA fixture)
# ---------------------------------------------------------------------------

# Realistic NBA DK Network event block, structure from the scraper docstring.
# One game, Total market, Over/Under rows. The two %-divs per outcome are
# ordered Handle% then Bets% (VSiN-compatible: ticket_pct = Bets, money_pct = Handle).
NBA_EVENT_HTML = """
<div class="tb-se">
  <div class="tb-se-title">
    <h5><a href="/event/29876543/lal-lakers-bos-celtics">LAL Lakers @ BOS Celtics</a></h5>
    <span>3/15, 07:30PM</span>
  </div>
  <div class="tb-market-wrap">
    <div class="tb-se-head"><div>Total</div></div>
    <div class="tb-sodd">
      <div class="tb-slipline">Over 224.5</div>
      <div class="tb-odd-s">-110</div>
      <div>58%</div>
      <div>62%</div>
    </div>
    <div class="tb-sodd">
      <div class="tb-slipline">Under 224.5</div>
      <div class="tb-odd-s">-110</div>
      <div>42%</div>
      <div>38%</div>
    </div>
  </div>
</div>
"""

# Multi-game page with a whole-number line and Unicode-minus odds.
NBA_MULTIGAME_HTML = """
<div class="tb-se">
  <div class="tb-se-title">
    <h5><a href="/event/111/gsw-den">GSW Warriors @ DEN Nuggets</a></h5>
  </div>
  <div class="tb-market-wrap">
    <div class="tb-se-head"><div>Total</div></div>
    <div class="tb-sodd">
      <div class="tb-slipline">Over 231</div>
      <div class="tb-odd-s">−115</div>
      <div>71%</div><div>65%</div>
    </div>
    <div class="tb-sodd">
      <div class="tb-slipline">Under 231</div>
      <div class="tb-odd-s">−105</div>
      <div>29%</div><div>35%</div>
    </div>
  </div>
</div>
<div class="tb-se">
  <div class="tb-se-title">
    <h5><a href="/event/222/phi-mia">PHI 76ers @ MIA Heat</a></h5>
  </div>
  <div class="tb-market-wrap">
    <div class="tb-se-head"><div>Total</div></div>
    <div class="tb-sodd">
      <div class="tb-slipline">Over 210.5</div>
      <div class="tb-odd-s">+100</div>
      <div>50%</div><div>48%</div>
    </div>
    <div class="tb-sodd">
      <div class="tb-slipline">Under 210.5</div>
      <div class="tb-odd-s">-120</div>
      <div>50%</div><div>52%</div>
    </div>
  </div>
</div>
"""


def _bare_scraper():
    """Instance without ScraperBase.__init__ — _parse_event only needs the class."""
    return DKNetworkBettingSplitsScraper.__new__(DKNetworkBettingSplitsScraper)


class TestParseEventNBA:

    def test_single_nba_event(self):
        scraper = _bare_scraper()
        ev = BeautifulSoup(NBA_EVENT_HTML, "html.parser").select_one("div.tb-se")
        game = scraper._parse_event(ev, "2026-03-15")

        assert game is not None
        assert game["away_team"] == "LAL"
        assert game["home_team"] == "BOS"
        assert game["game_date"] == "2026-03-15"
        assert game["dk_event_id"] == "29876543"
        assert game["total_line"] == 224.5
        # ticket = % Bets (2nd div), money = % Handle (1st div)
        assert game["over_ticket_pct"] == 62.0
        assert game["under_ticket_pct"] == 38.0
        assert game["over_money_pct"] == 58.0
        assert game["under_money_pct"] == 42.0
        assert game["over_odds"] == -110.0
        assert game["under_odds"] == -110.0

    def test_ticket_and_money_pct_not_swapped(self):
        """Regression guard: Handle/Bets ordering is the load-bearing assumption."""
        scraper = _bare_scraper()
        ev = BeautifulSoup(NBA_EVENT_HTML, "html.parser").select_one("div.tb-se")
        game = scraper._parse_event(ev, "2026-03-15")
        # Money (handle) 58/42, tickets (bets) 62/38 — must stay distinct & mapped.
        assert game["over_money_pct"] != game["over_ticket_pct"]

    def test_multigame_and_edge_formats(self):
        scraper = _bare_scraper()
        soup = BeautifulSoup(NBA_MULTIGAME_HTML, "html.parser")
        games = [scraper._parse_event(ev, "2026-03-15")
                 for ev in soup.select("div.tb-se")]
        games = [g for g in games if g]

        assert len(games) == 2
        g1, g2 = games
        assert (g1["away_team"], g1["home_team"]) == ("GSW", "DEN")
        assert g1["total_line"] == 231.0            # whole-number line
        assert g1["over_odds"] == -115.0            # Unicode minus normalized
        assert g1["under_odds"] == -105.0
        assert (g2["away_team"], g2["home_team"]) == ("PHI", "MIA")
        assert g2["total_line"] == 210.5

    def test_event_without_matchup_returns_none(self):
        scraper = _bare_scraper()
        html = '<div class="tb-se"><div class="tb-se-title"><h5><a>No At Symbol Here</a></h5></div></div>'
        ev = BeautifulSoup(html, "html.parser").select_one("div.tb-se")
        assert scraper._parse_event(ev, "2026-03-15") is None

    def test_event_without_total_market_returns_none(self):
        scraper = _bare_scraper()
        html = """
        <div class="tb-se">
          <div class="tb-se-title"><h5><a href="/event/9/x">LAL Lakers @ BOS Celtics</a></h5></div>
          <div class="tb-market-wrap">
            <div class="tb-se-head"><div>Moneyline</div></div>
            <div class="tb-sodd"><div class="tb-slipline">LAL</div><div class="tb-odd-s">-150</div><div>55%</div><div>60%</div></div>
          </div>
        </div>
        """
        ev = BeautifulSoup(html, "html.parser").select_one("div.tb-se")
        assert scraper._parse_event(ev, "2026-03-15") is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
