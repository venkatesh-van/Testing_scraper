# Definition of done

## Verified so far
- [x] Folder layout as specified; `scrapy list` finds the three spiders
- [x] 141 offline tests pass (parsers, pagination, validation, storage, repair, prices, skip-stored)
- [x] Live run (recent, 3 Al Thani sales): 600 lots; after repair description 600/600, every row `parse_quality = detail`
- [x] `repair_details` fills only blank cells (checked: 0 overwrites against the .bak copy)
- [x] Sold-price rules run on every row; `validate_prices.py` exits 1 on any error
- [x] Re-runs skip stored auctions/lots (D26); `max_auctions=1` = first new auction
- [x] Code split into single-purpose modules; `docs/ARCHITECTURE.md` describes every module
- [x] End-to-end run against a local fake site: results → auction → 2 GraphQL pages → CSV + coverage report + raw files
- [x] Re-run resumes without duplicates or a second header
- [x] No credentials needed or stored; `.env` ignored

## Still to do (needs the live site)
- [ ] Read the site's terms; confirm robots.txt allows the paths used
- [x] Live smoke test: GraphQL returns lots without errors (R2) — the 600-lot run worked
- [ ] Rows per auction equal the logged `totalCount`
- [ ] Spot-check 10 random lots against the live pages
- [ ] Check the date window against the site's UI (R7)
- [ ] Save 3 real older lot pages as fixtures; fix the legacy parser against them (R5)
- [ ] Full 30-day run; review `*_coverage.json` fill rates
- [ ] Full August 2015 run; compare with the v1 11-row file
- [x] Decide on sold prices: public pages only, login removed (D25)
- [ ] Re-run from a clean clone; confirm no secrets or data files in git
- [ ] Update this list and `PROJECT_LOG.md` before submitting
