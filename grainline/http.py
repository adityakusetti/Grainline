"""HTTP with retries and backoff, so one flaky call does not fail the whole run."""
import time

import requests

RETRY_STATUS = {429, 500, 502, 503, 504}


def request(method, url, retries=3, backoff=2.0, **kwargs):
    kwargs.setdefault("timeout", 60)
    last = None
    for attempt in range(retries):
        try:
            r = requests.request(method, url, **kwargs)
            if r.status_code not in RETRY_STATUS:
                r.raise_for_status()
                return r
            last = requests.HTTPError(f"{r.status_code} from {url}")
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
        time.sleep(backoff ** attempt)
    raise last
