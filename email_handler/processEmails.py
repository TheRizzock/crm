import os
import json
import sys
from send_emails import send_template_email
import re

import dns.resolver

def check_domain_dns(domain):
    result = {
        "domain": domain,
        "has_mx": False,
        "mx_records": [],
        "has_a_record": False,
        "status": "unknown"
    }

    # Check MX records
    try:
        mx_records = dns.resolver.resolve(domain, 'MX')
        result["has_mx"] = True
        result["mx_records"] = [str(r.exchange).rstrip('.') for r in mx_records]
    except dns.resolver.NoAnswer:
        result["has_mx"] = False
    except dns.resolver.NXDOMAIN:
        result["status"] = "invalid_domain"
        return result
    except Exception as e:
        result["status"] = f"mx_error: {e}"
        return result

    # Check A record (fallback mail servers sometimes use this)
    try:
        dns.resolver.resolve(domain, 'A')
        result["has_a_record"] = True
    except:
        result["has_a_record"] = False

    # Determine status
    if result["has_mx"]:
        result["status"] = "valid_mx"
    elif result["has_a_record"]:
        result["status"] = "no_mx_but_a_record"
    else:
        result["status"] = "no_mail_servers"

    return result

def analyze_email(email):
    domain = email.split("@")[-1].lower()
    dns_result = check_domain_dns(domain)

    return {
        "email": email,
        **dns_result
    }

def is_valid_email(email):
    if not email:
        return False

    # basic format check
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not re.match(pattern, email):
        return False

    # extra sanity checks
    if ".." in email:
        return False

    return True


SKIP_STATUSES = {"sent", "delivered", "bounced", "skipped"}


def process_apify_leads(filename):
    with open(filename) as contact_data:
        contact_data = json.load(contact_data)

    for contact in contact_data:
        if contact.get("send_status") in SKIP_STATUSES:
            continue

        email = contact.get("email")
        first_name = contact.get("first_name", "")

        if not is_valid_email(email):
            print(f"❌ Skipping invalid email: {email}")
            continue

        analyzed_email = analyze_email(email)
        if analyzed_email["status"] == "no_mx_but_a_record":
            print(f"⚠️ Sketchy domain (no MX): {email}")
            continue  # optional: you could allow these if you want

            # ✅ Safe to send
        print(f"✅ Sending to: {first_name} ({email})")

        print(first_name, contact.get('last_name'), email, contact.get('job_title'))

        send_template_email(
            "90376431-09d5-4e5d-8981-24a072db23f5",
            first_name,
            email
        )



if __name__ == "__main__":
    pathname = '../data/raw_leads/chunks'
    process_apify_leads(os.path.join(pathname, "net_new_leads_3.json"))