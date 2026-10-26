# Loomwell — Cost / Latency Tradeoffs

The judgment an FDE is actually hired for isn't "can you call the model
API" — it's "do you know what each call costs the client, in money and in
time, and can you say so plainly before they find out the hard way."

## Where the money and the latency actually go

| Call | Triggered by | Cost driver | Typical latency | Notes |
|---|---|---|---|---|
| Tavily search (`trend_research.py`) | Every design generation | Per-search, free tier capped (1,000/mo at time of writing) | ~1–2s | Cheapest call in the pipeline by far; batch-of-8 generation makes 8 of these. |
| `gpt-image-1.5` generation (`image_client.py`) | Every design generation | Per-image, the single most expensive call in the system | 10–20s | Dominates both the cost and the wall-clock time of "Generate new design." A batch of 8 is sequential by design (see below), so it's ~2–3 minutes end to end, not 8×20s in parallel. |
| Azure AI Vision tagging (`visual_search.py`) | Every design generation (non-fatal if it fails) | Per-call, Vision pricing tier | ~1s | Deliberately wrapped so a Vision outage degrades to "untagged design," not a failed generation — see `FAILURE_MODES.md`. |
| Mockup-template generation (27 combos: 3 garments × 3 colors × 3 slots) | One-time admin action | 27× the image-gen cost, paid once | 5–10 minutes total | This is the one call worth flagging to a client *before* they click it — it's the single largest one-time spend in the whole system, and it's easy to trigger by accident while exploring the admin UI. |
| Foundry `ceo-assistant` chat | Every chatbot question | Per-token, File Search retrieval adds a small fixed overhead | 1–3s | Cheap relative to image generation; not a cost concern at typical usage. |
| Razorpay order creation / verification | Every checkout attempt (live mode only) | Razorpay's own transaction fee, not an Azure/model cost | <1s | Zero cost in simulated mode — see `SETUP.md` §3. |
| Instagram Graph API post | Every scheduled post (live mode only) | Free (Meta doesn't charge for Graph API posting) | 1–3s per step, two steps | The image URL it publishes from must be *publicly reachable* — this is a correctness constraint, not a cost one, but it's the detail that trips up a first integration attempt. |

## Why batch generation is sequential, not parallel

`generate_batch` (app/routes/design_routes.py) deliberately loops, not
`asyncio.gather`s, across the 8 generations. Firing all 8 image-generation
calls at once would cut wall-clock time roughly 8x, but:

1. It multiplies peak concurrent cost exposure with no cost benefit (same
   total spend, just all at once) — the only upside is speed.
2. Hitting rate limits on the image deployment under concurrent load fails
   *all* in-flight requests at once rather than failing forward one at a
   time, which is strictly worse for an admin watching a progress count.

This is exactly the kind of tradeoff worth saying out loud to a client
before they ask "why is this slow" — the honest answer is "it's a
deliberate choice, and here's the failure mode it avoids," not "we didn't
get to optimizing it yet."

## The one tradeoff a client will ask about directly: simulated vs. live payments/posting

Running Razorpay/Instagram in simulated mode costs nothing and has zero
latency beyond a DB write — which is also why it's the default until real
keys are configured (`SETUP.md` §3). The tradeoff to be explicit about:
simulated mode proves the *code path* works; it proves nothing about
Razorpay's actual approval behavior, webhook timing under their real load,
or Instagram's content-review queue. A client should not treat a clean
pilot in simulated mode as evidence the live integration will behave
identically — flag that gap, don't let them discover it on launch day.
