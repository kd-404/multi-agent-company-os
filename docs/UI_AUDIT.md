# UI audit — what looked weak, and what changed

Done as a UI-engineer pass over the storefront after the first public version. Each row: the problem, why it hurt, the fix.

| # | Weakness found | Why it hurt | Fix |
|---|---|---|---|
| 1 | Purple, dark-tech header and neon accents | Read as a dev dashboard, not a clothing brand; clashed with product photos | Beige / white / brown palette, script wordmark, announcement bar |
| 2 | Display font (Clash Display) and system-style body | Cold, generic; no brand voice | Allura (script accent), Cormorant Garamond (headings), Jost (UI) |
| 3 | No hero image; abstract tilt-card of one tee | First screen sold nothing | Full-bleed model hero (generated with the image model), copy on a soft scrim |
| 4 | Only graphic tees; nothing else to browse | Looked like a one-product demo | Linen Edit (plain shirts), farm/vintage gallery, printed pieces with type filters |
| 5 | Product cards: raw trend paragraph as the title, no price | Nobody can scan or compare | Title, type · colour, price, struck-through MRP, % off, stock chip, hover swap to the worn photo |
| 6 | Same white tee on every card (template fallback + invisible prints on dark fabric) | Catalog looked broken | AI product photos per garment/colour with a Vision critic + retry; fixed fabric shading in the fallback |
| 7 | Checkout was a tiny modal with a neon button | Not credible next to Amazon/Flipkart/Swiggy | Full-page 4-step flow: login → address → order summary → payment, price-details card, coupon, ETA, success screen |
| 8 | No size / quantity / delivery cost | Missing basics of any shop | Size S–XL, qty, delivery fee rule (free over ₹999), WELCOME10 coupon; totals computed on the server |
| 9 | No form validation feedback | Silent failures | Inline per-field errors (phone, pincode, address); server re-validates |
| 10 | Cart popover that said "coming soon" | A dead control | Removed; Buy now goes straight to checkout |
| 11 | No way to customise a tee | Image agent was hidden in the admin panel | `/studio`: upload or describe artwork, pick garment/colour, flat + on-model preview, order |
| 12 | One chatbot, admin-only knowledge, shown to everyone | Leak risk and not useful to shoppers | RBAC (admin/support/user); CEO assistant admin-only; separate customer assistant (stock, catalog, FAQ, photo scan, tickets) |
| 13 | Mobile: filter sidebar and header crowded | Hard to use on a phone | Collapsing nav, chip filters instead of a sidebar, sticky bottom bar in checkout, full-height assistant sheet |
| 14 | Low contrast muted text, no focus styles | Accessibility | Darker muted tone, visible focus rings, reduced-motion support, labelled controls |
| 15 | Admin dashboard showed every panel to every staff user | Wrong audience | Role-based panels; support role sees only tickets; customers are redirected to the shop |

## Deliberately not built
- Real payments. Checkout takes a **method choice only**: no card number, CVV or UPI-ID fields. A form that looks like it collects payment credentials is indistinguishable from a harvesting page, even when labelled demo.
- Real e-mail/SMS. Support tickets live in the database and the staff queue.

## Still weak (honest list)
- Product copy is short; no size chart or reviews.
- No cart (single-item checkout) and no order-history page for customers.
- Brand imagery quality depends on the image model; regenerate from Storefront Builder if a shot is off.
