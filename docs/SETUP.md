# Loomwell — Client Setup Guide

This is the document an FDE hands a client before the kickoff call: what
gets provisioned, in what order, who owns which credential, and what
"done" looks like. It assumes the reader has an Azure subscription and no
prior context on this codebase — the full click-by-click Portal steps live
in the repo [README](../README.md); this doc is the checklist and the
reasoning behind the order, not a repeat of every click.

## 1. Provisioning order, and why it's this order

| Step | Resource | Why it comes here |
|---|---|---|
| 1 | Resource group | Everything else needs a home; pick the region once, use it everywhere (cross-region calls add 50–150ms per hop and sometimes egress cost). |
| 2 | PostgreSQL Flexible Server | The app's `init_db()` runs on first boot and needs a reachable DB immediately — provisioning this after the App Service just means a crash-looping container until it's added. |
| 3 | Azure AI Vision | Independent of the DB; can be done in parallel with step 2. |
| 4 | Azure AI Foundry project + `ceo-assistant` agent | Needs the two knowledge files (`project-status.md`, `team.md`) written and uploaded *before* the agent is created, so the vector store isn't empty on day one. |
| 5 | App Service + Deployment Center → GitHub | Last, because its environment variables depend on the connection strings/keys from steps 2–4. Connecting it earlier just means redeploying after every credential lands. |
| 6 | Tavily API key | Needed by the Design agent's trend-research step; free tier is enough for a pilot. |

## 2. Credential ownership

A client engagement means credentials the FDE should **not** be the sole
holder of. Split like this:

- **Client's Azure subscription owner**: creates the resource group, grants
  the FDE *Contributor* (not *Owner*) on it for the engagement duration.
- **Client's billing contact**: should be the one who sees the Tavily and
  any future paid-tier Azure AI bills, not routed through the FDE's own
  account.
- **FDE**: holds `SECRET_KEY` (session signing) only until an admin account
  exists; rotates it once an admin can manage the app directly (see
  `ROLLBACK.md` for exactly what a `SECRET_KEY` rotation invalidates).

## 3. Minimum viable configuration vs. full configuration

Loomwell is built to run with partial configuration — each third-party
integration gates itself on whether its own env vars are present
(`razorpay_configured()`, `instagram_configured()` in
`app/routes/payment_routes.py` / `app/routes/marketing_routes.py`) and
**simulates** that integration, clearly labeled, when they're absent. This
means a client can go live with:

- DB + App Service + Vision + Foundry + Tavily → **required**, the app
  won't do anything useful without these.
- Razorpay keys, Instagram Graph token → **optional**, deferred to whenever
  the client's own business accounts (bank KYC, Meta Business verification)
  clear — which is realistically weeks behind the technical rollout, and
  shouldn't block it.

This is the deliberate design decision an FDE should be able to explain in
a client meeting: *the system is honest about what's real vs. simulated at
every point, so a partial rollout never silently pretends to be a complete
one.*

## 4. Definition of done for this setup

- [ ] `/health` returns `{"status": "ok"}`
- [ ] An admin account exists (see README §4)
- [ ] The Design agent generates and logs a design (Design Studio →
      "Generate new design")
- [ ] The CEO assistant answers a grounded question citing a real source
      file (not a generic LLM answer)
- [ ] `/shop` loads for a signed-out visitor
