import os
import json
import sys

SKIP_STATUSES = {"sent", "delivered", "bounced", "skipped"}

STATUS_OPTIONS = {
    "s": "sent",
    "d": "delivered",
    "b": "bounced",
    "x": "skipped",
    "q": None,  # quit
}


def load_contacts(filepath):
    with open(filepath) as f:
        return json.load(f)


def save_contacts(filepath, contacts):
    with open(filepath, "w") as f:
        json.dump(contacts, f, indent=2)


def prompt_status(contact):
    email = contact.get("email", "")
    first = contact.get("first_name", "")
    last = contact.get("last_name", "")
    title = contact.get("job_title", "")
    company = contact.get("company_name", "")

    print("\n" + "=" * 60)
    print(f"  Name   : {first} {last}")
    print(f"  Title  : {title}")
    print(f"  Company: {company}")
    print(f"  Email  : {email}")
    print("-" * 60)
    print("  [s] sent   [d] delivered   [b] bounced   [x] skip   [q] quit")

    while True:
        choice = input("  Status: ").strip().lower()
        if choice in STATUS_OPTIONS:
            return STATUS_OPTIONS[choice]
        print("  Invalid choice. Enter s, d, b, x, or q.")


def run(filepath):
    contacts = load_contacts(filepath)
    total = len(contacts)
    pending = [i for i, c in enumerate(contacts) if c.get("send_status") not in SKIP_STATUSES]

    print(f"\nLoaded {total} contacts. {len(pending)} pending (no status yet).")

    for idx in pending:
        contact = contacts[idx]
        status = prompt_status(contact)

        if status is None:
            print("\nQuitting. Progress saved.")
            save_contacts(filepath, contacts)
            return

        contact["send_status"] = status
        save_contacts(filepath, contacts)  # save after each entry
        print(f"  Marked as: {status}")

    print("\nAll contacts processed.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # default to the same file processEmails.py uses
        filepath = os.path.join(os.path.dirname(__file__), "../data/raw_leads/chunks/net_new_leads_3.json")
    else:
        filepath = sys.argv[1]

    filepath = os.path.abspath(filepath)
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    run(filepath)
