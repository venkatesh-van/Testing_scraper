"""Retries that tell you WHY.

1. LoggingRetryMiddleware: Scrapy's normal retry (timeouts, 429, 5xx), plus a log line
   for every retry and a 'GAVE UP' line when the attempts are used up.
2. retry_request(): for 'soft' failures, where the page loaded (HTTP 200) but had no
   data (no __NEXT_DATA__, GraphQL returned errors). Scrapy does not retry those itself.
"""

import logging

from scrapy.downloadermiddlewares.retry import RetryMiddleware, get_retry_request
from scrapy.http import Request, Response

logger = logging.getLogger(__name__)

SOFT_RETRY_TIMES_DEFAULT = 2


class LoggingRetryMiddleware(RetryMiddleware):
    """Replaces Scrapy's RetryMiddleware (see DOWNLOADER_MIDDLEWARES in settings.py)."""

    # *args / **kwargs: different Scrapy versions pass the spider or not.
    def process_response(self, request, response, *args, **kwargs):
        result = super().process_response(request, response, *args, **kwargs)
        if isinstance(result, Request):
            self._retrying(request, result, f"HTTP {response.status}")
        elif (isinstance(result, Response) and result.status in self.retry_http_codes
              and not request.meta.get("dont_retry")):
            logger.error("GAVE UP after %s retries, HTTP %s: %s",
                         request.meta.get("retry_times", 0), result.status, request.url)
        return result

    def process_exception(self, request, exception, *args, **kwargs):
        result = super().process_exception(request, exception, *args, **kwargs)
        if isinstance(result, Request):
            self._retrying(request, result, type(exception).__name__)
        elif result is None and request.meta.get("retry_times", 0) >= self.max_retry_times:
            logger.error("GAVE UP after %s retries, %s: %s",
                         request.meta.get("retry_times", 0), type(exception).__name__, request.url)
        return result

    def _retrying(self, request, retry, why):
        limit = request.meta.get("max_retry_times", self.max_retry_times)
        logger.warning("RETRY %s/%s because %s: %s", retry.meta.get("retry_times"), limit, why, request.url)


def retry_request(spider, request, reason):
    """A copy of `request` to try again, or None when out of attempts.

    Also returns None when there is no crawler (unit tests), so tests never retry.
    """
    crawler = getattr(spider, "crawler", None)
    if crawler is None:
        return None
    limit = getattr(spider, "soft_retry_times", None)          # -a retries=N on the command line
    if limit is None:
        limit = crawler.settings.getint("SOFT_RETRY_TIMES", SOFT_RETRY_TIMES_DEFAULT)
    return get_retry_request(request, spider=spider, reason=reason, max_retry_times=limit)