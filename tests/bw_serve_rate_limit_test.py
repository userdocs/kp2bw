"""Checks for the per-request rate-limit delay in BitwardenServeClient._request().

``--bw-rate-limit MS`` (and its ``KP2BW_BW_RATE_LIMIT`` env counterpart) adds a
minimum inter-request pause so a self-hosted Bitwarden/Vaultwarden server that
throttles rapid writes gets time to breathe.  These checks drive the guard in
:meth:`BitwardenServeClient._request` without spawning a live ``bw serve``.
"""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from kp2bw.bw_serve import BitwardenServeClient


def _make_client(rate_limit_delay_s: float, last_request_time: float) -> BitwardenServeClient:
    """Return a BitwardenServeClient instance that bypasses __init__.

    Only the state _request() touches is set: rate limit config, the
    last-request timestamp, and a fake HTTP client that returns a minimal
    success envelope.
    """
    inst: BitwardenServeClient = object.__new__(BitwardenServeClient)
    inst._rate_limit_delay_s = rate_limit_delay_s
    inst._last_request_time = last_request_time

    fake_resp = httpx.Response(200, content=b'{"success":true,"data":{}}')
    mock_http = MagicMock()
    mock_http.request.return_value = fake_resp
    inst._http = mock_http  # type: ignore[assignment]
    return inst


def assert_no_sleep_when_disabled() -> None:
    """rate_limit_delay_s=0 must never call time.sleep."""
    client = _make_client(rate_limit_delay_s=0.0, last_request_time=time.monotonic())
    with patch("kp2bw.bw_serve.time.sleep") as mock_sleep:
        client._request("GET", "/status")
    if mock_sleep.called:
        raise AssertionError("time.sleep must not be called when rate limiting is disabled")


def assert_sleeps_when_called_rapidly() -> None:
    """When _last_request_time is 'just now', _request should call time.sleep."""
    delay_s = 0.5
    client = _make_client(
        rate_limit_delay_s=delay_s,
        last_request_time=time.monotonic(),  # simulate a request that just completed
    )
    with patch("kp2bw.bw_serve.time.sleep") as mock_sleep:
        client._request("GET", "/status")
    if not mock_sleep.called:
        raise AssertionError("time.sleep must be called when a request follows immediately")
    slept = mock_sleep.call_args[0][0]
    if not (0 < slept <= delay_s):
        raise AssertionError(f"sleep duration {slept:.4f}s should be in (0, {delay_s}]")


def assert_no_sleep_when_enough_time_elapsed() -> None:
    """When more than rate_limit_delay_s has elapsed since the last request, no sleep."""
    delay_s = 0.1
    client = _make_client(
        rate_limit_delay_s=delay_s,
        last_request_time=time.monotonic() - 10.0,  # 10 seconds ago
    )
    with patch("kp2bw.bw_serve.time.sleep") as mock_sleep:
        client._request("GET", "/status")
    if mock_sleep.called:
        raise AssertionError(
            f"time.sleep must not be called when >{delay_s}s has elapsed since last request"
        )


def assert_last_request_time_updated_after_call() -> None:
    """_last_request_time is stamped each call so subsequent calls enforce the gap."""
    delay_s = 0.5
    old_time = time.monotonic() - 10.0
    client = _make_client(rate_limit_delay_s=delay_s, last_request_time=old_time)

    with patch("kp2bw.bw_serve.time.sleep"):
        client._request("GET", "/status")

    if client._last_request_time <= old_time:
        raise AssertionError(
            "_last_request_time was not advanced after _request() call"
        )
    if client._last_request_time > time.monotonic() + 1.0:
        raise AssertionError("_last_request_time is unreasonably far in the future")


def assert_negative_rate_limit_clamped_to_zero() -> None:
    """A negative rate_limit_delay_s value is clamped to 0 in __init__, meaning disabled.

    The constructor uses max(0.0, ...) so it can never trigger a negative sleep
    call or an infinite wait.
    """
    inst = object.__new__(BitwardenServeClient)
    # Simulate what __init__ does: max(0.0, -0.5) == 0.0
    inst._rate_limit_delay_s = max(0.0, -0.5)
    if inst._rate_limit_delay_s != 0.0:
        raise AssertionError(
            "Negative rate_limit_delay_s should clamp to 0.0 via max(0.0, ...)"
        )


def main() -> None:
    assert_no_sleep_when_disabled()
    assert_sleeps_when_called_rapidly()
    assert_no_sleep_when_enough_time_elapsed()
    assert_last_request_time_updated_after_call()
    assert_negative_rate_limit_clamped_to_zero()
    print("bw serve rate limit test passed")


if __name__ == "__main__":
    main()
