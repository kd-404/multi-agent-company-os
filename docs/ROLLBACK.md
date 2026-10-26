# Loomwell — Rollback Plan

What to do when a deploy, a config change, or an integration goes wrong in
production, in order of how fast each gets the client back to a working
state. An FDE's rollback plan should always be decided *before* the thing
it's for breaks, not improvised during an incident.

## 1. Bad deploy (new code, same config)

Azure App Service's Deployment Center (wired to GitHub Actions, see
README §2) keeps every prior deployment. Fastest path:

1. App Service → **Deployment Center** → **Logs** → find the last known-good
   deployment → **Redeploy**.
2. This reverts code only — the database schema is forward-only (see §3),
   so this is safe as long as the bad deploy didn't also ship a breaking
   migration.
3. Confirm via `/health` and a manual "Generate new design" before telling
   the client it's resolved — a 200 on `/health` only proves the process
   started, not that the pipeline works.

**Time to recover: minutes.**

## 2. Bad config (an env var change broke something)

- App Service → **Configuration** → **Application settings** → the Portal
  keeps no history here, which is exactly why `SETUP.md`'s env var table
  should be kept as a maintained record *outside* the Portal (a doc, a
  password manager note) — treat the Portal as the current-state editor,
  not the source of truth for "what should it be."
- If a single integration's keys are the problem (e.g. a rotated Razorpay
  secret that's now wrong), the fastest fix is often **removing** the env
  var rather than fixing it — `razorpay_configured()` returning `False`
  drops the system back to simulated mode cleanly, which is a legitimate
  temporary state, not a broken one (see `COST_LATENCY.md` on why
  simulated mode exists at all).

**Time to recover: minutes, once the bad var is identified.**

## 3. Database migration went wrong

`app/db.py`'s `_run_lightweight_migrations()` is intentionally additive
and defensive — it adds missing columns and creates indexes wrapped in
`try/except`, and never drops or renames an existing column. This means:

- A failed migration on startup degrades to "some new feature's columns
  are missing" (that feature breaks, logged clearly), not "the app won't
  boot" or "existing data is lost."
- Rollback here is almost always a **code** rollback (§1) back to the
  version before the migration was introduced, not a database restore —
  reserve an actual point-in-time restore (Azure Flexible Server supports
  this from the Portal) for data corruption, not schema mistakes.

**Time to recover: minutes for a code rollback; up to an hour for a
genuine point-in-time DB restore.**

## 4. A third-party integration is actively failing (Tavily, Vision, image gen, Razorpay, Instagram)

This is the scenario `app/retry.py`'s retry/backoff and the
`*_configured()` gating exist for (see `FAILURE_MODES.md` for exactly
which calls are covered and what each one degrades to). The rollback
instinct here should usually be **don't roll back code — let the
degradation do its job**:

- Vision down → designs save untagged, backfilled later. No action needed.
- Tavily down after retries exhausted → that one generation fails loudly
  in the Agent Status feed; retry the click. No config change needed.
- Razorpay/Instagram down → remove the keys to force simulated mode
  (§2) until the provider recovers, rather than leaving customers facing
  a half-failed checkout.

## 5. `SECRET_KEY` rotation (compromise, or handing off from FDE to client)

Rotating `SECRET_KEY` invalidates every existing session cookie — every
signed-in user (including admins) is logged out, with no data loss. This
is the one "rollback" that's actually a forward action with a visible,
expected side effect: tell the client's team in advance ("everyone will
need to log back in") so it doesn't read as an outage.

## Escalation order, if the FDE isn't available

1. Check the Agent Status activity feed first — it's the system's own
   audit trail and usually names the failing stage directly.
2. Check `/health`.
3. Check App Service → Deployment Center → Logs for a crash loop.
4. Only then touch config or redeploy — changing two things at once is
   how a 10-minute incident becomes a 2-hour one.
