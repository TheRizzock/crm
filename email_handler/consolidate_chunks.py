"""
Consolidates all net_new_leads_*.json chunk files into a single
data/raw_leads/all_leads.json file.

Rules:
  - Contacts from chunks 1 & 2 get send_status = "sent" (already sent, skip re-send)
  - Existing send_status values on other chunks are preserved
  - Deduplicates by email (first occurrence wins)

Usage:
    python email_handler/consolidate_chunks.py
"""

import os
import sys
import re
import json
import glob
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CHUNKS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/raw_leads/chunks"))
OUTPUT_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/raw_leads/all_leads.json"))

ALREADY_SENT_CHUNKS = {1, 2}


def chunk_number(filepath: str) -> int:
    match = re.search(r"net_new_leads_(\d+)\.json$", filepath)
    return int(match.group(1)) if match else 999


def main():
    chunk_files = sorted(
        glob.glob(os.path.join(CHUNKS_DIR, "net_new_leads_*.json")),
        key=chunk_number,
    )

    if not chunk_files:
        log.error("No chunk files found in %s", CHUNKS_DIR)
        sys.exit(1)

    log.info("Found %d chunk files.", len(chunk_files))

    seen_emails = set()
    all_contacts = []
    stats = {"total": 0, "dupes": 0, "marked_sent": 0}

    for filepath in chunk_files:
        chunk_num = chunk_number(filepath)
        with open(filepath) as f:
            contacts = json.load(f)

        for contact in contacts:
            stats["total"] += 1
            email = (contact.get("email") or "").strip().lower()

            if email and email in seen_emails:
                stats["dupes"] += 1
                log.debug("Dupe skipped: %s", email)
                continue

            if email:
                seen_emails.add(email)

            if chunk_num in ALREADY_SENT_CHUNKS:
                contact["send_status"] = "sent"
                stats["marked_sent"] += 1

            all_contacts.append(contact)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_contacts, f, indent=2)

    log.info("=== Consolidation complete ===")
    log.info("  Chunks processed : %d", len(chunk_files))
    log.info("  Total contacts   : %d", stats["total"])
    log.info("  Duplicates skipped: %d", stats["dupes"])
    log.info("  Marked as sent   : %d (chunks 1 & 2)", stats["marked_sent"])
    log.info("  Written to       : %s", OUTPUT_FILE)
    log.info("  Final count      : %d", len(all_contacts))


if __name__ == "__main__":
    main()
