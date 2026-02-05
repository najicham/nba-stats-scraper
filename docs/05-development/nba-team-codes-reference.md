# NBA Team Codes Reference

**Purpose:** Canonical reference for NBA team tricodes (3-letter abbreviations)

All NBA teams use **exactly 3 uppercase letters**: ATL, BOS, BKN, CHA, CHI, CLE, DAL, DEN, DET, GSW, HOU, IND, LAC, LAL, MEM, MIA, MIL, MIN, NOP, NYK, OKC, ORL, PHI, PHX, POR, SAC, SAS, TOR, UTA, WAS

**Game Code Format:** `YYYYMMDD/AWYHOM` (e.g., `20260204/OKCSAS`)

**Common Mistakes:**
- ❌ "OKCSA" (5 chars) → ✅ "OKCSAS" (6 chars)
- ❌ "OKL" from truncating "Oklahoma" → ✅ "OKC"

**Usage:**
```python
from shared.constants import validate_tricode, validate_game_code
validate_game_code("20260204/OKCSAS")  # True
```

```bash
./bin/validate_game_codes.sh "20260204/OKCSAS"
```

See `shared/constants/nba_teams.py` for complete module.
