# Loomwell — Agent/Tool-Use Reliability: Failure Modes

This is the write-up an FDE should be able to hand a client's engineering
contact: not "it works," but *what was deliberately stress-tested, what
fails safely by design, and what still needs a human.* The actual suite
lives in `tests/test_reliability.py`; this doc is the narrative behind it.

## What's actually being stress-tested

Loomwell's agents call five external services with no SLA this project
controls: Tavily (trend research), the Foundry image deployment, Azure AI
Vision, Razorpay, and the Instagram Graph API. Every one of those calls
can fail in the same handful of ways — timeout, connection drop, rate
limit (429), transient server error (5xx) — and until this pass, every
call site handled that failure differently (some retried informally with
a user clicking "try again," some didn't retry at all).

## Fix 1: a single retry/backoff policy, applied consistently (`app/retry.py`)

**Failure mode found:** no call in the pipeline retried anything. A
single dropped connection to Tavily mid-batch failed that one design
outright, even though the exact same request would likely succeed a
second later.

**Fix:** `with_retry()` wraps every external call (Tavily, image
generation, Vision, Razorpay order creation, each Instagram Graph step)
with exponential backoff + jitter, retrying only on signals that mean
"this will probably work if I just ask again" — timeouts, connection
errors, HTTP 429/500/502/503/504 — and never on a 4xx that means the
request itself was wrong (bad prompt, bad auth, 404), since retrying
those just wastes time reproducing the same failure.

**What's deliberately NOT retried as a single unit:** the Instagram
two-step publish (create container → publish container). Retrying the
whole pair would risk creating a second media container if the first
create actually succeeded but the client never saw the response in time;
each step retries independently instead.

**Tested by:** `test_with_retry_succeeds_after_transient_failures`,
`test_with_retry_gives_up_and_raises_retry_exhausted`,
`test_with_retry_does_not_retry_non_retryable_errors`,
`test_with_retry_retries_on_429`.

## Fix 2: malformed input to admin endpoints degrades to 4xx, never 500

**Failure mode found (before the garment/color reassign feature shipped
with validation):** an endpoint that takes a `garment`/`color` string and
trusts it blindly would either silently no-op on a typo'd value or throw
an unhandled exception deep in the compositing code when it tried to look
up a print-area box for a garment type that doesn't exist.

**Fix:** `POST /api/admin/design/{id}/reassign` validates `garment` and
`color` against the real `GARMENTS`/`COLORS` matrix and returns a `400`
naming exactly which field was invalid, before anything touches the
database.

**Tested by:** `test_reassign_rejects_unknown_garment`,
`test_reassign_rejects_unknown_color`,
`test_reassign_rejects_missing_fields`.

## Fix 3: referencing a nonexistent record is 404, not a crash

**Failure mode found:** several endpoints assumed the id in the URL
always exists (reasonable for "my own admin dashboard clicking its own
buttons," unreasonable the moment the surface is scriptable or
hand-edited). Reassigning, approving, or compositing a mockup for a
design id that doesn't exist (or isn't in the right status) needs to
fail as a clean `404`, not an unguarded `NoneType has no attribute`.

**Fix:** every lookup-by-id route checks for `None` and raises
`HTTPException(404, ...)` before touching the row.

**Tested by:** `test_reassign_nonexistent_design_is_404_not_500`,
`test_approve_nonexistent_design_is_404_not_500`,
`test_public_mockup_nonexistent_design_is_404`,
`test_create_order_rejects_unapproved_design`.

## Fix 4: payment verification fails safe when Razorpay isn't configured

**Failure mode found:** `verify_payment` computes an HMAC using
`RAZORPAY_KEY_SECRET` — if that's empty (simulated mode, no keys set
yet), signature verification is either a meaningless no-op or, worse, an
unhandled exception on an empty-string HMAC key.

**Fix:** `razorpay_configured()` is checked first and returns a clean
`409 Conflict` ("Razorpay isn't connected") before any HMAC computation
happens at all.

**Tested by:** `test_verify_payment_without_razorpay_configured_is_409_not_500`,
`test_verify_payment_rejects_malformed_payload`.

## Fix 5: auth boundaries hold under direct, unauthenticated/unauthorized hits

**Failure mode found:** none, but this is exactly the kind of thing that
regresses silently when a new admin route is added and someone forgets
the `Depends(require_admin)`. A parametrized test sweep across every
admin route catches that class of mistake automatically going forward,
rather than relying on someone noticing in manual QA.

**Tested by:** `test_admin_get_routes_require_login`,
`test_admin_get_routes_reject_non_admin`,
`test_admin_post_routes_require_login` (parametrized across every admin
route currently in the app).

## What's intentionally out of scope here

- **Live third-party behavior** (does Razorpay's sandbox actually behave
  like its docs say, does the Instagram content-review queue delay a real
  post) — this suite runs with no real credentials and never hits the
  real network; it proves the *code's* failure handling, not a vendor's
  uptime. See `docs/COST_LATENCY.md` for the explicit caveat about
  simulated mode not being a complete substitute for a live-credentials
  pilot.
- **Load/concurrency testing** — the suite checks correctness under bad
  input, not throughput under many simultaneous users. Loomwell's current
  scale (a portfolio project, not production traffic) doesn't justify
  that investment yet; flagged here so it's a known gap, not a hidden one.

## Running the suite

```
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

No real Azure/Tavily/Razorpay/Instagram credentials are needed — the
suite points `DATABASE_URL` at a throwaway SQLite file and never
exercises a route that makes a real third-party call.
