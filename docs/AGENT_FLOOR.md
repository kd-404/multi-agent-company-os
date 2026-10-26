# Agent Floor (`/floor`)

Admin-only live map of every agent: what it does, what it touches, and whether it is working right now.

## Tabs
- **Workflow** – lanes (Design, Photo, Storefront, Orders, Marketing, Support) with a card per agent and arrows for data flow. Dashed arrows are feedback loops. Click an agent for its job, reads/writes, failure behaviour and recent runs.
- **Globe** – the pipeline as a journey: App Service → Tavily → Azure AI Foundry → Postgres → admin/shopper/Instagram. Click a hop or play the tour. A hop glows blue when one of its agents is working.
- **All agents** – card grid by lane with status pills.

## Where the data comes from
Every agent step calls `agent_log.step()` which writes a `start` row then an `ok`/`error` row (with `duration_ms`) to `agent_activities` (`node`, `run_id` columns). `/api/admin/floor/state` derives status:
`working` (start row < 5 min old, no finish), `finished` (< 90 s), `ok`, `waiting` (needs a human, e.g. approval), `error`, `planned`, `idle`. Stale start rows are treated as stalled. Logging failures never break requests.

## Live vs simulation
- **Run a real design** calls the real pipeline (Tavily + image model + Vision; costs a few cents).
- **Simulate a drop** is a scripted overlay in the browser (SIM-tagged). No API calls, no DB writes.

## Extending
Add the node to `app/agent_registry.py` (NODES/EDGES/HOPS), then wrap its work in `step(db, agent, node, label, run_id)`. Globe pin positions are illustrative.
