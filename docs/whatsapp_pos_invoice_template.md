# Meta WhatsApp template: `hotel_bell_elite_invoice`

POS restaurant/bar invoices are sent with this approved Cloud API template.
The **body structure** (blank lines, WhatsApp bold `*…*`, and the ₹ glyph)
must live in Meta Business Manager. App code only supplies the four body
variable values — see `pos_invoice_whatsapp.py`.

There is **no in-repo sync** that updates Meta template definitions. After
changing the copy below, edit the template in Meta Business Manager (or
submit a new version for approval) so live sends match.

## Why the WhatsApp **message text** did not change (PDF was already correct)

Cloud API fills only `{{1}}`…`{{4}}`. Fixed wording (“Thank you for dining at…”,
blank lines, `*bold*`, `₹`) comes from the **approved** template in Business
Manager — not from Python formatters.

**Live Graph GET (2026-09-05)** for this WABA:

| Field | Live value |
| --- | --- |
| Name | `hotel_bell_elite_invoice` |
| Language | `en` |
| Category | `UTILITY` |
| Template id | `2991938901141220` |
| Status | **`PENDING`** (not `APPROVED`) |
| Header | `DOCUMENT` |
| Body (pending draft) | New “dining at” copy (see below) — **not** the old “visit to” letter |

There was **no** separate `APPROVED` row for this name/language in the API list.
While an edit is **PENDING**, WhatsApp continues to **deliver the last approved
body** to guests. That is why guests still see the old Meta letter:

```
Dear Rajesh,

Thank you for your visit to Spice Multicuisine.
Please find your invoice SPC/2287/2026-27 attached for ₹6,362.00.

We hope to welcome you again soon!
```

even though app code already sends:

- template name `hotel_bell_elite_invoice` / language `en` (no `.env` override)
- four body params: guest first name, brand title case, invoice no, amount **without** ₹
- DOCUMENT header = generated PDF (so the PDF can look correct while the bubble text is still old)

**Code cannot fix the bubble text** by reformatting params or sending a free-form
UTILITY message (business-initiated policy requires the approved template).

### Graph API edit attempt

`POST /{template-id}` with an updated BODY returned:

- HTTP 400 / OAuthException code 100 / subcode `2388003`
- *“Message templates can only be edited if they have been rejected.”*

So while status is **PENDING**, Meta will not accept an API edit. Prefer
Business Manager (wait for approval, or cancel/reject and re-submit with the
exact body). Do **not** invent a new template name or a non-template send for
this flow.

## Template settings

| Field | Value |
| --- | --- |
| Name | `hotel_bell_elite_invoice` |
| Language | `en` |
| Header | **DOCUMENT** (PDF invoice attachment) |
| Body variables | 4 (`{{1}}` … `{{4}}`) |
| Env overrides | `WHATSAPP_POS_INVOICE_TEMPLATE`, `WHATSAPP_POS_INVOICE_TEMPLATE_LANGUAGE` |

## Exact body text to approve in Meta

Copy this **exactly** (including the blank lines between sections and the
asterisks around variables). Do not put newlines or `*` inside the parameter
values themselves.

```
Dear {{1}},

Thank you for dining at *{{2}}*.

Invoice: *{{3}}*

Amount: *₹{{4}}*

We look forward to serving you again!
```

**Note on the pending draft (2026-09-05):** Graph returned almost this text, but
**without** a blank line between `Invoice: *{{3}}*` and `Amount: *₹{{4}}*`. After
the pending version is approved (or rejected), edit again in Business Manager so
that blank line is present. Also set body examples to values **without** a ₹ in
`{{4}}` (e.g. `6,362.00`) — the static template already includes `₹`.

## Business Manager steps (same template name)

1. Open [Meta Business Suite](https://business.facebook.com/) → **WhatsApp Manager**
   → **Message templates**.
2. Open **`hotel_bell_elite_invoice`** (language **English / `en`**). Confirm you
   are not editing a differently named template.
3. Check **Status**:
   - If **Pending**: wait for Meta review. Live guest text stays on the **previous
     approved** body until this review finishes.
   - If **Approved** but still showing old copy: **Edit** the template, paste the
     exact body above, keep HEADER = **Document**, keep category **Utility**,
     submit for review.
   - If **Rejected**: edit (API edit is allowed when rejected), paste the exact
     body, resubmit.
4. Sample values for review: `Rajesh` / `Spice Multicuisine` /
   `SPC/2287/2026-27` / `6,362.00` (no ₹ in the amount sample).
5. After status becomes **Approved**, send one test invoice from POS and confirm
   the bubble matches the “Rendered guest message” section below.
6. Do **not** create a free-form session message for business-initiated invoices.

## Parameter mapping (code → Meta)

| Slot | Meaning | Example value supplied by code |
| --- | --- | --- |
| `{{1}}` | Guest first / name only | `Rajesh` |
| `{{2}}` | Brand display (title case) | `Spice Multicuisine` / `Irish Barrel House Bar` |
| `{{3}}` | Invoice / order number | `SPC/2287/2026-27` |
| `{{4}}` | Amount **without** ₹ (template already has ₹) | `6,362.00` |

App send path: `pos_invoice_whatsapp.send_pos_invoice_whatsapp` →
`whatsapp_client.send_template_message` with `body_parameters` = those four
strings and `header_document_id` = uploaded PDF media id.

## Rendered guest message (what they should see)

```
Dear Rajesh,

Thank you for dining at *Spice Multicuisine*.

Invoice: *SPC/2287/2026-27*

Amount: *₹6,362.00*

We look forward to serving you again!
```

WhatsApp turns `*…*` into bold. The PDF rides in the DOCUMENT header.

## Why ₹ is in the template, not `{{4}}`

`Amount: *₹{{4}}*` with `{{4}} = 6,362.00` produces `*₹6,362.00*` and avoids a
double ₹ if someone later formats the param with a currency symbol. Do not
change code to send `₹6,362.00` unless the Meta body is also changed to
`Amount: *{{4}}*` (no ₹ in the static text).


## Sender number (Cloud API "from")

All Hotel Bell Elite WhatsApp sends (including this POS invoice template) go
**from** **+91 96112 32344** (E.164 `+919611232344` / digits `919611232344`).

Meta Cloud API does **not** put that number in the HTTP body. The sender is the
`phone_number_id` in the Graph URL (`/{phone_number_id}/messages` and
`/{phone_number_id}/media`).

| Env | Value |
| --- | --- |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta id for +91 96112 32344 — `1241737459022736` |
| `WHATSAPP_SENDER_E164` | `+919611232344` (optional check; refuses send if Graph display number for the id does not match) |

Do **not** use the shared-WABA Neeraj Tex id (`1213272865195663` / +91 94742 41325)
for HBE outbound. See `whatsapp_client.HBE_WHATSAPP_PHONE_NUMBER_ID`.
