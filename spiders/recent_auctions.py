"""Recent auctions: results page -> auction page -> GraphQL lots (-> optional lot page).

    scrapy crawl recent_auctions -a days=30
    scrapy crawl recent_auctions -a days=30 -a details=1 -a max_auctions=3
    scrapy crawl recent_auctions -a days=90 -a f2=none     # no f2 filter
    scrapy crawl recent_auctions -a days=90 -a f2=auto     # discover and crawl every f2 value
    scrapy crawl recent_auctions -a days=30 -a recrawl_stored=1   # also auctions already in the csv
    scrapy crawl recent_auctions -a days=30 -a details=1 -a field_retries=4   # retry pages with empty sections

Empty sections: when a lot page leaves description / provenance / literature / exhibited /
catalogue_note empty, the page is fetched again up to `field_retries` times (default 4,
0 = off; choose the columns with -a retry_fields=a,b,c). Values found on any try are kept.
At the end a DATA COMPLETENESS table is printed from the csv (after validation).

Already stored = in the csv this run writes to (data/processed/<spider>_<source_version>.csv):
  * an auction whose lots are ALL in the csv is skipped before any request, and does not count
    toward max_auctions (so max_auctions=1 means "the first auction I do not have yet")
  * in a partly stored auction (a crash mid-way), only the missing lots are requested
  * "all" is checked against the lot total the site gave when the auction was first crawled, kept
    in <csv name>_auction_totals.json. An auction in an older csv with no recorded total counts as
    complete; use -a recrawl_stored=1 if you know one is not.
  * -s OVERWRITE=1 starts a fresh csv, so nothing counts as stored.
"""

import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.spidermiddlewares.httperror import HttpError

from config.settings import DEFAULT_F2, GRAPHQL_URL, LOT_QUERY, PAGE_SIZE, RAW_DIR
from parsers.graphql_parser import find_auction_id, find_lot_cards, parse_card, parse_connection
from parsers.html_parser import find_filter_values, parse_auction_cards, results_next_page
from parsers.lot_detail_parser import analyse_detail, merge_detail
from pipelines.storage import save_raw_response
from utils.completeness import print_csv_completeness
from utils.field_retry import (DEFAULT_FIELD_RETRIES, RETRY_FIELDS, blank_fields, field_retry_request,
                               restore, snapshot)
from utils.logs import log_not_stored
from utils.results_url import build_results_url
from utils.retries import retry_request
from utils.stored_data import StoredData

BLOCKED_STATUSES = (403, 429)


class RecentAuctionsSpider(scrapy.Spider):
    name = "recent_auctions"
    allowed_domains = ["www.sothebys.com", "clientapi.prod.sothelabs.com"]
    source_version = "recent"

    def __init__(self, days=30, start_date=None, end_date=None, f2=DEFAULT_F2, results_url=None,
                 details="0", max_auctions=None, source_version=None, raw_dir=None, recrawl_stored="0",
                 processed_dir=None, field_retries=None, retry_fields=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.end_date = date.fromisoformat(end_date) if end_date else date.today()
        self.start_date = (date.fromisoformat(start_date) if start_date
                           else self.end_date - timedelta(days=int(days)))
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if source_version:
            self.source_version = source_version
        self.details = str(details).lower() in ("1", "true", "yes")
        self.max_auctions = int(max_auctions) if max_auctions else None
        self.raw_dir = Path(raw_dir) if raw_dir else RAW_DIR / self.name
        self.recrawl_stored = str(recrawl_stored).lower() in ("1", "true", "yes")
        self.processed_dir = Path(processed_dir) if processed_dir else None
        self._stored = None          # loaded on first use (see stored())
        self.field_retries = (int(field_retries) if field_retries not in (None, "")
                              else DEFAULT_FIELD_RETRIES)
        self.retry_fields = (tuple(name.strip() for name in retry_fields.split(",") if name.strip())
                             if retry_fields else RETRY_FIELDS)

        f2_text = str(f2 or "").strip().lower()
        self.auto_f2 = f2_text == "auto"       # -a f2=auto -> discover the values from the page
        self.f2_discovered = False
        if self.auto_f2 or f2_text in ("", "none", "all"):
            f2 = None                          # first request has no f2 filter
        self.start_urls = [results_url or build_results_url(self.start_date, self.end_date, f2)]

        self.seen = set()            # lot ids / lot urls already requested
        self.auctions_seen = set()   # auction urls already requested
        self.counts = Counter()      # run summary, logged when the spider closes

    # ---- what the csv already has (utils/stored_data.py does the work)
    def csv_path(self):
        """The csv this run writes to: data/processed/<spider>_<source_version>.csv"""
        folder = self.processed_dir
        if folder is None:
            crawler = getattr(self, "crawler", None)
            if crawler is None:
                return None              # unit tests without a crawler: nothing counts as stored
            folder = Path(crawler.settings.get("PROCESSED_DIR"))
        return folder / f"{self.name}_{self.source_version}.csv"

    def stored(self):
        """StoredData for this run's csv, read once."""
        if self._stored is None:
            crawler = getattr(self, "crawler", None)
            fresh = bool(crawler and crawler.settings.getbool("OVERWRITE"))
            self._stored = StoredData(self.csv_path(), enabled=not (fresh or self.recrawl_stored))
        return self._stored

    def limit_reached(self):
        """True once max_auctions auctions have been requested (the limit is for the whole run)."""
        return bool(self.max_auctions) and len(self.auctions_seen) >= self.max_auctions

    # ---- helper: page loaded but had no usable data
    def soft_failure(self, response, stage, reason, detail=None):
        """Retry the request; when out of tries, record WHY nothing was stored.

        Use as:  yield from self.soft_failure(...)
        """
        retry = retry_request(self, response.request, reason)
        if retry is not None:
            self.counts["soft_retries"] += 1
            self.logger.warning("Retrying (%s): %s", reason, response.url)
            return [retry]
        self.counts[f"lost_{reason}"] += 1
        log_not_stored(self, stage, reason, url=response.url, detail=detail)
        return []

    # ---- step 1: results page lists the auctions (and may have more pages)
    def parse(self, response):
        save_raw_response(self.raw_dir, response, "html", label="results")
        self.counts["results_pages"] += 1
        auctions = parse_auction_cards(response)
        self.logger.info("Results page: %d auctions (%s)", len(auctions), response.url)
        if not auctions:
            self.logger.warning("No auction cards found. Open the saved raw results_*.html: "
                                "if the auctions are not in it, the list is loaded by JavaScript.")
            log_not_stored(self, "results_page", "no_auction_cards", url=response.url,
                           detail="no auctions in this page: wrong dates/filter, or list loaded by JavaScript")

        # queue this page's auctions (stop at max_auctions)
        for auction in auctions:
            if self.limit_reached():
                break
            if auction["auction_url"] in self.auctions_seen:
                continue
            if not self.recrawl_stored and self.stored().auction_complete(auction["auction_url"]):
                self.counts["auctions_skipped_already_stored"] += 1
                self.logger.info("Already stored, skipped: %s", auction.get("auction_name") or auction["auction_url"])
                continue                     # does not count toward max_auctions
            self.auctions_seen.add(auction["auction_url"])
            self.counts["auctions_found"] += 1
            yield scrapy.Request(auction["auction_url"], callback=self.route_auction(auction["auction_url"]),
                                 errback=self.request_failed, cb_kwargs={"auction": auction})

        # f2=auto: read every f2 value on the first page, then crawl each one
        if self.auto_f2 and not self.f2_discovered:
            self.f2_discovered = True
            if self.limit_reached():
                self.logger.info("max_auctions reached: not crawling the f2 filter pages")
            else:
                filters = find_filter_values(response)
                self.logger.info("Found %d f2 filter values", len(filters))
                for value in filters:
                    yield scrapy.Request(build_results_url(self.start_date, self.end_date, value),
                                         callback=self.parse, errback=self.request_failed)

        if not self.limit_reached():
            next_page = results_next_page(response)
            if next_page:
                self.logger.info("Results next page: %s", next_page)
                yield scrapy.Request(next_page, callback=self.parse, errback=self.request_failed)

    def route_auction(self, url):
        """Which callback handles this auction page (the historical spider adds a second kind)."""
        return self.parse_auction

    # ---- step 2: auction page -> auction id
    def parse_auction(self, response, auction):
        save_raw_response(self.raw_dir, response, "html", label="auction")
        name = auction.get("auction_name")
        raw = response.css("script#__NEXT_DATA__::text").get()
        if not raw:
            self.logger.warning("No __NEXT_DATA__ on %s", response.url)
            yield from self.soft_failure(response, "auction_page", "no_next_data",
                                         detail=f"auction '{name}': page has no __NEXT_DATA__ (blocked or layout changed)")
            return
        data = json.loads(raw)
        first = next(find_lot_cards(data), None)
        auction_id = ((first or {}).get("auction") or {}).get("auctionId")
        if not auction_id:
            # no lot cards in the page: look for the auction id anywhere in the data
            auction_id = find_auction_id(data)
            if auction_id:
                self.logger.info("No lot cards in the page, but found auction id %s: asking GraphQL anyway", auction_id)
        if not auction_id:
            page_props = (data.get("props") or {}).get("pageProps") or {}
            self.logger.warning("No lot cards / auction id on %s", response.url)
            self.counts["auctions_without_lots"] += 1
            log_not_stored(self, "auction_page", "no_lot_cards", url=response.url,
                           detail=f"auction '{name}': no lots and no auction id. pageProps keys: {list(page_props)[:12]}")
            return
        self.counts["auctions_with_lots"] += 1
        yield self.graphql_request(auction_id, 0, auction)

    # ---- step 3: all lots through GraphQL, PAGE_SIZE at a time
    def graphql_request(self, auction_id, offset, auction):
        payload = {
            "operationName": "LotCardsFilterByPaginated",
            "query": LOT_QUERY,
            "variables": {"id": auction_id, "filter": "ALL", "language": "ENGLISH",
                          "limit": PAGE_SIZE, "offset": offset},
        }
        return scrapy.Request(
            GRAPHQL_URL, method="POST", body=json.dumps(payload), dont_filter=True,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "Origin": "https://www.sothebys.com", "Referer": "https://www.sothebys.com/"},
            callback=self.parse_graphql, errback=self.request_failed,
            cb_kwargs={"auction_id": auction_id, "offset": offset, "auction": auction},
        )

    def parse_graphql(self, response, auction_id, offset, auction):
        save_raw_response(self.raw_dir, response, "json", label=f"{auction_id}_offset{offset}")
        where = f"auction={auction_id} offset={offset}"
        try:
            page = parse_connection(response.json())
        except ValueError:
            self.logger.error("Invalid GraphQL JSON: auction=%s offset=%d", auction_id, offset)
            yield from self.soft_failure(response, "graphql", "invalid_json", detail=where)
            return
        if page["errors"]:
            self.logger.error("GraphQL errors: %s", page["errors"])
            if not page["cards"]:
                yield from self.soft_failure(response, "graphql", "graphql_errors",
                                             detail=f"{where} errors={page['errors']}")
                return
        cards, total = page["cards"], page["total"]
        self.logger.info("auction=%s offset=%d lots=%d total=%s", auction_id, offset, len(cards), total)
        if offset == 0:
            self.stored().record_total(auction.get("auction_url"), total)

        if offset == 0 and not cards and not page["errors"]:
            self.counts["auctions_graphql_empty"] += 1
            log_not_stored(self, "graphql", "auction_has_no_lots", url=auction.get("auction_url"),
                           detail=f"{where} totalCount={total}: the site itself returns no lots for this auction")
            return

        for card in cards:
            lot = parse_card(card, auction, self.source_version)
            if lot.lot_id in self.seen:
                self.counts["lots_duplicate"] += 1
                continue
            if not self.recrawl_stored and self.stored().has_lot(lot.lot_id):
                self.counts["lots_skipped_already_stored"] += 1   # no lot-page request for it
                self.seen.add(lot.lot_id)
                continue
            self.counts["lots_found"] += 1
            self.seen.add(lot.lot_id)
            if self.details and lot.lot_url:
                yield scrapy.Request(lot.lot_url, callback=self.parse_detail,
                                     errback=self.detail_failed, cb_kwargs={"lot": lot})
            else:
                yield lot

        has_next = page["has_next"] if page["has_next"] is not None else len(cards) >= PAGE_SIZE
        if has_next and cards:
            yield self.graphql_request(auction_id, offset + PAGE_SIZE, auction)
        elif total is not None and offset + len(cards) < total:
            self.logger.warning("Pagination ended at %d of %d lots (auction=%s)",
                                offset + len(cards), total, auction_id)
            log_not_stored(self, "pagination", "ended_early", url=response.url,
                           detail=f"auction={auction_id}: got {offset + len(cards)} of {total} lots")

    # ---- step 4 (optional): the lot's own page
    def parse_detail(self, response, lot):
        """Read the lot page. A page that looks incomplete is fetched again (SOFT_RETRY_TIMES).

        Retry only when the PAGE looks broken (no description markers at all), not whenever a
        field is blank: a lot with no literature is normal, and re-fetching it changes nothing.
        Withdrawn lots are not retried (their pages hold little).
        """
        save_raw_response(self.raw_dir, response, "html", label="lot")
        report = analyse_detail(response)
        tries = response.meta.get("retry_times", 0)

        if not report.complete and lot.lot_status != "withdrawn":
            retry = retry_request(self, response.request, "lot_page_incomplete")
            if retry is not None:
                self.counts["detail_retries"] += 1
                self.logger.warning("Lot page looks incomplete, trying again: %s", response.url)
                yield retry
                return
            lot.add_flag("detail_page_incomplete")
            self.counts["detail_incomplete_after_retry"] += 1
            log_not_stored(self, "lot_page", "page_incomplete", url=response.url, lot_id=lot.lot_id,
                           detail=f"lot saved with what the page gave after {tries} retries")
        elif report.complete and tries:
            self.counts["detail_recovered_by_retry"] += 1

        merge_detail(lot, response, report)
        restore(lot, response.meta.get("field_saved"))   # keep what earlier tries found
        if not response.meta.get("field_tries"):
            for column, kind in report.gaps.items():
                self.counts[f"gap_{column}_{kind}"] += 1       # shown in the run summary
        for flag in report.flags:
            self.counts[f"fixed_or_flagged_{flag}"] += 1
        yield from self.finish_lot(response, lot)

    # ---- shared by recent + historical: retry a lot page while sections are empty
    def finish_lot(self, response, lot):
        """Yield a retry of this page if sections are still empty, else the lot.

        Use as:  yield from self.finish_lot(response, lot)
        """
        missing = blank_fields(lot, self.retry_fields)
        tries = response.meta.get("field_tries", 0)
        first_missing = response.meta.get("field_first_missing", missing)
        page_broken = "detail_page_incomplete" in (lot.data_quality_flags or "").split(";")
        can_retry = getattr(self, "crawler", None) is not None   # unit tests: never retry
        if (missing and can_retry and not page_broken and tries < self.field_retries
                and lot.lot_status != "withdrawn"):
            self.counts["field_retries"] += 1
            self.logger.info("Lot %s: empty %s, fetching the page again (%d/%d)",
                             lot.lot_id or lot.lot_url, ",".join(missing), tries + 1, self.field_retries)
            yield field_retry_request(response.request, tries, snapshot(lot, self.retry_fields), first_missing)
            return
        for name in first_missing:
            if name not in missing:
                self.counts[f"filled_by_retry_{name}"] += 1     # empty at first, found on a retry
        for name in missing:
            self.counts[f"absent_{name}"] += 1                  # still empty after every try
        yield lot

    def detail_failed(self, failure):
        """Never lose a lot because its page failed."""
        lot = failure.request.cb_kwargs["lot"]
        lot.add_flag("detail_request_failed")
        self.logger.warning("Lot page failed: %s", failure.request.url)
        log_not_stored(self, "lot_page", "detail_request_failed", url=failure.request.url, lot_id=lot.lot_id,
                       detail=f"lot saved WITHOUT its page data: {failure.value!r}")
        yield lot

    def request_failed(self, failure):
        """Record why a request is lost. Stop the whole crawl if the site blocks or rate-limits us."""
        url = failure.request.url
        if failure.check(HttpError):
            status = failure.value.response.status
            log_not_stored(self, "request_failed", f"http_{status}", url=url,
                           detail=f"after {failure.request.meta.get('retry_times', 0)} retries")
            if status in BLOCKED_STATUSES:
                raise CloseSpider(f"access_denied_{status}")
        else:
            log_not_stored(self, "request_failed", type(failure.value).__name__, url=url,
                           detail=repr(failure.value))
        self.logger.error("Request failed: %s (%r)", url, failure.value)

    def closed(self, reason):
        """Scrapy calls this at the end: run summary + completeness of the csv (after validation)."""
        self.logger.info("Run summary (%s): %s", reason, dict(self.counts))
        absent = {key[len("absent_"):]: value for key, value in self.counts.items() if key.startswith("absent_")}
        try:
            print_csv_completeness(self.csv_path(), absent)
        except Exception as error:          # the table must never break the end of a crawl
            self.logger.warning("Could not print the completeness table: %r", error)