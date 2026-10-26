"""
Shared retry/backoff helper for every external call this project makes
(Tavily, the Foundry image deployment, Azure AI Vision, Razorpay, the
Instagram Graph API). This is the agent-to-agent/tool-use reliability
project's core piece: these are the exact calls FAILURE_MODES.md
documents stress-testing, and the retries here are why most of those
documented failures self-heal instead of surfacing to a user or client.

Design choices, and why:
  - Retries only transient-looking failures (timeouts, connection errors,
    HTTP 429/500/502/503/504) - never retries on a 4xx that means the
    request itself was malformed (400, 401, 403, 404), since retrying a
    request that will deterministically fail the same way just burns
    quota/time for no benefit, and can mask a real bug behind "it worked
    on the 3rd try" noise.
  - Exponential backoff with jitter: fixed-interval retries from many
    concurrent callers (e.g. a batch of 8 design generations) would
    otherwise all retry at the exact same moment, which is how a brief
    blip turns into a self-inflicted thundering-herd second outage.
  - Every retry is logged at WARNING (not silently swallowed) - a
    dashboard or log stream should be able to tell "this call needed 2
    retries" apart from "this call was fast and clean," since a high
    retry rate on one integration is itself a signal worth a client
    seeing (see docs/COST_LATENCY.md on why that matters for the image
    generation call specifically).
"""
import logging
import random
import time
from typing import Callable, TypeVar

import httpx

log = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


class RetryExhausted(Exception):
    """Raised when every retry attempt failed - wraps the last real exception."""
    def __init__(self, attempts: int, last_error: Exception):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Gave up after {attempts} attempt(s): {type(last_error).__name__}: {last_error}")


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_HTTP_STATUS
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.NetworkError)):
        return True
    return False


def with_retry(
    fn: Callable[[], T],
    *,
    label: str,
    retries: int = 2,
    base_delay: float = 0.5,
    retryable: Callable[[Exception], bool] = _is_retryable,
) -> T:
    """
    Calls fn() and retries on transient failure, up to `retries` extra
    attempts (so `retries=2` means 3 total attempts). `label` is just for
    the log line - name the call site (e.g. "tavily_search",
    "image_generation") so a retry shows up attributable in logs/Log
    Stream, not as an anonymous "retrying...".
    """
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, re-raised below if not retryable
            last_error = exc
            if not retryable(exc) or attempt == retries + 1:
                break
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            log.warning(
                "[%s] attempt %d/%d failed (%s: %s) - retrying in %.1fs",
                label, attempt, retries + 1, type(exc).__name__, exc, delay,
            )
            time.sleep(delay)

    assert last_error is not None
    if _is_retryable(last_error):
        raise RetryExhausted(retries + 1, last_error) from last_error
    raise last_error
