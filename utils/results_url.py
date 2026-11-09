"""The Sotheby's results-page URL for a date window (what the site's own date picker builds)."""

from datetime import datetime, time, timezone
from urllib.parse import urlencode

from config.settings import DEFAULT_F2, RESULTS_URL


def epoch_ms(day):
    """Midnight UTC of a date, in epoch milliseconds (the site's f0 filter unit)."""
    return int(datetime.combine(day, time.min, tzinfo=timezone.utc).timestamp() * 1000)


def build_results_url(start, end, f2=DEFAULT_F2):
    """Results URL for a date window.

    The site writes dates as DD/MM/YYYY (checked against the old URLs: 02/08/2015
    pairs with an f0 of 1 Aug 18:30 UTC = 2 Aug IST). f0 is start-midnight to
    end-midnight, as the site's own date picker produced.
    """
    params = {
        "from": start.strftime("%d/%m/%Y"),
        "to": end.strftime("%d/%m/%Y"),
        "f0": f"{epoch_ms(start)}-{epoch_ms(end)}",
    }
    if f2 and str(f2).lower() != "auto":  # empty / None / "auto" = no f2 filter in the URL
        params["f2"] = f2
    params["q"] = ""
    return f"{RESULTS_URL}?{urlencode(params)}"
