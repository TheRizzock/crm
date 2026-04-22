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

## Environment variables

Add to `.env` in the project root (never committed):

```
DATABASE_URL=your_db_url_here
ZEROBOUNCE_API_KEY=your_key_here
RESEND_API_KEY=your_key_here
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
