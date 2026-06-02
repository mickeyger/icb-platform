# GRP Costings System — User Guide

This is the knowledge base for the AI Help assistant. It describes the app the way a user sees it — menus, screens, buttons, and what each one does. Internal names, code, database details, and technical wording are deliberately left out.

The sidebar nav is grouped:

- **Main** — Dashboard, Cost Calculator, Cost Calculator 2
- **Bodies** — Body Templates (with sub-links: Formula Scan, Settings, Configurator preview, Body Designer)
- **Chassis** — Chassis Options
- **Pricing Formulas** — Floor Plates, Mounting Cleats, SAP Prices, Skin Formulas, Taping Blocks
- **BOM** — Materials & Prices, Formulas, BOM Snapshots
- **Form Setup** — PDF Templates, Quote Templates, Template Builder
- **User Setup** — Customers, GRP Import, Import from Excel, Manage Users, Themes, User View Permissions, Quote Numbering

The labels on the nav-group headings ("Bodies", "BOM", etc.) are renameable by admins. If a user can't find a heading, suggest they look for the equivalent area or check User View Permissions to confirm their access.

---

## Running a costing (the core daily task)

Two calculators ship with the app:

- **Cost Calculator** — the original UI, optimised for the full BOM workflow.
- **Cost Calculator 2** — same engine, alternate UX. Some bodies have certain items pre-set to be excluded from Calculator 2 by default.

Typical flow:

1. Pick a **Body Template** from the dropdown at the top. The page loads its BOM (Bill of Materials) and chassis options.
2. Pick a **Chassis** selection. The chassis cost is added to the body cost.
3. Adjust **Dimensions** (length, width, height in metres) if needed — the BOM re-evaluates live.
4. Toggle **Optional Extras** sections on/off. Sections marked as optional start greyed-out and render in red so users see they are off by default.
5. (Calc 2 only) Toggle individual BOM items with the per-line checkbox.
6. Review the **Results** — line items with unit price and extended cost, grouped by category, plus a grand total.
7. **Save** the costing (gives it a quote number) or **Generate Quote PDF** for the customer.
8. Optionally **Mark as accepted / declined** to feed approval-rate stats on the dashboard.

If a line shows **R0** unexpectedly, the usual causes are:

- The material has no price set in Materials & Prices.
- The line uses a formula that depends on a Body Variable that hasn't been set.
- The line is linked to a sub-recipe (skin formula, taping block, floor plate, mounting cleat) that has no ingredients yet.

Tell the user to check Materials & Prices for the material in question, or open the body in Body Templates and inspect that line.

---

## Bodies: managing Body Templates

**Bodies > Body Templates** is the master list of trailer body types (e.g. "Insulated 8m", "Curtainside 14m").

### Creating a new body type

1. Click **+ New Body Template**.
2. Give it a name, optional description, default length/width/height (in metres), and markup %.
3. Save — the new body appears in the list with an empty BOM.

### Adding BOM items to a body type

This is the most-asked question. The flow:

1. Open the body template (click its row in Body Templates).
2. The BOM editor shows existing items grouped by **BOM Section** (e.g. CHASSIS, FLOOR, WALLS).
3. Click **Add Section** to create a new section, or expand an existing section and click **Add Item**.
4. For each item: pick the **Material** from the picker, enter a **Formula** for the quantity (placeholders like {LENGTH}, {WIDTH}, {HEIGHT} are available, plus named formulas from BOM > Formulas, plus any Body Variables defined on the body), and a sort order.
5. (Optional) Mark the item as a **Body Option** to make it user-toggleable on the calculator. Assign it to a **Body Option Group** and optional **Subgroup** so it appears under a labelled checklist (single-select for radio-style, multi-select for checkbox-style).
6. (Optional) Add **Conditions** so the item only appears when other options are picked.
7. Save.

### Linking sub-recipes (skin formulas, taping blocks, floor plates, mounting cleats)

Instead of an individual material, a BOM line can reference a composite **sub-recipe**. The unit price then comes from the sub-recipe's own ingredient list. Create the sub-recipes under Pricing Formulas first, then link them on the BOM line.

### BOM sections

- Edit a section's name and multiplier inline.
- Mark a section as **Optional Extras** to make it render red and start greyed-out on the calculators.
- Archive a section to hide it from costings without deleting it.
- Sections can be tied to a master Body Option so they only appear when that option is picked.

### Configurator v2

Each body has a **Configurator v2** toggle in Body Templates. When on, the calculator honours the newer configurator features (archived sections, conditional rows, option-master ownership). When off, only the legacy behaviour runs. Roll-out is per body so it can be flipped back instantly.

### Body Designer

**Bodies > Body Designer** is a visual editor for assembling body options into a configurator tree. Useful for complex bodies with many user choices.

---

## Chassis

**Chassis > Chassis Options** lists every chassis variant (make/model/axles/length) with its cost. The page also holds **Chassis Constants** — named numeric values referenced by chassis-cost formulas.

To add a new chassis: click **+ New Chassis**, fill the fields (name, axles, GVM, base cost, etc.), save. It becomes selectable in the chassis dropdown on the calculator.

---

## Pricing Formulas (sub-recipes)

These five pages let admins define reusable composite costings that BOM lines then reference:

- **Floor Plates** — sheet-good plate recipes with an optional price formula (e.g. derives price from area).
- **Mounting Cleats** — cleat assemblies (material + cut lengths).
- **SAP Prices** — SAP item code catalogue. Used as an alternative price source on skin/taping items.
- **Skin Formulas** — composite skin assemblies. Each formula has ingredient lines; each ingredient picks either the master material price or the linked SAP price.
- **Taping Blocks** — similar to skin formulas but for taping/edge assemblies.

Admins who have the right permission can edit prices on skin and taping lines inline.

---

## BOM: Materials & Prices

**BOM > Materials & Prices** is the master materials list.

### Updating a price in a costing

Two ways:

- **Update the master price** (preferred, affects every body): BOM > Materials & Prices > find the material by name, SAP code, or material code > click the price cell > type the new value > Enter. Every body that uses this material reprices the next time the BOM loads.
- **Override the price on one BOM line for one body**: open the costing in the **Cost Calculator** (Main > Cost Calculator), load the body, then **right-click the BOM line** in the results and use the price-editing dialog that appears. This sets a per-line override that sticks for that body only; the master price stays as it was. Bodies that have overrides protection enabled are also exempt from bulk material price propagation.

(The right-click menu on a BOM row in **Bodies > Body Templates** is a different thing — that opens the line editor for changing the material, formula, options, etc. To edit a *price override*, do it in the Cost Calculator as described above.)

### Bulk price updates

Materials & Prices has a **Bulk Update** action (and a separate Import flow under User Setup) that lets the user upload a price-change Excel sheet. Every updated material gets a "last bulk update" timestamp and note recorded against it.

### Filtering and grouping

Materials & Prices has a filter by **sub-category** (the source sheet name in the original price-list Excel), plus a "group by sub-category" view.

### Formulas

**BOM > Formulas** is the named-formula library. Any BOM line's formula can reference these by name in braces. There's also an "Apply to BOM" tool that propagates a formula change across every BOM line that uses it.

### BOM Snapshots

**BOM > BOM Snapshots** lets admins freeze a body's BOM at a point in time (e.g. before a price change). Snapshots are read-only and can be compared side-by-side. One snapshot per body can be **pinned** as the approved baseline.

---

## Form Setup

- **PDF Templates** — visual PDF templates for printed costings.
- **Quote Templates** — HTML report templates for customer-facing quotes.
- **Template Builder** — WYSIWYG editor for PDF templates.

A trailer's quote/report template is picked in this order: the per-trailer override (if set), otherwise the default template assigned to the trailer's group.

---

## User Setup

- **Customers** — customer master list. Picked on a costing for quote generation.
- **GRP Import** + **Import from Excel** — bring materials and prices in from spreadsheets.
- **Manage Users** — add/remove users, set role (admin / full / user), reset passwords.
- **Themes** — switch between the blue (default) and red IceCold themes; admins can create new themes.
- **User View Permissions** — fine-grained per-user permission overrides on top of role defaults.
- **Quote Numbering** — configure the auto-incrementing quote-number format.

### Permissions you might be asked about

These are the labels shown on the User View Permissions screen. Each controls one user-facing capability:

| Permission | Allows |
|---|---|
| `menu.calculator` | Open the cost calculator |
| `menu.dashboard` | See the dashboard and saved costings list |
| `menu.materials` | Access Materials & Prices |
| `menu.body_templates` | Access Body Templates |
| `menu.chassis` | Access Chassis Options |
| `menu.customers` | Access Customers |
| `menu.templates` | Access Quote Templates |
| `menu.themes` | Access Themes |
| `menu.import` | Access the import pages |
| `menu.users` | Access Manage Users |
| `menu.quote_numbering` | Access Quote Numbering |
| `menu.devtools` | Access Dev Tools |
| `bom.view_prices` | See unit prices and line costs on the costing results |
| `bom.view_full_cost` | See the grand total / cost-per-m² summary |
| `export.excel` | Download a costing as Excel |
| `export.pdf` | Download a costing as PDF |
| `quote.generate` | Generate a customer quote PDF |
| `dashboard.approval_rate` | See the Approval Rate card on the dashboard |
| `recipes.edit_inline` | Inline-edit skin/taping prices |

Admins bypass all permission checks automatically.

---

## Dashboard

The dashboard shows recent saved costings, search and filter, and per-user activity. The **Approval Rate** stats card is gated by its own permission.

---

## Comparing a costing to an Excel sheet

If the user wants to know why her in-app costing isn't balancing with the original Excel costing model, she can attach the Excel workbook to the chat:

1. Open the costing she wants to audit in **Cost Calculator** so the live BOM is on screen.
2. Click the **📎 paperclip** in the chat input row > pick the Excel workbook (.xlsx or .xls, max 5 MB).
3. A chip appears above the input showing the filename and the picked sheet. The chat auto-selects the sheet whose name best matches her body template; she can switch via the dropdown on the chip.
4. Ask "why is this not balancing with my Excel?" or "what's different between my costing and the Excel?".

The assistant compares grand totals, section totals, and individual line items, and calls out the biggest discrepancies first. It will also warn if the Excel sheet's dimensions or markup differ from the costing on screen, because that makes a like-for-like comparison invalid.

The workbook stays attached for follow-up questions in the same chat (e.g. "show me the floor line by line"). Click the **✕** on the chip to detach it, or use **Clear chat** to drop both the conversation and the attached workbook. Workbooks are auto-removed from the server after two hours; the user can re-attach if needed.

This feature needs the **`bom.view_prices`** permission (admins always have it). Without it, the paperclip refuses the upload because a reconciliation that hides prices is meaningless.

---

## Common "how do I..." answers

- **How do I add BOM items to a body type?** — Bodies > Body Templates > click the body > expand a BOM Section > Add Item. See "Adding BOM items" above for the full flow.
- **How do I update a price in a costing?** — Master price: BOM > Materials & Prices > click the price cell > type the new value. Per-line override for one body: open the costing in Cost Calculator, right-click the BOM line in the results, and use the price-editing dialog.
- **How do I create a new body type?** — Bodies > Body Templates > + New Body Template.
- **How do I save / print a costing?** — Run the costing in the Cost Calculator > Save. From the saved costing, click Generate Quote PDF or Export > PDF / Excel.
- **How do I give a user access to X?** — User Setup > Manage Users (set the role) or User View Permissions (per-permission allow / deny).
- **Why is my chassis line R0?** — The selected chassis has no base cost set in Chassis Options, or no chassis is selected.
- **Why is a BOM line R0?** — The material has no price set, or the line uses a formula whose body variable isn't set, or the linked sub-recipe (skin formula, taping block) has no ingredients.
- **How do I switch theme?** — Bottom-left of the sidebar, click the colour swatch.
- **What does Optional Extras mean?** — Sections marked optional render red on the calculator and start unchecked. Users tick the section header to include it. Optional sections also show red in the Excel and PDF exports.
- **How does pricing flow when I update a material?** — The new price takes effect the next time any body's BOM is loaded into the calculator. Existing saved costings keep the price they were saved at. Bodies that have "protect overrides" turned on are skipped during bulk propagation — their per-line price overrides stay as set.

---

## Limits the assistant has

- The assistant **cannot make changes**. It only explains how to do something, looks up data, and reasons about what the user sees.
- The assistant **respects the user's permissions**. If you ask about a screen or data your role can't access, it will tell you and suggest who to ask.
- The assistant **never reveals user credentials, sessions, or permission assignments**. That data is off-limits.
- The assistant **never reveals anything about the code, file structure, database schema, internal names, or how the app is built technically**. It explains behaviour and business logic only.
