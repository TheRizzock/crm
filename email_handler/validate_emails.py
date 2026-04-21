"""
Bulk email validation via ZeroBounce API.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DEFAULT INPUT FILE:
    data/raw_leads/all_leads.json   ← run consolidate_chunks.py first

  OVERRIDE: pass any .json file(s) as arguments
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Usage:
    python email_handler/validate_emails.py
    python email_handler/validate_emails.py path/to/file.json
    python email_handler/validate_emails.py --force          # re-validate even if zb_status exists

Skips contacts where send_status == "sent" (no point burning credits on already-sent emails).
ZeroBounce batch endpoint: up to 200 emails per request.
Results written back into the same file: zb_status, zb_sub_status, zb_free_email, zb_did_you_mean.

Requires ZEROBOUNCE_API_KEY in .env or environment.
"""

import os
import sys
import json
import time
import glob
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_KEY = os.getenv("ZEROBOUNCE_API_KEY")
BATCH_ENDPOINT = "https://api.zerobounce.net/v2/validatebatch"
BATCH_SIZE = 200  # ZeroBounce max per request

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DEFAULT INPUT — change this if your consolidated file lives elsewhere
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEFAULT_INPUT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../data/raw_leads/all_leads.json")
)


def load_contacts(filepath):
    with open(filepath) as f:
        return json.load(f)


def save_contacts(filepath, contacts):
    with open(filepath, "w") as f:
        json.dump(contacts, f, indent=2)


def validate_batch(emails: list[dict]) -> dict[str, dict]:
    payload = {"api_key": API_KEY, "email_batch": emails}
    resp = requests.post(BATCH_ENDPOINT, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    results = {}
    for item in data.get("email_batch", []):
        addr = item.get("address", "").lower()
        results[addr] = {
            "zb_status": item.get("status"),
            "zb_sub_status": item.get("sub_status"),
            "zb_free_email": item.get("free_email"),
            "zb_did_you_mean": item.get("did_you_mean") or None,
        }
    return results


def process_file(filepath: str, force: bool = False) -> None:
    contacts = load_contacts(filepath)
    total = len(contacts)

    skipped_sent = sum(1 for c in contacts if c.get("send_status") == "sent")

    to_validate = [
        i for i, c in enumerate(contacts)
        if c.get("email")
        and c.get("send_status") != "sent"          # never re-validate already-sent
        and (force or not c.get("zb_status"))
    ]

    log.info("━" * 60)
    log.info("File     : %s", filepath)
    log.info("Total    : %d contacts", total)
    log.info("Skipped  : %d (send_status=sent — no credits wasted)", skipped_sent)
    log.info("To validate: %d", len(to_validate))
    log.info("━" * 60)

    if not to_validate:
        log.info("Nothing to validate in this file.")
        return

    batches = [to_validate[i:i + BATCH_SIZE] for i in range(0, len(to_validate), BATCH_SIZE)]

    for batch_num, batch_indices in enumerate(batches, 1):
        email_payloads = [
            {"email_address": contacts[i]["email"], "ip_address": ""}
            for i in batch_indices
        ]

        log.info("  Batch %d/%d — %d emails", batch_num, len(batches), len(email_payloads))

        try:
            results = validate_batch(email_payloads)
        except requests.HTTPError as e:
            log.error("  HTTP error on batch %d: %s", batch_num, e)
            continue
        except Exception as e:
            log.error("  Unexpected error on batch %d: %s", batch_num, e)
            continue

        for i in batch_indices:
            email = contacts[i]["email"].lower()
            zb = results.get(email, {})
            contacts[i].update(zb)

        save_contacts(filepath, contacts)
        log.info("  Saved after batch %d.", batch_num)

        if batch_num < len(batches):
            time.sleep(1)

    valid_count = sum(
        1 for c in contacts
        if c.get("zb_status") == "valid" and c.get("send_status") != "sent"
    )
    log.info("Done. %d validated as valid (excludes already-sent).", valid_count)


def print_summary(filepaths: list[str]) -> None:
    totals = {"valid": 0, "invalid": 0, "catch-all": 0, "unknown": 0, "other": 0, "not_run(sent)": 0}
    for fp in filepaths:
        contacts = load_contacts(fp)
        for c in contacts:
            if c.get("send_status") == "sent":
                totals["not_run(sent)"] += 1
                continue
            status = c.get("zb_status")
            if status in totals:
                totals[status] += 1
            elif status:
                totals["other"] += 1

    print("\n" + "━" * 40)
    print("  ZeroBounce Validation Summary")
    print("━" * 40)
    for k, v in totals.items():
        print(f"  {k:<20}: {v}")
    print("━" * 40 + "\n")


def main():
    if not API_KEY:
        log.error("ZEROBOUNCE_API_KEY is not set. Add it to your .env or environment.")
        sys.exit(1)

    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        filepaths = [os.path.abspath(a) for a in args]
    else:
        filepaths = [DEFAULT_INPUT]

    missing = [fp for fp in filepaths if not os.path.exists(fp)]
    if missing:
        for fp in missing:
            log.error("File not found: %s", fp)
        if DEFAULT_INPUT in missing:
            log.error("Run consolidate_chunks.py first to generate all_leads.json.")
        sys.exit(1)

    log.info("Processing %d file(s).", len(filepaths))
    for fp in filepaths:
        process_file(fp, force=force)

    print_summary(filepaths)


if __name__ == "__main__":
    main()
