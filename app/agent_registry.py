"""
The map of Loomwell's agents: who exists, what each one does, what it reads
and writes, which service it calls, and how work flows between them.

This one file drives the Agent Floor page (/floor): the workflow graph, the
"All agents" cards and the globe's pipeline explanation. Live status is NOT
stored here - it is derived from the agent_activities table (see
floor_routes.py) using each node's `id`, which is the value agents pass as
`node=` to log_activity()/step(). `built: False` nodes are shown as Planned
so the graph never claims an agent that doesn't exist.

kind: "ai"    - calls a model (Azure OpenAI image / Vision / Foundry agent)
      "tool"  - calls an external API or library (Tavily, Pillow)
      "rule"  - deterministic code (rules, math, database)
      "human" - waits for a person
"""

LANES = [
    {"id": "design", "title": "Design Studio", "sub": "Searches trends, then designs", "color": "#e9a15f"},
    {"id": "photo", "title": "Photo Studio", "sub": "Puts every design on a real garment", "color": "#d98f7a"},
    {"id": "shop", "title": "Storefront & Shoppers", "sub": "What customers see and talk to", "color": "#9bbf8a"},
    {"id": "orders", "title": "Orders & Delivery", "sub": "Runs on every store order", "color": "#6fb7b0"},
    {"id": "growth", "title": "Marketing", "sub": "Finds gaps, writes captions, posts", "color": "#d6a1c9"},
    {"id": "care", "title": "Support & Leadership", "sub": "Tickets and the CEO assistant", "color": "#8fa8d8"},
    {"id": "platform", "title": "Platform & Safety", "sub": "Guardrails that run under everything", "color": "#b5a58f"},
]

N = lambda **k: k  # noqa: E731  (tiny readability helper)

NODES = [
    # ---------------- Design Studio ----------------
    N(id="trend_scout", code="TS", lane="design", name="Trend Scout", kind="tool", built=True,
      does="Searches the live web for what people are wearing right now and writes a short trend brief.",
      service="Tavily search API", reads="A focus phrase (or the default trend query)", writes="Trend brief + source URLs",
      failure="Retry with backoff; if Tavily is down the run stops cleanly and is logged as an error."),
    N(id="prompt_writer", code="PW", lane="design", name="Prompt Writer", kind="rule", built=True,
      does="Turns the trend brief into an image prompt and appends the house style rules (flat print-ready art, plain background, no text).",
      service="Python (no model call)", reads="Trend brief", writes="Image prompt", failure="Deterministic - cannot fail on its own."),
    N(id="image_gen", code="DG", lane="design", name="Design Generator", kind="ai", built=True,
      does="Draws the print artwork from the prompt with the image model.",
      service="Azure OpenAI image deployment (Foundry)", reads="Image prompt", writes="1024x1024 PNG artwork",
      failure="Retries on 429/5xx/timeouts; other errors fail fast with the real message."),
    N(id="vision_tagger", code="VT", lane="design", name="Vision Tagger", kind="ai", built=True,
      does="Looks at the finished artwork and extracts subject tags and its dominant colour (used for search and garment matching).",
      service="Azure AI Vision", reads="Artwork PNG", writes="Tags + dominant RGB",
      failure="Non-fatal: the design is saved untagged and backfilled the first time someone searches."),
    N(id="relevance_critic", code="RC", lane="design", name="Relevance Critic", kind="rule", built=True,
      does="Scores 0-100 whether the artwork's own Vision tags actually relate to the trend brief - catches off-brief drift even when every call returned 200.",
      service="Evaluation layer (app/evaluation.py)", reads="Trend brief + tags", writes="relevance_score metric",
      failure="Scores only; never blocks a design."),
    N(id="garment_matcher", code="GM", lane="design", name="Garment Matcher", kind="rule", built=True,
      does="Chooses the garment (tee, hoodie, full-sleeve, shorts) and a fabric colour that contrasts with the art, so prints never vanish.",
      service="Python rules (app/garments.py)", reads="Dominant colour", writes="Garment + colour on the design",
      failure="Falls back to a white tee."),
    N(id="human_approval", code="OK", lane="design", name="Human Approval", kind="human", built=True,
      does="A person reviews each design. Nothing reaches the shop, photography or social media until approved.",
      service="Admin dashboard", reads="Pending designs", writes="approved / rejected",
      failure="Designs simply wait - nothing ships unreviewed."),

    # ---------------- Photo Studio ----------------
    N(id="photo_director", code="PD", lane="photo", name="Photo Director", kind="rule", built=True,
      does="Writes an art-directed photo brief: print placement for the garment, contrast fixes for dark-on-dark art, model and setting.",
      service="Python (app/product_photos.py)", reads="Approved design + garment/colour", writes="Photo prompt",
      failure="Deterministic."),
    N(id="photographer", code="PH", lane="photo", name="Photographer", kind="ai", built=True,
      does="Uses the image EDIT model with the design as the reference to photograph it printed on the actual garment - flat lay and on a model.",
      service="Azure OpenAI image edit (Foundry)", reads="Photo prompt + design PNG", writes="Product photo",
      failure="Retry/backoff; on failure the shop falls back to a Pillow composite."),
    N(id="photo_critic", code="PC", lane="photo", name="Photo Critic", kind="ai", built=True,
      does="Asks Vision what is in the photo. Wrong garment or colour? It names the exact mistake and sends the photographer back for one corrected retry.",
      service="Azure AI Vision", reads="Product photo", writes="verified flag + caption",
      failure="If Vision is unavailable the photo is stored as 'unverified'."),
    N(id="linen_atelier", code="LA", lane="photo", name="Linen Atelier", kind="ai", built=True,
      does="Creates the plain linen shirt line: flat-lay and on-model photos, price, stock, listing.",
      service="Azure OpenAI image", reads="Linen catalogue spec", writes="Approved plain products",
      failure="One product per request; idempotent."),
    N(id="brand_stylist", code="BS", lane="photo", name="Brand Stylist", kind="ai", built=True,
      does="Generates brand imagery: the model hero, vintage farm-and-horse photos and section banners.",
      service="Azure OpenAI image", reads="Brand brief", writes="Brand assets",
      failure="One image per request; safe to rerun."),

    # ---------------- Storefront ----------------
    N(id="storefront", code="SF", lane="shop", name="Storefront", kind="rule", built=True,
      does="Serves the catalogue: titles, prices, MRP, live stock chips, product photos.",
      service="FastAPI + PostgreSQL", reads="Approved designs + photos", writes="Pages and JSON",
      failure="Missing photos fall back to the composite mockup."),
    N(id="visual_search", code="VS", lane="shop", name="Visual Search", kind="ai", built=True,
      does="Takes a shopper's photo and ranks products by subject tags and colour similarity.",
      service="Azure AI Vision + Pillow", reads="Uploaded photo", writes="Ranked matches + interest signal",
      failure="Unreadable images get a friendly error."),
    N(id="shop_assistant", code="SA", lane="shop", name="Shop Assistant", kind="rule", built=True,
      does="Answers shoppers about products, live stock, delivery and returns, scans photos, and opens support tickets. Grounded only in the catalogue and a public fact sheet - never the internal docs.",
      service="Rules + catalogue DB", reads="Message / photo", writes="Reply, product cards, tickets",
      failure="Unknown questions are handed to support."),
    N(id="studio_agent", code="PY", lane="shop", name="Print-Your-Own Studio", kind="ai", built=True,
      does="Lets shoppers upload artwork or describe it for the image model, with a deny-list, per-user daily limit and private designs.",
      service="Azure OpenAI image + Pillow", reads="Upload or prompt", writes="Custom design + previews",
      failure="Rate-limited; blocked prompts never reach the model."),

    # ---------------- Orders ----------------
    N(id="checkout", code="CK", lane="orders", name="Checkout Desk", kind="rule", built=True,
      does="Runs the 4-step demo checkout and logs every stage a shopper reaches - opened, address, payment, paid - so drop-off is visible.",
      service="FastAPI + PostgreSQL", reads="Cart item + address", writes="Funnel events, orders",
      failure="Server recomputes all totals; stock is re-checked at confirm."),
    N(id="payment", code="PM", lane="orders", name="Payments", kind="rule", built=True,
      does="Records the demo payment choice. No card data is ever collected and no money moves.",
      service="Demo (Razorpay adapter exists, not enabled)", reads="Payment method", writes="Simulated payment record",
      failure="n/a - simulation."),
    N(id="warehouse", code="WH", lane="orders", name="Warehouse", kind="rule", built=True,
      does="Tracks stock per product, decrements on each sale, and flags reprints when stock is low and interest is high.",
      service="PostgreSQL", reads="Orders + interest signals", writes="Stock levels, reprint alerts",
      failure="Never lets stock go negative."),
    N(id="shipping", code="SH", lane="orders", name="Shipping", kind="rule", built=False,
      does="Would book a courier and send tracking.", service="-", reads="-", writes="-", failure="-"),
    N(id="gst_invoice", code="GS", lane="orders", name="Payments & GST", kind="rule", built=False,
      does="Would produce GST invoices.", service="-", reads="-", writes="-", failure="-"),

    # ---------------- Marketing ----------------
    N(id="trend_radar", code="TR", lane="growth", name="Trend Radar", kind="tool", built=True,
      does="Compares live trend research with what's already in the catalogue; when it finds a real gap it commissions a new design from the Design Studio.",
      service="Tavily + catalogue", reads="Live trends + catalogue", writes="Gap findings, design commissions",
      failure="Scan errors are logged; nothing is commissioned."),
    N(id="caption_writer", code="CW", lane="growth", name="Caption Writer", kind="rule", built=True,
      does="Drafts the social caption and hashtags from each design's own research and tags.",
      service="Python (no model call)", reads="Design + tags", writes="Caption + hashtags", failure="Deterministic."),
    N(id="instagram", code="IG", lane="growth", name="Instagram Poster", kind="tool", built=True,
      does="Posts an approved design with its caption to Instagram once credentials are configured.",
      service="Instagram Graph API", reads="Approved design + caption", writes="Social post",
      failure="Retry/backoff; failures are logged with the API's message."),
    N(id="whatsapp", code="WA", lane="growth", name="WhatsApp Follow-up", kind="ai", built=False,
      does="Would nudge abandoned checkouts.", service="-", reads="-", writes="-", failure="-"),

    # ---------------- Support & leadership ----------------
    N(id="support_desk", code="SD", lane="care", name="Support Desk", kind="human", built=True,
      does="Customer tickets (from the assistant or the form) land in a queue worked by staff with the support role.",
      service="PostgreSQL + RBAC", reads="Tickets", writes="Resolved tickets", failure="Tickets are never lost - stored first."),
    N(id="ceo", code="CEO", lane="care", name="CEO Assistant", kind="ai", built=True,
      does="Admin-only Foundry agent grounded in internal project documents; answers status and planning questions.",
      service="Azure AI Foundry agent", reads="Internal docs + question", writes="Answer",
      failure="Admin-only via RBAC; customers can never reach it."),

    # ---------------- Platform ----------------
    N(id="rbac", code="RB", lane="platform", name="Access Control", kind="rule", built=True,
      does="Roles (admin, support, customer) map to named permissions; every sensitive route asks for one.",
      service="app/auth.py", reads="Session", writes="Allow / 403", failure="Default deny."),
    N(id="retry", code="RT", lane="platform", name="Retry & Backoff", kind="rule", built=True,
      does="Wraps every external call: retries rate limits, 5xx and timeouts with exponential backoff; fails fast on real client errors.",
      service="app/retry.py", reads="Any external call", writes="Result or clear error", failure="Gives up after the configured attempts."),
    N(id="evals", code="EV", lane="platform", name="Evaluation Layer", kind="rule", built=True,
      does="Records per-stage latency, success and relevance for every design run - the Evaluation dashboard reads it.",
      service="app/evaluation.py", reads="Stage timings", writes="Metrics", failure="Never blocks the pipeline."),
]

# from -> to, with what travels along the edge. loop=True draws it dashed (a feedback loop).
EDGES = [
    ("trend_scout", "prompt_writer", "trend brief"),
    ("prompt_writer", "image_gen", "image prompt"),
    ("image_gen", "vision_tagger", "artwork PNG"),
    ("vision_tagger", "relevance_critic", "tags"),
    ("vision_tagger", "garment_matcher", "dominant colour"),
    ("relevance_critic", "human_approval", "score"),
    ("garment_matcher", "human_approval", "pending design"),
    ("human_approval", "photo_director", "approved design"),
    ("human_approval", "caption_writer", "approved design"),
    ("photo_director", "photographer", "photo brief"),
    ("photographer", "photo_critic", "photo"),
    ("photo_critic", "photographer", "correction (retry once)", True),
    ("photo_critic", "storefront", "verified photos"),
    ("linen_atelier", "storefront", "linen products"),
    ("brand_stylist", "storefront", "brand imagery"),
    ("storefront", "visual_search", "catalogue"),
    ("storefront", "shop_assistant", "catalogue + stock"),
    ("storefront", "checkout", "Buy now"),
    ("studio_agent", "checkout", "custom design"),
    ("checkout", "payment", "method chosen"),
    ("payment", "warehouse", "sale"),
    ("warehouse", "trend_radar", "low stock / interest", True),
    ("trend_radar", "trend_scout", "commissioned design", True),
    ("caption_writer", "instagram", "caption"),
    ("shop_assistant", "support_desk", "ticket"),
    ("evals", "ceo", "metrics"),
    ("warehouse", "ceo", "stock status"),
    ("rbac", "ceo", "admin only"),
    ("retry", "image_gen", "wraps calls", True),
]

# The globe: places the pipeline touches and the hops between them. Positions
# are illustrative (which cloud region hosts what is an App Service setting),
# the sequence and the data on each hop are real.
PLACES = {
    "web": {"label": "The open web", "lat": 38.9, "lon": -77.0, "kind": "external"},
    "tavily": {"label": "Tavily search", "lat": 37.4, "lon": -122.1, "kind": "external"},
    "foundry": {"label": "Azure AI Foundry\n(image, Vision, CEO agent)", "lat": 59.3, "lon": 18.1, "kind": "azure"},
    "app": {"label": "App Service\n(FastAPI, agents)", "lat": 18.5, "lon": 73.9, "kind": "azure"},
    "db": {"label": "PostgreSQL\n(designs, photos, events)", "lat": 1.3, "lon": 103.8, "kind": "azure"},
    "admin": {"label": "You\n(staff dashboard)", "lat": 10.9, "lon": 76.9, "kind": "person"},
    "shopper": {"label": "Shoppers", "lat": 28.6, "lon": 77.2, "kind": "person"},
    "insta": {"label": "Instagram", "lat": 53.3, "lon": -6.3, "kind": "external"},
}

HOPS = [
    {"id": 1, "from": "app", "to": "tavily", "title": "Scout asks the web", "nodes": ["trend_scout"],
     "body": "The Trend Scout sends one search query to Tavily and gets back a synthesized trend brief plus source URLs. If Tavily returns 429/5xx the call is retried with backoff."},
    {"id": 2, "from": "app", "to": "foundry", "title": "Prompt becomes artwork", "nodes": ["prompt_writer", "image_gen"],
     "body": "The brief plus house style rules go to the Azure image deployment. A 1024px PNG comes back (base64) and is held in memory."},
    {"id": 3, "from": "app", "to": "foundry", "title": "Vision reads the artwork", "nodes": ["vision_tagger"],
     "body": "Azure AI Vision returns tags and a caption. Locally, Pillow computes the dominant colour with the background keyed out."},
    {"id": 4, "from": "app", "to": "db", "title": "Design saved as pending", "nodes": ["relevance_critic", "garment_matcher"],
     "body": "A relevance score is recorded, a garment and contrasting colour are chosen, and the design is saved with status 'pending'. Every step is also written to agent_activities - that is what lights up this graph."},
    {"id": 5, "from": "admin", "to": "app", "title": "A human approves", "nodes": ["human_approval"],
     "body": "You review the pending design in the dashboard. Approval is the only gate to the shop, photography and social media."},
    {"id": 6, "from": "app", "to": "foundry", "title": "Photographer + critic", "nodes": ["photo_director", "photographer", "photo_critic"],
     "body": "In the background, the image EDIT model photographs the design on its garment; Vision then checks it's the right garment and colour. One automatic corrected retry if not."},
    {"id": 7, "from": "app", "to": "db", "title": "Photos stored", "nodes": ["storefront"],
     "body": "Verified photos are stored in the database (App Service's disk is wiped on restart) and served to the shop with caching."},
    {"id": 8, "from": "shopper", "to": "app", "title": "Shoppers browse, search, chat", "nodes": ["storefront", "visual_search", "shop_assistant", "studio_agent"],
     "body": "Shoppers hit the catalogue API. Photo search and the shop assistant call Vision; the assistant reads live stock from the database and opens tickets for humans."},
    {"id": 9, "from": "shopper", "to": "app", "title": "Checkout funnel", "nodes": ["checkout", "payment"],
     "body": "Each checkout step is logged (opened, address, payment, paid). No card data exists anywhere in this flow; totals are recomputed server-side."},
    {"id": 10, "from": "app", "to": "db", "title": "Warehouse updates stock", "nodes": ["warehouse"],
     "body": "A paid order decrements stock. Low stock plus sustained interest raises a reprint alert, which the Trend Radar can turn into a new design request - closing the loop."},
    {"id": 11, "from": "app", "to": "insta", "title": "Marketing posts", "nodes": ["caption_writer", "instagram"],
     "body": "Approved designs get a caption drafted from their own research, and can be posted to Instagram when credentials are configured."},
]


def node_ids() -> set[str]:
    return {n["id"] for n in NODES}


def registry_payload() -> dict:
    return {
        "lanes": LANES,
        "nodes": NODES,
        "edges": [{"from": e[0], "to": e[1], "label": e[2], "loop": bool(e[3]) if len(e) > 3 else False} for e in EDGES],
        "places": PLACES,
        "hops": HOPS,
    }
