# Loomwell — Client Onboarding Flow

What happens after infrastructure is up (see `SETUP.md`) and before the
client's team is self-sufficient. The goal of onboarding isn't "the app
works" — it's "the client can run and extend this without the FDE in the
room."

## Day 0 — Handover call (30 min)

1. Walk through the admin dashboard panel-by-panel, in the order a new
   operator would actually use them: **Design Studio** (how a design gets
   made and approved) → **Marketing** (how a design gets a caption and, if
   configured, an Instagram post) → **Warehouse** (how stock/reprint
   decisions surface) → **Customer Interest** (how the visual-search
   feature feeds back demand signal) → **Agent Status** (the full-pipeline
   demo button, and the activity feed as the audit trail for everything the
   agents did).
2. Create the client's own first admin account live on the call (README
   §4), so the FDE is never the only person who can promote others.
3. Show the one still-manual step by design: every generated design sits
   as `pending` until a human clicks Approve. This is a deliberate
   control, not a gap — say so explicitly, since clients default to
   assuming more automation than exists unless told otherwise.

## Week 1 — Supervised operation

- Client runs the daily flow themselves (generate → review → approve →
  schedule a post) with the FDE watching, not driving.
- FDE collects the first real friction points — usually: "how do I know
  if the Design agent is actually researching anything, or if Tavily
  failed silently?" (answer: the Agent Status feed logs every failure by
  stage — `trend_research`, `image_generation` — not just successes).
- First KYC checkpoint: Razorpay business-PAN and Instagram Business
  verification are usually still pending at this point. Confirm the client
  owns those processes directly; the FDE's role is making sure the app
  behaves correctly in simulated mode until they clear, not chasing the
  paperwork.

## Week 2 — Handback

- FDE does a final pass through `FAILURE_MODES.md` with the client's
  engineering contact (if they have one) — what was stress-tested, what
  retries automatically, what still needs a human when it breaks.
- Confirm the client has their own copy of all credentials (see `SETUP.md`
  §2) and has rotated `SECRET_KEY` if the FDE ever held it.
- Agree on a support window (if any) and a channel for it — don't leave
  "how do I reach you if this breaks" undefined; that's the single most
  common cause of a client feeling abandoned post-handoff even when the
  system is working fine.

## What "self-sufficient" means here, concretely

The client's team should be able to, without the FDE:
- Promote/demote admin accounts.
- Read the Agent Status feed and tell a real failure from a simulated
  integration notice.
- Re-run the mockup-template generation step if they add a new
  garment/color (`app/garments.py` — adding an entry there plus running
  "Generate mockup templates" is the entire extension path, no code
  review needed from the FDE).
- Know which three env vars gate which integration, and where to set them
  (App Service → Configuration), so clearing a KYC approval doesn't
  require re-engaging the FDE just to flip a switch.
