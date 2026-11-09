"""Historical auctions for an explicit date window. Also reads older /ecatalogue/ pages.

    scrapy crawl historical_auctions -a start_date=2015-08-01 -a end_date=2015-08-31
    scrapy crawl historical_auctions -a start_date=... -a end_date=... -a field_retries=4

Lot pages with empty description / provenance / literature / exhibited / catalogue_note are
fetched again up to field_retries times (default 4). A DATA COMPLETENESS table is printed at the end.
"""

import scrapy

from parsers.html_parser import legacy_lot_links, legacy_next_page, parse_legacy_lot
from parsers.legacy_detail import legacy_report
from pipelines.storage import save_raw_response
from spiders.recent_auctions import RecentAuctionsSpider
from utils.field_retry import restore
from utils.logs import log_not_stored
from utils.retries import retry_request


class HistoricalAuctionsSpider(RecentAuctionsSpider):
    name = "historical_auctions"
    source_version = "historical"

    def __init__(self, *args, **kwargs):
        if not (kwargs.get("start_date") and kwargs.get("end_date")):
            raise ValueError("historical_auctions needs -a start_date=YYYY-MM-DD -a end_date=YYYY-MM-DD")
        super().__init__(*args, **kwargs)

    def route_auction(self, url):
        """Older auctions are .html pages; newer ones use the GraphQL path."""
        return self.parse_legacy_auction if url.lower().endswith(".html") else self.parse_auction

    def parse_legacy_auction(self, response, auction):
        save_raw_response(self.raw_dir, response, "html", label="legacy_auction")
        links = legacy_lot_links(response)
        self.logger.info("Legacy auction: %d lot links on %s", len(links), response.url)
        if not links:
            log_not_stored(self, "legacy_auction", "no_lot_links", url=response.url,
                           detail=f"auction '{auction.get('auction_name')}': no /ecatalogue/ lot links on this page")
        for url in links:
            if url not in self.seen:
                self.seen.add(url)
                yield scrapy.Request(url, callback=self.parse_legacy_lot, errback=self.legacy_failed,
                                     cb_kwargs={"auction": auction})

        next_page = legacy_next_page(response)
        if next_page:
            self.logger.info("Legacy auction: next page %s", next_page)
            yield scrapy.Request(next_page, callback=self.parse_legacy_auction,
                                 errback=self.legacy_failed, cb_kwargs={"auction": auction})
        else:
            hints = response.xpath('//a[contains(translate(@href,"PAGE","page"),"page")]/@href').getall()[:5]
            self.logger.info("Legacy auction: no next page after %s (page-like links: %s)", response.url, hints)

    def parse_legacy_lot(self, response, auction):
        """Read an older lot page. A page with no lot text at all is fetched again
        (SOFT_RETRY_TIMES), like recent_auctions.parse_detail. A lot with no
        literature or provenance is normal and is NOT retried.
        """
        save_raw_response(self.raw_dir, response, "html", label="legacy_lot")
        report = legacy_report(response)
        tries = response.meta.get("retry_times", 0)

        if not report.complete:
            retry = retry_request(self, response.request, "lot_page_incomplete")
            if retry is not None:
                self.counts["detail_retries"] += 1
                self.logger.warning("Legacy lot page looks incomplete, trying again: %s", response.url)
                yield retry
                return

        lot = parse_legacy_lot(response, auction, self.source_version)
        restore(lot, response.meta.get("field_saved"))   # keep what earlier tries found
        if not report.complete:
            lot.add_flag("detail_page_incomplete")
            self.counts["detail_incomplete_after_retry"] += 1
            log_not_stored(self, "lot_page", "page_incomplete", url=response.url, lot_id=lot.lot_id,
                           detail=f"lot saved with what the page gave after {tries} retries")
        elif tries:
            self.counts["detail_recovered_by_retry"] += 1
        yield from self.finish_lot(response, lot)

    def legacy_failed(self, failure):
        self.logger.warning("Legacy page failed: %s", failure.request.url)
        log_not_stored(self, "legacy_page", type(failure.value).__name__, url=failure.request.url,
                       detail=repr(failure.value))