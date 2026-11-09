"""Scrapy settings plus the project's constants, in one place."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CONTACT = os.getenv("SCRAPER_CONTACT", "no-contact-set")

# ---------------------------------------------------------------- Scrapy
BOT_NAME = "sothebys_scraper"
SPIDER_MODULES = ["spiders"]
NEWSPIDER_MODULE = "spiders"

USER_AGENT = f"sothebys_scraper/2.0 (educational data exercise; {CONTACT})"
ROBOTSTXT_OBEY = True
COOKIES_ENABLED = False  # public pages only: no login, no session

# # Politeness: one request at a time, 5 s apart, AutoThrottle may slow it more.
# CONCURRENT_REQUESTS_PER_DOMAIN = 1
# DOWNLOAD_DELAY = 5
# AUTOTHROTTLE_ENABLED = True
# AUTOTHROTTLE_START_DELAY = 5
# AUTOTHROTTLE_MAX_DELAY = 120
# AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# Politeness: a little faster than before, still gentle.
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 3                      # was 5. Autothrottle never goes below this.
DOWNLOAD_DELAY_JITTER = 0.5             # waits 0.5x-1.5x of the delay, not a fixed beat
                                        # (Scrapy 2.20 renamed RANDOMIZE_DOWNLOAD_DELAY to this)
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3
AUTOTHROTTLE_MAX_DELAY = 120
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5   # was 1.0. Scrapy slows down if the server gets slow

RETRY_ENABLED = True
RETRY_TIMES = 4
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524]
DOWNLOAD_TIMEOUT = 45


SOFT_RETRY_TIMES = 2  # extra tries when a page loads but has no data

# Replace Scrapy's retry with ours (same behaviour, but it logs the reason)
DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,
    "utils.retries.LoggingRetryMiddleware": 550,
}

# The "why was it not stored" ledger
LOGS_DIR = DATA_DIR / "logs"
EXTENSIONS = {"utils.logs.NotStoredLog": 500}


ITEM_PIPELINES = {
    "pipelines.validation.ValidationPipeline": 300,
    "pipelines.storage.StoragePipeline": 400,
}

LOG_LEVEL = "INFO"

# --------------------------------------------------- project constants
# Set OVERWRITE=1 (-s OVERWRITE=1) to start a fresh CSV instead of resuming.
OVERWRITE = False

RESULTS_URL = "https://www.sothebys.com/en/results"
# Opaque filter id copied from the site's own results URL. Its scope
# (department / region) is unverified, so results are not "all of Sotheby's".
DEFAULT_F2 = os.getenv("RESULTS_F2", "")  # empty = no f2 filter

GRAPHQL_URL = "https://clientapi.prod.sothelabs.com/graphql"
PAGE_SIZE = 48

# The site's own lot-list query, trimmed to the fields this project uses.
# __typename is requested on `sold` and `estimateV2` so hidden results and
# "estimate upon request" can be told apart from missing data.
LOT_QUERY = """
query LotCardsFilterByPaginated($id: String!, $filter: LotCardsConnectionFilter!, $language: TranslationLanguage!, $limit: Int, $offset: Int) {
  auction(id: $id, language: $language) {
    lotCards: lotCardsConnection(offset: $offset, limit: $limit, filter: $filter) {
      hasNextPage
      totalCount
      lots {
        lotId
        title
        creatorsDisplayTitle
        auction { auctionId sapSaleNumber currency slug { name year } }
        lotNumber { ... on VisibleLotNumber { lotDisplayNumber } }
        bidState {
          isClosed
          reserveMet
          sold {
            __typename
            ... on ResultVisible { isSold premiums { finalPrice: finalPriceV2 { currency amount } } }
          }
        }
        slug { lotSlug }
        estimateV2 {
          __typename
          ... on LowHighEstimateV2 { highEstimate { amount } lowEstimate { amount } }
        }
        withdrawnState { state }
        media(imageSizes: [Large]) { images { renditions { url imageSize } } }
      }
    }
  }
}
"""








