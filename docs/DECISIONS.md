# Decisions

Format: decision, why, what it costs. Newest at the bottom.

**D1. Scrapy, reading the page's embedded JSON and the site's GraphQL lot list.**
Why: structured fields (ids, estimates) beat parsing HTML; Scrapy gives retries, throttling, robots and resume. Cost: depends on an interface the site owns and may change.

**D2. Public pages only; no token or cookie in the code.**
Why: reproducible by anyone, no credential handling, no terms-of-service question about a logged-in session. Cost: sold prices stay hidden for many lots. v1 used a personal token to get them. *Open:* if prices are essential, decide deliberately (and document it) rather than quietly re-adding credentials.

**D3. One dataclass schema (`AuctionLot`) for every source.**
Why: one CSV shape for recent and historical, and the field list is defined in exactly one place. `lot_number` is text because `12A` exists; `0` is kept distinct from missing (v1 turned `0` into blank).

**D4. Dates are written DD/MM/YYYY in the results URL.**
Evidence: v1's URL `from=02/08/2015&to=01/09/2015` pairs with `f0` = 1 Aug 18:30 UTC to 31 Aug 18:30 UTC, i.e. 2 Aug to 1 Sep in IST. The reference example used MM/DD/YYYY, which would silently shift or break the window. `f0` is built from UTC midnights (v1's browser used IST); whether the server reads `from/to` or `f0` is unverified, so both are sent.

**D5. Explicit `lot_status`; a hidden result is not "unsold".**
Why: treating hidden as unsold would corrupt any sold-to-estimate analysis. `__typename` is requested on `sold` so the API's own "hidden" marker can be read.

**D6. Two spiders, one base.** `historical_auctions` extends `recent_auctions` and only adds the older-page branch and required dates. Avoids the duplicated spiders of v1.

**D7. Save every raw response.** File name hashes URL + request body (all GraphQL pages share one URL). Lets parser fixes be re-run without re-crawling.

**D8. Resume by file, not by memory.** On start, `lot_id`s already in the CSV are skipped, so re-running after a crash or on an overlapping window never duplicates rows. Cost: one pass over the CSV at start.

**D9. Medium/size/year stay deterministic heuristics (from v1).** An LLM extraction step is a later, separate stage (batch, with the raw text kept as the source of truth).

**D10. Stop the whole crawl on HTTP 403/429 after retries.** Being blocked is a signal to stop and review, not to push harder.

**D14. Retry when the PAGE looks broken, not whenever a field is blank.**
A lot page counts as incomplete when it has no `og:description`, no "Lot Details" and no section heading (a shell page). Only then is it fetched again (`SOFT_RETRY_TIMES`, default 2). A blank `literature`, `exhibited` or even `dimensions` on a normal page is usually real (the lot has none), and re-fetching would only add requests. Withdrawn lots are not retried.

**D15. Every blank detail field gets a reason.**
`analyse_detail()` reports each blank as `incomplete` (page broken), `parse_failed` (the page shows evidence of the data, for example a size in inches, but we did not extract it: flag `<column>_parse_failed`) or `absent` (no evidence). Fallbacks that use only THIS lot's own text fill what they can and say so: `dimensions_from_page_text`, `medium_from_page_text`, `medium_inferred`, `description_partial`. Nothing is taken from other lots on the page, and `year_created` is never taken from the fallback text (provenance lines contain dates).

**D16. A separate `repair_details` spider fixes a CSV you already have.**
The normal spider skips lots already stored, so re-running it cannot fill old blanks. `repair_details` re-opens only the rows with blanks, writes values into blank cells only (never overwrites), keeps the original as `<name>.bak.csv` (made once) and rewrites the CSV when it closes.

**D17. Fill from text already in the csv before fetching anything.**
Literature written under 'RELATED LITERATURE' inside the catalogue note (19 Al Thani lots) and sizes the old regex missed ('55mmFrench', inch-only sizes) are filled with no request (`literature_from_note`, `dimensions_inches_only`). The note itself is kept whole. Cost: literature then appears twice (note and column); the flag says why.

**D18. Read the page's embedded JSON when its visible text is empty.**
Pages built by script can have the description only in `__NEXT_DATA__` / ld+json. The JSON object that mentions this lot's slug and has the most wanted keys wins (`<column>_from_page_json`). Cost: key names are guessed (description, provenance, literature, exhibition, catalogueNote); confirm on one saved live page (R42).

**D19. A lot page read in full is not fetched again.**
`repair_details` flags it `repair_checked`; blanks left then are what the page holds. Incomplete pages are not flagged, so the next run tries them again. `-a recheck=1` redoes all. `-a retries=N` sets the soft retries for one run.

**D20. Withdrawn lots are repaired too (replaces the withdrawn part of D14/D16).**
Evidence: 42 of the 46 withdrawn lots already have a description from their page, and the user found a withdrawn lot (the ivory cockatoo okimono) whose page shows a description that `repair_details` never fetched. `-a skip_withdrawn=1` brings back the old behaviour. The normal crawl still does not RETRY an incomplete withdrawn page.

**D21. `parse_quality = good` means "list card complete", not "row complete".**
Evidence: all 45 `good` rows in the recent csv have every lot-page field blank (description, dimensions, provenance, literature, ...); all 555 `detail` rows have a description. The values are kept (renaming would break existing csv files), but README, the model and `gap_report.py` now say what each means, and `gap_report.py` gives the repair command for `good`/`partial` rows. `repair_details` turns a row into `detail` when it fills its description.

**D22. Sold prices are read after login, with the user's own account (revises D2).**
Decision by the project owner, 9 Nov 2026: sold prices are essential, and they are shown only after login. How: the user logs in by hand in a real browser (`login.py save-session`); only the session cookies are saved, in `.auth/` (git-ignored, mode 600, left out of `make_zip.py`). The script never sees or stores a password. Pages are read one at a time, 6 s apart (min 3 s), and the run stops on 403/429. Cost and risk: automated access to a logged-in account may break the site's terms of use and could get the account blocked (R44); check the terms before a full run, and prefer a licensed feed for production.

**D23. A sold price is written only when four checks pass, otherwise nothing is written.**
(1) the page's label says sold; (2) the amount text is unambiguous (`12,700 EUR`; never `12.700` or decimals); (3) when the page's own JSON has a price for this lot, it is identical; (4) every rule in `utils/price_validation.py`. A wrong price is worse than a blank one: a blank is visible and can be filled later, a wrong number spreads silently into every analysis. The same rules run on every crawled row (`ValidationPipeline`) and on a whole file (`validate_prices.py`, exit code 1 on any error). `sold_price_source` says where every price came from.

**D24. 'Log in to view results' stops the run.**
It means the session expired. Treating it as "no result" would mark hidden lots unsold; continuing would read nothing for the rest of the run. Withdrawn lots are not read for prices.

**D25. Public pages only, again: the login step is removed (supersedes D22, D23's login parts, D24).**
9 Nov 2026: the first real login showed Sotheby's bot protection ('Verify you are human') blocking the automated browser. Getting past it, or moving a session/bearer token from a normal browser into a script, would defeat a protection the site added on purpose; we do not do that. Removed: `login.py`, `run.py`, `parsers/result_parser.py`, their tests, and the login-only columns (`auction_closed_text`, `auction_closed_at`, `price_checked_at`, `condition_report`). Kept: the price rules (`utils/price_validation.py`, run on every row) and `validate_prices.py`, which guard any price from a public page; `result_label` and `sold_price_source`. Hidden results stay `hidden` + `result_not_public`. For sold prices: a licensed feed (Sotheby's or a market-data provider) or prices looked up by hand.

**D26. Re-runs skip stored auctions before requesting them (extends D8).**
D8 skipped stored lots only when writing, after their pages had been fetched: a re-run on the same csv re-requested everything and `max_auctions=1` always took the first auction in the list, usually one already stored. Now: an auction whose lots are all in the csv is skipped at the results page and does not count toward `max_auctions`; in a partly stored auction only missing lots are requested. "All" = the site's lot total, saved per auction in `<csv>_auction_totals.json` the moment it is known (so a crash cannot lose it). Auctions from csv files made before this, with no saved total, count as complete. Cost: a lot added to a stored auction later is missed unless `-a recrawl_stored=1`.
