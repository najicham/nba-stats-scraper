# REMINDER: Retry Failed PBP Games When IP Block Clears

**Priority:** 🟡 MEDIUM
**Type:** Data Completeness
**Blocker:** External (AWS CloudFront IP ban)
**Check Frequency:** Every 6-12 hours

---

## What is CloudFront?

**AWS CloudFront** is Amazon's Content Delivery Network (CDN) that sits in front of cdn.nba.com:

```
Your Script → Internet → CloudFront (AWS) → Origin (S3/NBA servers) → Data
                             ↑
                        BLOCKING HERE
                        (403 Forbidden)
```

**Current Issue:**
- CloudFront detected rapid requests as potential abuse
- Blocked our IP address (and our proxy IPs)
- Returns: `403 Forbidden` with `x-amz-*` headers (AWS signature)
- Block duration: Unknown (48+ hours so far, typically 24-72 hours)

**Why CloudFront?**
- NBA.com uses CloudFront for global content delivery
- CloudFront has aggressive rate limiting to prevent DDoS/scraping
- Once blocked, must wait for automatic expiration (no manual override)

---

## Quick Status Check

Run this command to check if the block has cleared:

```bash
curl -I "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0022500651.json" 2>&1 | head -1
```

**Still Blocked (don't retry yet):**
```
HTTP/2 403
```

**Block Cleared (ready to retry!):**
```
HTTP/2 200
```

---

## When Block Clears: Run These Commands

### Step 1: Verify Block is Cleared
```bash
curl -I "https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0022500651.json" | head -1
# Should show: HTTP/2 200
```

### Step 2: Retry First Game
```bash
cd ~/code/nba-stats-scraper
python3 scripts/backfill_pbp_20260125.py --game-id 0022500651
```

**Expected output:**
```
✅ 0022500651 (DEN @ MEM): ~600 events
```

### Step 3: Wait 18-20 Seconds
```bash
sleep 20
```

### Step 4: Retry Second Game
```bash
python3 scripts/backfill_pbp_20260125.py --game-id 0022500652
```

**Expected output:**
```
✅ 0022500652 (DAL @ MIL): ~600 events
```

### Step 5: Verify Both Games in GCS
```bash
# Should now show 8 directories (currently shows 6)
gsutil ls gs://nba-scraped-data/nba-com/play-by-play/2026-01-25/ | wc -l

# Verify specific games exist
gsutil ls gs://nba-scraped-data/nba-com/play-by-play/2026-01-25/game-0022500651/
gsutil ls gs://nba-scraped-data/nba-com/play-by-play/2026-01-25/game-0022500652/
```

### Step 6: Update Documentation
```bash
# Mark task as complete in:
# - docs/08-projects/current/2026-01-25-incident-remediation/STATUS.md
# - docs/08-projects/current/2026-01-25-incident-remediation/COMPLETION-CHECKLIST.md
# - docs/08-projects/current/MASTER-PROJECT-TRACKER.md

# Create completion commit
git add docs/
git commit -m "docs: Complete 2026-01-25 incident remediation - all 8 games in GCS"
```

---

## Alternative: Run from GCP Cloud Shell

If local IP remains blocked for 72+ hours, use GCP Cloud Shell (different IP):

```bash
# 1. Open Cloud Shell
gcloud cloud-shell ssh

# 2. Navigate to project
cd /workspace/nba-stats-scraper

# 3. Pull latest code
git pull origin main

# 4. Run backfill (proxies enabled automatically)
python3 scripts/backfill_pbp_20260125.py --game-id 0022500651
sleep 20
python3 scripts/backfill_pbp_20260125.py --game-id 0022500652

# 5. Verify in GCS (should now show 8 games)
gsutil ls gs://nba-scraped-data/nba-com/play-by-play/2026-01-25/ | wc -l
```

---

## Games to Retry

| Game ID | Matchup | Status | Expected Events |
|---------|---------|--------|-----------------|
| 0022500651 | DEN @ MEM | ❌ Missing | ~600 |
| 0022500652 | DAL @ MIL | ❌ Missing | ~600 |

**Already Complete (6/8):**
- 0022500650 (SAC @ DET) - 588 events ✅
- 0022500644 (GSW @ MIN) - 608 events ✅
- 0022500653 (TOR @ OKC) - 565 events ✅
- 0022500654 (NOP @ SAS) - 607 events ✅
- 0022500655 (MIA @ PHX) - 603 events ✅
- 0022500656 (BKN @ LAC) - 546 events ✅

---

## Success Criteria

- [ ] Both games successfully downloaded
- [ ] Event counts reasonable (400-700 events each)
- [ ] Both games verified in GCS
- [ ] Total games in GCS: 8/8 (100%)
- [ ] Documentation updated
- [ ] Project marked as complete

---

## Timeline

- **2026-01-26 05:30 UTC:** IP blocked
- **2026-01-27:** Proxy enabled, retry attempted (still blocked)
- **Next Check:** Every 6-12 hours until block clears
- **Expected Resolution:** Within 24-72 hours of original block

---

## Technical Details

**Why Both Direct and Proxy IPs Are Blocked:**

CloudFront appears to be using multiple blocking mechanisms:
1. **IP-based blocking** - Blocks individual IPs that make rapid requests
2. **Possible fingerprinting** - May use additional signals beyond IP (headers, TLS, etc.)
3. **Proxy detection** - CloudFront may detect and block known proxy IPs

**Why We Need to Wait:**
- No way to manually remove CloudFront IP bans
- Blocks typically expire after 24-72 hours
- Attempting retries while blocked may extend the ban

**Why Proxy is Still Valuable:**
- Prevents future IP blocks during normal operations
- Distributes requests across multiple IPs
- Once this specific ban expires, proxies will work

---

**Created:** 2026-01-27
**Owner:** Data Engineering Team
**Check Every:** 6-12 hours
**Priority:** Medium (preventive measure complete, data 75% available)
