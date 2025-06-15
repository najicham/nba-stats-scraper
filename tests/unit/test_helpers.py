import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scrapers.espn_game_boxscore import GetEspnBoxscore


SCRAPER = GetEspnBoxscore()


@pytest.mark.parametrize(
    "src_url,alt_text,expected",
    [
        (
            # src contains /scoreboard/<abbr>.png
            "https://a.espncdn.com/.../scoreboard/ind.png?foo=1",
            "Indiana Pacers",
            "IND",
        ),
        (
            # src is base‑64 ⇒ fallback to map
            "data:image/gif;base64,abcd",
            "Oklahoma City Thunder",
            "OKC",
        ),
        (
            # nothing works ⇒ fall back to alt text with underscores
            "data:image/gif;base64,abcd",
            "Some Expansion Team",
            "SOME_EXPANSION_TEAM",
        ),
    ],
)
def test_extract_team_abbr(src_url, alt_text, expected):
    fake_html = f"""
        <div class="Boxscore__Title">
            <img src="{src_url}" alt="{alt_text}">
        </div>
    """
    soup = BeautifulSoup(fake_html, "html.parser")
    assert SCRAPER._extract_team_abbr(soup) == expected

