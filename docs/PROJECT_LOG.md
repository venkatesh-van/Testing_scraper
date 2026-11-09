# Project log

Newest first. Facts only: what was done, what was found, what is next.

## 2026-11-09 (modules + architecture guide)
- Split the lot-page parser into `page_text`, `lot_sections`, `lot_facts`, `embedded_json` (entry point stays `lot_detail_parser`, old imports still work). Moved the results URL to `utils/results_url.py` and the skip logic to `utils/stored_data.py` (`StoredData`). `gap_report.py` now has a `main()` (it crashed on import). Removed the leftover `docs/* copy.md` files (merged earlier).
- Added `docs/ARCHITECTURE.md`: module map, data flow, files written, rules, recipes. Behaviour unchanged; 141 tests.

## 2026-11-09 (skip stored auctions)
- `recent_auctions` (and `historical_auctions`) now skip complete stored auctions before any request (not counted toward max_auctions) and request lot pages only for lots not stored; `-a recrawl_stored=1` turns it off; `-s OVERWRITE=1` starts fresh. Lot totals kept in `<csv>_auction_totals.json` (D26). 137 tests.

## 2026-11-09 (login removed)
- First real login: 'Verify you are human' never completes in the automated browser (bot protection). Decision D25: public pages only.
- Removed `login.py`, `run.py`, `parsers/result_parser.py`, tests for them, Playwright from requirements, `.auth/` handling, and the login-only columns. An existing csv that already has those columns empty gets them dropped on the next crawl (columns WITH data are never dropped).
- Kept: price rules on every row, `validate_prices.py`, strict price-text reading. 133 tests pass.

## 2026-11-09 (one command)
- Added `run.py`: public crawl (details=1 added) -> login.py fetch ONLY if `.auth/sothebys_state.json` exists -> validate_prices.py. No login = public data only, still a success; expired login = public data kept, exit 2 with a message. 154 tests.

## 2026-11-09 (real logged-in page checked)
- From the user's screenshots of a logged-in lot (Lot 100, silver-gilt stag): result box `data-testid="lotBidAmount"` with `<p>Lot Sold</p><p>5,376 EUR</p>`, 'Auction Closed' + 'November 5, 08:25 PM IST', condition section with only a contact note. Saved as `tests/fixtures/logged_in_lot.html` (staff e-mail replaced). The parser reads it: 5,376 EUR, closed 14:55 UTC.
- Fixed from it: a contact-only condition note is not stored (flag `condition_report_on_request`, no staff e-mail kept); 'No reserve' lots get flag `no_reserve` and no `sold_but_reserve_not_met` warning.
- Seen in the network tab: the logged-in price comes from POST /graphql with an `Authorization: Bearer` token (client 'Bidclient'). login.py does not need it copied: the browser session sends it.

## 2026-11-09 (sold prices after login)
- Repair finished: description 600/600, every row `parse_quality = detail`.
- Added: model fields `auction_closed_text`, `auction_closed_at`, `result_label`, `sold_price_source`, `price_checked_at`, `condition_report`; `login.py` (save-session / check / fetch, Playwright, manual login, session in `.auth/`); `parsers/result_parser.py`; `utils/price_validation.py` (one rule set for pipeline, login.py and files); `validate_prices.py` (exit 1 on any error); the storage pipeline adds new columns to an old csv instead of shifting them.
- Price parsing is now strict everywhere (`12.700 EUR` and `1,234.56` are refused); the old loose regex in `parse_result_box` read `1,234.56 USD` as 1,234.
- Tested: 148 tests, including a real-browser run of `login.py fetch` against a fake logged-in site (sale written only when screen = JSON; 3 kinds of bad price refused; another lot's box ignored; run stops when logged out).
- Not done: any run against the live logged-in site (R45). Next: `save-session`, `check`, `fetch --limit 5`, compare the 5 prices by hand.

## 2026-11-09 (parse_quality)
- User note: `parse_quality = good` rows have no description. Checked: all 45 `good` rows have every page field blank; all 555 `detail` rows have a description. `good` = list card complete, lot page not read. Documented (README, model, D21); `gap_report.py` now prints a parse_quality section with the meaning and the repair command, and lists withdrawn lots with blanks too.

## 2026-11-09 (withdrawn lots)
- User report: spreadsheet row 5 (withdrawn ivory cockatoo okimono) has a description on the site, but repair left it blank. Cause: `repair_details` skipped every withdrawn lot (SKIP_STATUSES). Fixed: withdrawn lots are repaired by default; `-a skip_withdrawn=1` to skip.
- The lot in the user's screenshot (German sideboard dishes, row 18) WAS filled in `recent_auctions_recent.csv`; it is blank only in the `.bak.csv`, which is the untouched original by design.
- Added a test built from the real page layout (heading in `<p data-testid="lotDetailsDescription">`, text in `<p>`s). 82 tests pass.

## 2026-11-09 (repair did not fill everything)
- Compared `recent_auctions_recent.bak.csv` (the untouched original, by design) with `recent_auctions_recent.csv`: the repair DID write, into the main csv: 18 lots got description, dimensions, provenance. Exactly 20 lots were touched (18 filled, 2 incomplete), so the run used `limit=20`; the other 39 blank descriptions were never requested.
- Causes found in the data: sizes glued to the next word (`55mmFrench`, 7 lots); literature under 'RELATED LITERATURE' inside the catalogue note (19 lots); inch-only sizes and '______' separators not read.
- Changed: block tags end lines; size regex accepts glued text; inch-only sizes kept (flagged); sub-headings inside note/description fill literature/exhibited/provenance; embedded JSON fallback; headings with ':' and more names. `repair_details`: offline pass, `retries`, `offline`, `recheck`, `repair_checked` flag, `.repair_log.csv`, refuses the .bak as source.
- Offline pass on a copy of the real csv: literature 498 -> 481 blank, dimensions 58 -> 51, 0 overwrites. 81 tests pass.
- Next: run `repair_details` without limit (46 pages), then with `only=description,literature,dimensions` (446 pages, ~25 min). Send one saved page of a lot that stays blank.

## 2026-11-09 (blank fields)
- Recent run, 600 rows (coverage report): description 89.5%, dimensions 87.3%, provenance 86%, medium 15%, artist 24%, year_created 5.7%, literature 17%, exhibited 3.5%, catalogue_note 27%. 46 of the 600 lots are withdrawn.
- The zip had only the coverage JSON, no CSV or saved pages, so the cause of each blank could not be checked here.
- Added: `analyse_detail()` (evidence, fallbacks, reason per blank), a content retry for incomplete lot pages, `repair_details` spider, `gap_report.py`. 65 tests pass; tested against a local fake site (a page incomplete once then complete: recovered on the 2nd try; a page never complete: 3 requests, then flagged).
- Not done: a run on the live site. Next: `python gap_report.py <csv>`, then `repair_details -a limit=20`.

## 2026-11-06
- Rebuilt the v1 scraper in the new modular layout (config, models, parsers, spiders, pipelines, tests, docs).
- Found while porting: the reference example formatted dates as MM/DD/YYYY, but the old v1 URLs are DD/MM/YYYY (D4). It also never requested `__typename`, so its "hidden result" check could not fire (fixed, D5). Its raw-file names collided across GraphQL pages (fixed, D7).
- Tests: 36 passing offline. End-to-end run against a local fake site passed.
- Not done: any run against the live site (see `DEFINITION_OF_DONE.md`).
- Next: read the terms, then one live smoke test with `max_auctions=1`.
