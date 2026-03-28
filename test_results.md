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

## Key findings

1. **strict review works** for data accuracy (Scholar 60→100 in Round 2)
2. **relevance check** prevents comparing wrong products (Price Compare 75→100)
3. **agent adaptation** is real strength — PCHome 429 → API fallback, TWSE sub-page redirect → API
4. **verifier calibration matters** — Round 3 initial run showed 1/5, but verifier was too strict on valid behaviors (API fallback, "since 2024" including 2025). After fixing verifier: 5/5.
5. **SDK compatibility** must be pinned (openai + httpx proxies issue)

## All issues resolved

- [x] Agent should scroll + take multiple screenshots to cover all data
- [x] Price comparison should verify product name matches search query
- [x] TWSE task re-tested after SDK fix — PASS
- [x] Weather skill uses county direct URL (CID=63)
- [x] Verifier correctly handles API fallback, date range interpretation
