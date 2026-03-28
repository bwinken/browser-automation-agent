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

## Key findings

1. **strict review works** for data accuracy (Scholar 60→100)
2. **screenshot coverage** is the main remaining issue (Weather fails because screenshot doesn't show all days)
3. **search relevance** needs improvement (Price Compare picked a case not the product)
4. **SDK compatibility** must be pinned properly (openai + httpx)

## Open issues to fix

- [ ] Agent should scroll + take multiple screenshots to cover all data
- [ ] Price comparison should verify product name matches search query
- [ ] TWSE task needs re-testing after SDK fix
- [ ] Weather skill should use county direct URL (CID=63) to get table data
