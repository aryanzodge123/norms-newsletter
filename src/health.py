"""healthchecks.io pings (SPEC section 8).

Two checks: one for the 6am publish, one for the collector cadence. Each is
a URL in the environment (config.Settings), and a job signals liveness by
POSTing to it: bare URL for success, `/start` before a long run, `/fail`
when it failed. A check that does not hear from its job within its grace
period fires the dead man's switch, which is how a silent deploy failure or
a stalled collector is surfaced (SPEC section 7, "Deploy fails ->
healthchecks.io alert").

Two rules this module never breaks:
- If the URL is not configured, pinging is a no-op. A dev run without
  monitoring set up must behave exactly like one with it.
- A ping never raises. Monitoring is observability, not pipeline logic; a
  network blip talking to healthchecks.io must not fail an edition that
  otherwise built fine.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

# Signals healthchecks.io understands, appended to the check URL.
START = "start"
FAIL = "fail"
SUCCESS = ""  # the bare URL is the success ping

_TIMEOUT = 10.0


def ping(url: str | None, signal: str = SUCCESS) -> bool:
    """POST a liveness signal to a healthchecks.io check. Never raises.

    Returns True if the ping was sent and accepted, False if it was skipped
    (no URL) or failed (network or non-2xx). The return value is for logging
    and tests; callers do not branch on it, because a failed ping must not
    change what the pipeline does.
    """
    if not url:
        return False

    target = url if signal == SUCCESS else f"{url.rstrip('/')}/{signal}"
    try:
        response = httpx.post(target, timeout=_TIMEOUT)
        response.raise_for_status()
        log.info("healthchecks: pinged %s", signal or "success")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("healthchecks ping (%s) failed, ignoring: %s", signal or "success", exc)
        return False
