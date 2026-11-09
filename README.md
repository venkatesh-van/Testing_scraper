# Sotheby's lots scraper (v2)

Collects lot data (artist, title, estimate, result, medium, size, provenance) from Sotheby's public pages into **one CSV schema**, for recent auctions and for a historical date window.

> Status: unit-tested and run end to end against a local fake site. **Not yet run against the live site.** See `docs/RISKS.md` and `docs/DEFINITION_OF_DONE.md`.

## Setup

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: set SCRAPER_CONTACT (goes in the User-Agent)
pytest                      # 141 offline tests
```

## Run

```sh
# the normal run: last 30 days, with each lot's own page (description, provenance, size, ...)
scrapy crawl recent_auctions -a days=30 -a details=1

# lists only (fast, no description): rows get parse_quality = good
scrapy crawl recent_auctions -a days=30

# re-runs skip what the csv already has: complete auctions are not requested at all (and do not
# count toward max_auctions), and stored lots get no lot-page request. So this gets the first NEW auction:
scrapy crawl recent_auctions -a days=30 -a max_auctions=1 -a details=1
# crawl stored auctions again anyway (stored lots are still not written twice):
scrapy crawl recent_auctions -a days=30 -a details=1 -a recrawl_stored=1

# one auction, with each lot's own page (description, provenance, medium, size)
scrapy crawl recent_auctions -a days=30 -a max_auctions=1 -a details=1

# a fixed historical window (also reads the older /ecatalogue/ lot pages)
scrapy crawl historical_auctions -a start_date=2015-08-01 -a end_date=2015-08-31

# fill blanks in a CSV you already have (writes into that CSV; <name>.bak.csv is the untouched original)
python gap_report.py data/processed/recent_auctions_recent.csv            # where are the blanks?
scrapy crawl repair_details -a source=data/processed/recent_auctions_recent.csv -a offline=1   # no requests
scrapy crawl repair_details -a source=data/processed/recent_auctions_recent.csv                # description, dimensions
scrapy crawl repair_details -a source=data/processed/recent_auctions_recent.csv -a only=description,literature,dimensions -a retries=4
# every filled cell is listed in <name>.repair_log.csv; lots read in full are flagged repair_checked
# and skipped next time (-a recheck=1 to redo them)

# resume after an interruption: just run the same command again
# start a fresh file instead:  -s OVERWRITE=1
```

Output goes to `data/processed/<spider>_<period>.csv` and `..._coverage.json`; exact responses go to `data/raw/` so a parser fix never needs a re-crawl. Re-running skips `lot_id`s already in the CSV.

## Sold prices

Sotheby's shows most sold prices only to logged-in users, and its login page blocks automated
browsers with a human check. This project reads **public pages only** (D25): those lots keep
`lot_status = hidden` and the flag `result_not_public`. Any price that does come from a public page
(GraphQL `ResultVisible`, the lot page's result box, older `/ecatalogue/` pages) passes the rules in
`utils/price_validation.py`, and `sold_price_source` says where it came from:

```sh
python validate_prices.py          # every price checked; exit code 1 if any is wrong
```

## Layout

| Folder | Job |
|---|---|
| `config/` | Scrapy settings and constants (URLs, page size, GraphQL query) |
| `models/` | `AuctionLot`: the one row schema (field order = CSV columns) |
| `parsers/` | Pure functions: HTML/JSON in, `AuctionLot` out. No network. The lot page is split into `page_text`, `lot_sections`, `lot_facts`, `embedded_json`, with `lot_detail_parser` as the entry point |
| `spiders/` | Requests and pagination only: `recent_auctions`, `historical_auctions`, `repair_details` |
| `pipelines/` | `validation.py` (clean, drop, flag, price rules) and `storage.py` (CSV, raw, report) |
| `utils/` | Price rules, what is already stored, results URL, repair helpers, retries, not-stored log |
| `tests/` | Offline tests with fixtures |
| `docs/` | **`ARCHITECTURE.md` (start here)**, decisions, risks, project log, definition of done |

Flow: results page → auction page (`__NEXT_DATA__` gives the auction id) → GraphQL lots, 48 per page → optional lot page.

## Data contract

- One lot = one row; `lot_id` is the key. `lot_number` is text (`12A`).
- `None`/blank means "not available"; **`0` is a real value**.
- `lot_status`: `sold`, `unsold`, `withdrawn`, `upcoming`, `hidden` (closed but the public page shows no result; this is *not* unsold), `unknown` (older pages).
- `sold_price` is the final price including buyer's premium, in `sold_currency`. Only present when the public page shows it.
- `auction_date` is the first day, ISO format. Currencies are never converted.
- `parse_quality` says how far a row got. **`good` does NOT mean the details are there**:
  - `detail`: the lot page was read; description, dimensions, provenance, literature come from it.
  - `good`: only the auction list was read (lot number, id, title complete). The lot page was NOT read, so every page field is blank. Run `repair_details` to fill these rows.
  - `partial`: list only, and the list card itself was incomplete.
  - `legacy`: an older `/ecatalogue/` page (layout unverified).
- `parse_quality` and `data_quality_flags` (e.g. `result_not_public`, `estimate_missing`, `detail_request_failed`) say how far to trust a row.

## Honest limits

- Public pages only; no login. Many sold prices are therefore blank (`result_not_public`).
- Fixtures are **synthetic**, shaped from the old v1 code and CSVs, not captured from the live site. The GraphQL query is the v1 query plus `__typename`; confirm it against the live API on the first real run.
- The older-page (2015) parser and its price regexes come from v1 and are unverified on real pages.
- Medium, size and year are heuristics from description text; expect gaps.
- The `f2` filter is an opaque id copied from a site URL; its scope is unknown, so results are not "all of Sotheby's".
- Check the site's terms and robots.txt before running. For production use, ask for a licensed feed.
