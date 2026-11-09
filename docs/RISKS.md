# Risks

| # | Risk | Impact | Mitigation | Status |
|---|---|---|---|---|
| R1 | Site changes markup, GraphQL schema or filters | Empty or wrong rows | Raw responses saved; coverage report shows fill-rate drops; parser tested on fixtures | Open |
| R2 | GraphQL query not yet confirmed live (v1 query + `__typename`) | First live run may return errors | Errors are logged; test with `max_auctions=1` first | **Open, check first** |
| R3 | Sold prices hidden without login | Many `sold_price` blanks | Explicit `hidden` status + flag; decision D2 | Accepted |
| R4 | Terms of service / robots | Legal and access risk | Robots obeyed, 1 request at a time, 5 s delay, stop on 403/429, no credentials | Open: read the terms |
| R5 | Older-page layout and price regexes unverified | Wrong or empty 2015 data | Flagged `legacy_layout_unverified`; fixtures are synthetic; verify on saved real pages | **Open** |
| R6 | `f2` filter scope unknown | Not "all Sotheby's" | Documented; override with `-a f2=` | Accepted |
| R7 | `f0` end bound / `from`-`to` semantics unverified | Window off by a day | Compare auctions found with the site's UI for one window | Open |
| R8 | Date text spanning two years or odd formats | Wrong or blank `auction_date` | Year-wrap handled; unreadable gives blank; metadata only | Low |
| R9 | Heuristic medium/size/year miss | Blank columns | Fill rates reported; raw text kept for later extraction | Accepted |
| R10 | Secrets committed by accident | Credential leak | `.env` git-ignored; no credentials needed | Closed by design |

## Added with the blank-field work

| ID | Risk | Likelihood | Impact | Module | How you would notice | Response | Status |
|---|---|---|---|---|---|---|---|
| R37 | A blank field is real (the lot has no such data), but we treat it as a failure | M | L | lot_detail_parser | Many retries with no recovery (`detail_recovered_by_retry` stays 0) | Retry only for broken pages (D14); blanks on normal pages are counted as `absent` | Mitigated |
| R38 | The incomplete-page test (no og:description, no headings) is wrong for the real site | M | M | lot_detail_parser | `detail_retries` very high, or blanks stay high with `detail_page_incomplete` never raised | Check the counts in the run summary; open a saved `lot_*.html` for one flagged row | **Open: not run on the live site** |
| R39 | The inferred or fallback values are wrong (medium picked from the wrong line) | M | M | lot_detail_parser | Flags `medium_inferred`, `*_from_page_text`, `description_partial` | They are flagged so you can filter or review them; spot-check 10 rows before trusting | Open |
| R40 | `repair_details` rewrites a CSV | L | H | repair_details | A bad rewrite | Original kept as `.bak.csv` (first run only); only blank cells are written; `-a limit=20` trial first | Mitigated |
| R41 | Some blanks cannot be filled because the data is not in the page HTML | M | M | parsers | `*_absent` counts stay high | Check one saved page; if the data is loaded by script, a different request is needed | Open |
| R42 | The JSON key names guessed for script-built pages are wrong for the live site | M | M | lot_detail_parser | `*_from_page_json` never appears while `detail_page_incomplete` does | Open one saved `data/raw/repair_details/*.html`, find the description in `__NEXT_DATA__`, add its key to `JSON_KEYS` | **Open** |
| R43 | The glued-word split cuts a name ('McLaren' to 'Mc' + 'Laren') | L | L | lot_detail_parser | Odd `dimensions` values | Used only to find facts; stored description is unchanged | Accepted |
| R44 | Automated logged-in access breaks the site's terms / the account is blocked | M | H | login.py | Login wall, 403/429, account e-mail | Owner's decision D22; slow pace, stop on 403/429; check the terms first | Closed: login step removed (D25) |
| R45 | The logged-in page's real layout differs from the one assumed (result box test id, label text, 'Auction Closed', condition report section) | M | H | result_parser | `login.py check` shows no result box; many `unchanged`/`rejected` in price_log | Trial with `--limit 5`, compare 5 prices by hand with the site; send a saved `data/raw/login/*.html` to fix | Closed: login step removed (D25) |
| R46 | A price from another lot on the page ('You may also like') is taken | L | H | result_parser | price_log price differs from the site | Only the FIRST result box counts; text after 'You may also like' ignored; JSON price for THIS lotId must match when present | Closed: login step removed (D25) |
| R47 | A wrong price passes all checks (e.g. a plausible but wrong number) | L | H | price_validation | Spot-check | Cross-check with the page JSON; `validate_prices.py` also compares the csv with price_log; spot-check 10 sold lots by hand | Open |