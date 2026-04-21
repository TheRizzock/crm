# CRM CLI Usage

Run all commands from the project root as `./crm <command>`.

---

## First-time setup

```bash
# 1. Configure sender, template, and preferences
./crm config init

# 2. Set the active leads file
./crm validate set-file
```

Config is saved to `.cli_config.json`. Session state (active file) is saved to `.cli_state.json`. Neither is committed to git.

---

## Full workflow

```
consolidate_chunks.py  →  config init  →  validate set-file  →  validate run  →  send schedule
```

1. **Consolidate** raw chunk files into one master list
2. **Configure** sender address, template ID, timezone, etc.
3. **Set** the active file
4. **Validate** emails via ZeroBounce
5. **Schedule** sends

---

## Commands

### `config`

#### `config init`
Interactive setup wizard — walks through every config field.

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
| `test_email` | | — | Email address for test sends |
| `timezone` | | `America/New_York` | Scheduling timezone |
| `eod_hour` | | `17` | End-of-day cutoff hour (24h) |
| `default_tier` | | `1` | Default warming tier (1–4) |

> `send schedule` will block with a clear error if `from_address` or `template_id` are not set.

---

### `validate`

#### `validate set-file`
Set the active leads file. Persists across sessions.

```bash
./crm validate set-file                                 # interactive picker
./crm validate set-file data/raw_leads/all_leads.json  # direct path
```

#### `validate stats`
Count contacts ready to validate — checks email format, MX records, and ZeroBounce status.

```bash
./crm validate stats
```

Output includes total contacts, already sent (skipped), already ZeroBounced, pending count, and MX record breakdown.

#### `validate run`
Validate emails via ZeroBounce. Contacts with `send_status: sent` are always skipped.

```bash
./crm validate run --all          # validate every remaining contact
./crm validate run --number 10    # validate the next 10 (good for testing)
./crm validate run --all --force  # re-validate even if zb_status already set
```

Results written back to the file per contact:

| Field | Description |
|---|---|
| `zb_status` | `valid`, `invalid`, `catch-all`, `unknown`, `abuse`, `do_not_mail` |
| `zb_sub_status` | More detail (e.g. `mailbox_not_found`, `role_based`) |
| `zb_free_email` | `true` if Gmail/Yahoo/etc. |
| `zb_did_you_mean` | Suggested correction if ZB detects a typo |

---

### `send`

#### `send schedule`
Pick a random batch of validated contacts and scatter their send times between now and end of business.

```bash
./crm send schedule                        # use config defaults, real send
./crm send schedule --mock                 # preview only — nothing sent, no API calls
./crm send schedule --tier 2              # override warming tier
./crm send schedule --tier 3 --mock       # preview a medium batch
./crm send schedule --tz America/Chicago  # override timezone for this run
```

**Warming tiers:**

| Tier | Label | Emails per run |
|------|-------|---------------|
| `1` | Warmup | 5–15 |
| `2` | Light | 15–30 |
| `3` | Medium | 30–60 |
| `4` | Full | 60–100 |

**Sendable contacts** must have:
- `zb_status` of `valid` or `catch-all`
- `send_status` not `sent`, `delivered`, `bounced`, or `skipped`

**Mock mode** prints the full preview table (Name, Title, Email, ZB Status, Send Status, Scheduled Time, Template ID) with no API calls.

**Real mode** shows the same table then asks:
```
Send N emails as scheduled above? [y/N]:
```
On approval, each email is fired to Resend with a `scheduled_at` timestamp (UTC). The file is updated with `send_status: sent` + `resend_id` after each one. Sends are rate-limited to 4/sec.

---

## One-off scripts

These live in `email_handler/` and run standalone outside the CLI:

| Script | What it does |
|---|---|
| `consolidate_chunks.py` | Merges all `net_new_leads_*.json` chunks into `data/raw_leads/all_leads.json`. Marks chunks 1 & 2 as `send_status: sent`. |
| `validate_emails.py` | Standalone ZeroBounce bulk validator (same logic as `validate run`). Default input: `all_leads.json`. |
| `manualSend.py` | Interactive terminal tool to manually mark send statuses contact by contact. |

---

## Environment variables

Add to `.env` in the project root (never committed):

```
ZEROBOUNCE_API_KEY=your_key_here
RESEND_API_KEY=your_key_here
```
