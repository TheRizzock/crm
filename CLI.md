# CRM CLI Usage

Run all commands from the project root as `./crm <command>`.

---

## First-time setup

```bash
# 1. Apply database migrations
alembic upgrade head

# 2. Configure sender, template, and preferences
./crm config init
```

Config is saved to `.cli_config.json`. Not committed to git.

---

## Full workflow

```
crm import run  →  crm validate run  →  crm send schedule
```

1. **Import** leads from a JSON file into the database (deduplicates companies + contacts)
2. **Validate** contact emails via ZeroBounce — results written to `Contact` in the DB
3. **Schedule** sends — each send creates an `Activity(type='email')` record in the DB

---

## Commands

### `config`

#### `config init`
Interactive setup wizard.

```bash
./crm config init
```

#### `config show`
Display current config.

```bash
./crm config show
```

#### `config set`
Set a single field directly.

```bash
./crm config set from_address "Dan Kowalsky <dan@yourdomain.com>"
./crm config set template_id  "your-resend-template-id"
./crm config set subject      "Quick question"
./crm config set test_email   "you@yourdomain.com"
./crm config set timezone     "America/Chicago"
./crm config set eod_hour     17
./crm config set default_tier 2
```

**Config fields:**

| Field | Required | Default | Description |
|---|---|---|---|
| `from_address` | ✓ | — | Sender name + email shown to recipients |
| `template_id` | ✓ | — | Resend template ID |
| `subject` | | — | Email subject (stored on Activity record) |
| `test_email` | | — | Email address for test sends |
| `timezone` | | `America/New_York` | Scheduling timezone |
| `eod_hour` | | `17` | End-of-day cutoff hour (24h) |
| `default_tier` | | `1` | Default warming tier (1–4) |

---

### `import`

#### `import run`
Import leads from a JSON file into the database. Upserts `Company` and `Contact` records,
deduplicates, and prompts for action on any conflicts found.

```bash
./crm import run                                            # interactive file picker
./crm import run data/raw_leads/chunks/net_new_leads_3.json # direct path
./crm import run --dry-run                                  # preview without writing
./crm import run --auto-merge                               # merge all dupes without prompting
```

**Deduplication logic:**

| Match type | Confidence | Default action |
|---|---|---|
| Email address | High | Prompt: merge or skip |
| LinkedIn URL | High | Prompt: merge or skip |
| First + last name | Low | Prompt: merge, skip, or create new |

When merging, only null fields on the existing record are filled — existing data is never overwritten.
Companies are always auto-merged (null fields filled, no prompt needed).

**ZeroBounce fields** (`zb_status`, `zb_sub_status`, etc.) are imported if present in the file, skipped if null.

---

### `validate`

#### `validate stats`
Show ZeroBounce validation status across all contacts in the database. Checks MX records for pending contacts.

```bash
./crm validate stats
```

Output includes total contacts, no-email count, already validated, pending count, MX breakdown, and a ZB status breakdown.

#### `validate run`
Validate contact emails via ZeroBounce. Skips contacts that have already been emailed (no point burning credits).

```bash
./crm validate run --all           # validate every pending contact
./crm validate run --number 50     # validate the next 50
./crm validate run --all --force   # re-validate even if zb_status already set
```

Results written to the `Contact` record in the database:

| Field | Description |
|---|---|
| `zb_status` | `valid`, `invalid`, `catch-all`, `unknown`, `abuse`, `do_not_mail` |
| `zb_sub_status` | More detail (e.g. `mailbox_not_found`, `role_based`) |
| `zb_free_email` | `true` if Gmail/Yahoo/etc. |
| `zb_did_you_mean` | Suggested correction if ZB detects a typo |
| `email_validated_at` | Timestamp of when validation ran |

---

### `send`

#### `send test`
Send a one-off test email to verify deliverability and spam placement.

```bash
./crm send test
./crm send test you@yourdomain.com
```

#### `send schedule`
Pick a random batch of validated contacts and scatter their send times between now and end of business.
Creates an `Activity(type='email')` record per contact on send.

```bash
./crm send schedule                          # never-emailed contacts, config defaults
./crm send schedule --mock                   # preview only — nothing sent
./crm send schedule --tier 2                 # override warming tier
./crm send schedule --days-since 7           # include contacts not emailed in 7+ days (follow-ups)
./crm send schedule --tier 3 --mock          # preview a medium batch
./crm send schedule --tz "America/Chicago"   # override timezone for this run
```

**Warming tiers:**

| Tier | Label | Emails per run |
|---|---|---|
| `1` | Warmup | 5–15 |
| `2` | Light | 15–30 |
| `3` | Medium | 30–60 |
| `4` | Full | 60–100 |

**Sendable contacts** must have:
- `zb_status` of `valid` or `catch-all`
- No prior email activity (default), OR last email older than `--days-since N` days

**Each sent email creates an Activity with:**
- `type = "email"`
- `subject` — from config (if set)
- `body` — Resend template ID
- `status = "scheduled"`
- `resend_id` — Resend's message ID (for webhook reconciliation)

---

### `scrape`

Scrape company websites to hydrate missing fields using GPT-4.1-nano for extraction.
Only fills null fields by default — existing data is never overwritten unless `--force` is passed.

#### `scrape detect-company`
Detect and save a website URL for a single company that doesn't have one.
Tries the `domain` field first, then asks GPT. Validates every candidate with a HEAD request before saving.

```bash
./crm scrape detect-company <company_id>
./crm scrape detect-company <company_id> --yes   # skip confirmation
```

#### `scrape detect`
Batch find websites for all companies that don't have one. Prioritises companies that already have a `domain` or LinkedIn URL.

```bash
./crm scrape detect --limit 20          # process up to 20 companies
./crm scrape detect --dry-run           # preview candidates without making requests
./crm scrape detect --limit 20 --yes    # auto-save without prompting
```

#### `scrape company`
Scrape a single company's website and hydrate missing fields. If the company has no website, detection is attempted automatically first.

```bash
./crm scrape company <company_id>
./crm scrape company <company_id> --yes      # auto-approve changes
./crm scrape company <company_id> --force    # overwrite existing values too
```

#### `scrape run`
Batch scrape companies, prioritised by most missing fields. Companies without a website have detection attempted automatically before scraping.

```bash
./crm scrape run                    # top 10 companies with most missing fields
./crm scrape run --limit 25         # process up to 25
./crm scrape run --dry-run          # preview queue without any requests
./crm scrape run --yes              # auto-approve all changes
./crm scrape run --yes --force      # auto-approve + overwrite existing values
```

**Fields populated from scraping:**

| Field | Source |
|---|---|
| `description` | GPT-written summary from homepage/about content |
| `phone` | Main office number from contact/about pages |
| `street_address`, `full_address`, `city`, `state`, `country`, `postal_code` | Address from contact page |
| `founded_year` | About page |
| `technologies` | Tech stack mentioned on the site |

**Single-company workflow:**
```bash
crm scrape detect-company <id>   # find the website
crm scrape company <id>          # hydrate fields
```

---

### `enrich`

Find missing contact information (email, phone, etc.) by scraping company team pages
and inferring email patterns from colleagues at the same company.

#### `enrich contact`
Enrich a single contact.

```bash
./crm enrich contact <contact_id>
./crm enrich contact <contact_id> --yes      # auto-approve changes
./crm enrich contact <contact_id> --force    # overwrite existing values too
```

#### `enrich run`
Batch enrich contacts missing a specific field. Prioritises contacts whose company has a website.

```bash
./crm enrich run                          # find emails for up to 20 contacts
./crm enrich run --limit 50               # process up to 50
./crm enrich run --missing mobile_number  # target a different field
./crm enrich run --missing any            # target any missing field
./crm enrich run --dry-run                # preview candidates without processing
./crm enrich run --yes                    # auto-approve all changes
./crm enrich run --yes --force            # auto-approve + overwrite existing values
```

**How enrichment works for each contact:**

1. **Email pattern inference** (free, instant) — checks if other contacts at the same company already have emails, infers the format (`first.last@`, `flast@`, etc.), and constructs a suggestion. Requires at least one known colleague email.
2. **Team page scraping** — hits the company's `/team`, `/leadership`, `/people`, `/about` pages, checks if the contact's name appears, then asks GPT to extract any email or phone found near their name.

The diff table shows the proposed value and its source (`pattern` or `scraped`) so you can judge confidence before approving.

---

### `workflow`

Guided, interactive workflows that chain multiple enrichment steps together.

#### `workflow companies`
Lists all companies sorted by how much they need attention (fewest contacts + most missing fields first), ten at a time. Select a company by number to run the full pipeline for it.

```bash
./crm workflow companies
```

**Navigation:**
| Input | Action |
|---|---|
| `1`–`10` | Select company by position on current page |
| `n` | Next page |
| `p` | Previous page |
| `q` | Quit |

**Per-company pipeline (three steps):**

1. **Scrape company details** — hydrates missing fields from the company's website (same as `scrape company`).
2. **Enrich existing contacts** — finds missing emails/phones for contacts already in the CRM (same as `enrich run` scoped to this company). Asks for confirmation before running.
3. **Discover new contacts** — scrapes the team page for new people to add (same as `enrich discover-contacts` scoped to this company). Asks for confirmation before running.

The candidate list refreshes after each company is processed so scores stay accurate as you work through the queue.

---

### `backfill`

One-time commands for data cleanup. Safe to run more than once (idempotent).

#### `backfill linkedin-activities`
Creates a `linkedin` activity for every contact that doesn't already have one, dated at the contact's `created_at`. Useful since all existing contacts came from LinkedIn outreach.

```bash
./crm backfill linkedin-activities --dry-run   # preview
./crm backfill linkedin-activities             # run it
```

---

## Activity types

All outreach is tracked as `Activity` records on a contact.

| `type` | When created |
|---|---|
| `email` | Created automatically by `send schedule` |
| `linkedin` | Created manually or via `backfill linkedin-activities` |
| `phone` | Created manually via the API |

---

### `sync-resend`

Backfill email statuses from Resend for any `Activity` record still marked `scheduled`.
Emails start life as `scheduled` when queued via `send schedule` — this pulls the actual
delivery outcome from Resend and updates the record.

```bash
python -m cli.sync_resend              # interactive — preview list, pick one or all
python -m cli.sync_resend --all        # update every null-status activity
python -m cli.sync_resend --dry-run    # preview what would change, no writes
python -m cli.sync_resend --limit 200  # cap records inspected (default 500)
```

Interactive mode shows a table of all null-status emails, then prompts:
- Enter a row number to update just that one
- `a` to update all
- `q` to quit

---

## Webhook setup (Resend → activity status)

Resend fires webhook events when an email is delivered, bounced, opened, or clicked.
The app receives these at `POST /webhooks/resend` and updates the matching `Activity.status`.

### 1. Add the signing secret

In the Resend dashboard → **Webhooks** → create a new endpoint, copy the **Signing Secret** (`whsec_...`), then add it to `.env`:

```
RESEND_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxxxxxxxxxxx
```

> Without this variable the endpoint still works but skips signature verification — set it before exposing the URL in production.

### 2. Register the endpoint in Resend

Point Resend to your server's public URL:

```
POST https://<your-domain>/webhooks/resend
```

Subscribe to these events:

| Event | Maps to `Activity.status` |
|---|---|
| `email.sent` | `sent` |
| `email.delivered` | `delivered` |
| `email.bounced` | `bounced` |
| `email.opened` | `opened` |
| `email.clicked` | `clicked` |
| `email.complained` | `bounced` |

### 3. Backfill historical sends

Run the sync script to catch up on emails sent before the webhook was active:

```bash
python -m cli.sync_resend --dry-run   # preview
python -m cli.sync_resend --all       # apply
```

---

## Environment variables

Add to `.env` in the project root (never committed):

```
DATABASE_URL=your_db_url_here
ZEROBOUNCE_API_KEY=your_key_here
RESEND_API_KEY=your_key_here
RESEND_WEBHOOK_SECRET=whsec_your_signing_secret_here
OPENAI_API_KEY=your_key_here
```

---

## Legacy scripts (no longer used)

These files in `email_handler/` predate the database migration and are no longer part of the workflow:

| File | Replaced by |
|---|---|
| `consolidate_chunks.py` | `crm import run` |
| `validate_emails.py` | `crm validate run` |
| `processEmails.py` | `crm send schedule` |
| `manualSend.py` | `crm send test` |
