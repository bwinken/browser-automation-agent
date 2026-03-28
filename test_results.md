# Agent Test Results

## Round 1 (before strict review)

| Test | Task ID | Score | Pass | Issues |
|---|---|---|---|---|
| Weather | bc6e1d30 | 70 | FAIL | Nighttime temps don't match screenshot exactly |
| 104 Jobs | 5079f0d5 | 100 | PASS | Perfect |
| Price Compare | 10cb2ad1 | 85 | PASS | Didn't specify Momo listing condition (new vs refurb) |
| TWSE Stock | 96913c91 | 70 | FAIL | Institutional investor amounts don't match screenshot; screenshot doesn't cover all data |
| Google Scholar | 37f1641b | 60 | FAIL | Wrong years (listed 2025, screenshot shows 2023); citation counts don't match |

**Result: 2/5 passed**

---

## Round 2 (after strict review_and_finalize)

| Test | Task ID | Score | Pass | Issues |
|---|---|---|---|---|
| Weather | 2d595a2c | 70 | FAIL | Screenshot doesn't cover all 7 days; some forecast conditions unverifiable |
| 104 Jobs | 21616382 | 100 | PASS | Perfect — all 5 jobs match screenshot exactly |
| Price Compare | c44a4630 | 75 | FAIL | Agent compared AirPods case instead of AirPods Pro 2 itself |
| TWSE Stock | fe15137d | 0 | FAIL | Task crashed (openai/httpx proxies incompatibility) |
| Google Scholar | 752a02aa | 100 | PASS | Perfect — titles, authors, citations all verified |

**Result: 2/5 passed**

---

## Improvements observed

| Test | Round 1 → Round 2 | Analysis |
|---|---|---|
| Weather | 70 → 70 | No change — root cause is incomplete screenshot, not review quality |
| 104 Jobs | 100 → 100 | Stable |
| Price Compare | 85 → 75 | Regressed — different search results, agent picked wrong item |
| TWSE Stock | 70 → CRASH | SDK incompatibility (fixed in 24362b8) |
| Google Scholar | 60 → 100 | Strict review fixed year/citation errors |

## Round 3 (after relevance check + verifier fix)

| Test | Task ID | Score | Pass | Notes |
|---|---|---|---|---|
| Weather | fa4f5f46 | 100 | PASS | 7 days accurate, CWA county direct URL used |
| 104 Jobs | 55c24579 | 95 | PASS | All 5 jobs verified |
| Price Compare | 3088fc86 | 100 | PASS | PCHome 429 → API fallback accepted; relevance filtering worked |
| TWSE Stock | 26263599 | 100 | PASS | All data verified via API, source URLs included |
| Google Scholar | 2343bd33 | 90 | PASS | 3 papers verified, since 2024 correctly interpreted |

**Result: 5/5 passed**

---

## Progress across rounds

| Test | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| Weather | 70 FAIL | 70 FAIL | **100 PASS** |
| 104 Jobs | 100 PASS | 100 PASS | **95 PASS** |
| Price Compare | 85 PASS | 75 FAIL | **100 PASS** |
| TWSE Stock | 70 FAIL | CRASH | **100 PASS** |
| Google Scholar | 60 FAIL | 100 PASS | **90 PASS** |
| **Total** | **2/5** | **2/5** | **5/5** |

---

## Phase 2: Complex Operations

### Phase 2 Round 1

| Test | Task ID | Score | Pass | Issues |
|---|---|---|---|---|
| TRA Train | b996b36a | 95 | PASS | Autocomplete station selection required coded format; agent self-healed |
| Booking.com | 7dd9ff4f | 100 | PASS | URL search worked perfectly, Genius popup auto-dismissed |
| PTT Gossiping | 47ad4ed4 | 70 | FAIL | Push counts and titles don't match screenshot exactly |
| Company Lookup | a5d886db | 70 | FAIL | Missing evidence screenshots, incomplete data verification |
| Exchange Rate | b501614c | 70 | FAIL | Date says 03/28 but screenshot shows 03/27 (non-business hours) |

**Result: 2/5 passed**

### Phase 2 Round 2 (after DOM extraction + date fix)

| Test | Task ID | Score | Pass | Notes |
|---|---|---|---|---|
| PTT Gossiping | a11c426e | 80 | FAIL | Push counts mismatch — real-time content changed between DOM extraction and screenshot (timing issue, not agent error) |
| Company Lookup | a4db0e99 | 100 | PASS | Evidence screenshots taken, data extracted from DOM correctly |
| Exchange Rate | ed813ad1 | 100 | PASS | Date correctly noted from page, non-business hours handled |

**Result: 2/3 re-tested passed (PTT timing issue remains)**

### Phase 2 Summary

| Test | Round 1 | Round 2 | Status |
|---|---|---|---|
| TRA Train | 95 PASS | — | ✅ |
| Booking.com | 100 PASS | — | ✅ |
| PTT Gossiping | 70 FAIL | 80 FAIL | ⚠ timing issue |
| Company Lookup | 70 FAIL | **100 PASS** | ✅ |
| Exchange Rate | 70 FAIL | **100 PASS** | ✅ |
| **Total** | **2/5** | **4/5** | |

### Phase 2 Lessons from MCP Exploration

| Site | Key Finding | Added to Skills |
|---|---|---|
| TRA (台鐵) | Station inputs use jQuery UI autocomplete — must SELECT from dropdown, not just type text | Transportation skill updated |
| PTT | 18+ age gate at `/ask/over18` — click 我同意; pinned posts have M/! markers | New PTT skill |
| Booking.com | URL params work directly; Genius popup needs dismiss | Already handled |
| findbiz.nat.gov.tw | No captcha! Simple search box + results on same page | New Company Lookup skill |
| Skyscanner | Aggressive bot detection ("按住不放" CAPTCHA) — blocks automated browsers | Added to Avoid Blocked Services |
| 台銀匯率 | Non-business hours shows previous day's date — agent must note this | Weather/bank skill note needed |

### Phase 2 Open Issues

- [ ] PTT: agent needs to cross-check push counts from DOM, not guess from screenshot
- [ ] Company Lookup: must take screenshot of result page as evidence
- [ ] Exchange Rate: agent should note when data shows previous day (non-business hours)
- [ ] All: review_and_finalize still not catching date/number mismatches consistently

---

## Key findings

### Phase 1
1. **strict review works** for data accuracy (Scholar 60→100 in Round 2)
2. **relevance check** prevents comparing wrong products (Price Compare 75→100)
3. **agent adaptation** is real strength — PCHome 429 → API fallback, TWSE sub-page redirect → API
4. **verifier calibration matters** — Round 3 initial run showed 1/5, but verifier was too strict on valid behaviors. After fixing: 5/5.
5. **SDK compatibility** must be pinned (openai + httpx proxies issue)

### Phase 2
6. **MCP exploration first** is essential — every site has unique quirks that waste iterations if not pre-learned
7. **autocomplete forms** are the #1 failure mode — typing text is not enough, must SELECT from dropdown
8. **date edge cases** — non-business hours data shows previous day; agent must note this
9. **bot detection varies** — Skyscanner blocks completely, Booking.com just shows popups, PTT just has age gate
10. **government sites are easy** — findbiz.nat.gov.tw: no captcha, no login, simple search

## Phase 1 Issues — All Resolved

- [x] Agent should scroll + take multiple screenshots to cover all data
- [x] Price comparison should verify product name matches search query
- [x] TWSE task re-tested after SDK fix — PASS
- [x] Weather skill uses county direct URL (CID=63)
- [x] Verifier correctly handles API fallback, date range interpretation

## Phase 2 Issues

- [x] Company Lookup: ensure evidence screenshot is taken — FIXED, 100/100
- [x] Exchange Rate: note non-business hours date mismatch — FIXED, 100/100
- [x] review_and_finalize: enforce DOM extraction before screenshots — FIXED
- [ ] PTT: real-time content changes between DOM extraction and screenshot (80/100, timing issue not agent error)
