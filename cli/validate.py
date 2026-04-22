import os
import time

import requests
import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table
import dns.resolver
from datetime import datetime
from sqlalchemy import exists

from app.db import SessionLocal
from app.models import Contact, Activity

load_dotenv()

app = typer.Typer(help="Email validation commands (ZeroBounce)")
console = Console()

API_KEY         = os.getenv("ZEROBOUNCE_API_KEY")
BATCH_ENDPOINT  = "https://api.zerobounce.net/v2/validatebatch"
BATCH_SIZE      = 200


def _has_mx(domain: str) -> bool:
    try:
        dns.resolver.resolve(domain, "MX", lifetime=3)
        return True
    except Exception:
        return False


def _already_emailed(db, contact_id: str) -> bool:
    return db.query(
        exists().where(
            (Activity.contact_id == contact_id)
            & (Activity.type == "email")
            & (Activity.status.in_(["sent", "delivered"]))
        )
    ).scalar()


def _pending_contacts(db, force: bool = False) -> list[Contact]:
    """Contacts that need ZeroBounce validation."""
    q = db.query(Contact).filter(Contact.email.isnot(None))
    if not force:
        q = q.filter(Contact.zb_status.is_(None))
    contacts = q.all()
    # exclude anyone already emailed (no point burning credits)
    return [c for c in contacts if not _already_emailed(db, c.id)]


def _validate_batch_api(emails: list[dict]) -> dict[str, dict]:
    payload = {"api_key": API_KEY, "email_batch": emails}
    resp    = requests.post(BATCH_ENDPOINT, json=payload, timeout=60)
    resp.raise_for_status()
    results = {}
    for item in resp.json().get("email_batch", []):
        addr = item.get("address", "").lower()
        results[addr] = {
            "zb_status":      item.get("status"),
            "zb_sub_status":  item.get("sub_status"),
            "zb_free_email":  item.get("free_email"),
            "zb_did_you_mean":item.get("did_you_mean") or None,
        }
    return results


# ── commands ──────────────────────────────────────────────────────────────────

@app.command()
def stats():
    """Show ZeroBounce validation status across all contacts in the database."""
    db = SessionLocal()
    try:
        all_contacts = db.query(Contact).all()
        total        = len(all_contacts)
        no_email     = sum(1 for c in all_contacts if not c.email)
        validated    = sum(1 for c in all_contacts if c.zb_status)
        already_sent = sum(1 for c in all_contacts if _already_emailed(db, c.id))

        pending = _pending_contacts(db)

        rprint(f"\n[bold]Checking MX records for [cyan]{len(pending)}[/cyan] pending contacts...[/bold]")

        mx_ok, mx_fail = 0, 0
        seen: dict[str, bool] = {}
        with console.status("Resolving MX records..."):
            for c in pending:
                domain = c.email.split("@")[-1].lower()
                if domain not in seen:
                    seen[domain] = _has_mx(domain)
                if seen[domain]:
                    mx_ok += 1
                else:
                    mx_fail += 1

        # ZB breakdown for already-validated contacts
        zb_counts: dict[str, int] = {}
        for c in all_contacts:
            if c.zb_status:
                zb_counts[c.zb_status] = zb_counts.get(c.zb_status, 0) + 1

        table = Table(title="ZeroBounce Stats", show_header=True)
        table.add_column("Metric",  style="bold")
        table.add_column("Count",   justify="right", style="cyan")

        table.add_row("Total contacts",          str(total))
        table.add_row("No email address",        str(no_email))
        table.add_row("Already emailed (skip)",  str(already_sent))
        table.add_row("Already validated",       str(validated))
        table.add_row("─" * 28,                  "─" * 5)
        table.add_row("Pending validation",      str(len(pending)))
        table.add_row("  ↳ MX record found",     str(mx_ok))
        table.add_row("  ↳ MX record missing",   str(mx_fail))

        if zb_counts:
            table.add_row("─" * 28, "─" * 5)
            for status, count in sorted(zb_counts.items()):
                table.add_row(f"  zb: {status}", str(count))

        console.print()
        console.print(table)
        console.print()
    finally:
        db.close()


@app.command(name="run")
def run(
    all:    bool = typer.Option(False, "--all",    help="Validate all pending contacts"),
    number: int  = typer.Option(None,  "--number", "-n", help="Validate the next N contacts"),
    force:  bool = typer.Option(False, "--force",  help="Re-validate contacts that already have a zb_status"),
):
    """Validate contact emails via ZeroBounce and update the database."""
    if not all and number is None:
        rprint("[bold red]Specify --all or --number N.[/bold red]")
        raise typer.Exit(1)

    if not API_KEY:
        rprint("[bold red]ZEROBOUNCE_API_KEY not set.[/bold red] Add it to your .env file.")
        raise typer.Exit(1)

    db = SessionLocal()
    try:
        pending = _pending_contacts(db, force=force)

        if not pending:
            rprint("[yellow]No contacts left to validate.[/yellow]")
            return

        target  = pending if all else pending[:number]
        batches = [target[i:i + BATCH_SIZE] for i in range(0, len(target), BATCH_SIZE)]

        rprint(f"\n[bold]Validating [cyan]{len(target)}[/cyan] contacts in [cyan]{len(batches)}[/cyan] batch(es)...[/bold]\n")

        validated = 0
        for batch_num, batch in enumerate(batches, 1):
            email_payloads = [
                {"email_address": c.email, "ip_address": ""}
                for c in batch
            ]
            console.print(f"  Batch {batch_num}/{len(batches)} — {len(email_payloads)} emails", end=" ")

            try:
                results = _validate_batch_api(email_payloads)
                for contact in batch:
                    zb = results.get(contact.email.lower(), {})
                    if zb.get("zb_status"):
                        contact.zb_status       = zb["zb_status"]
                        contact.zb_sub_status   = zb["zb_sub_status"]
                        contact.zb_free_email   = zb["zb_free_email"]
                        contact.zb_did_you_mean = zb["zb_did_you_mean"]
                        contact.email_validated_at = datetime.utcnow()
                        validated += 1

                db.commit()
                console.print("[green]✓[/green]")
            except requests.HTTPError as e:
                db.rollback()
                console.print(f"[red]HTTP error: {e}[/red]")
            except Exception as e:
                db.rollback()
                console.print(f"[red]Error: {e}[/red]")

            if batch_num < len(batches):
                time.sleep(1)

        rprint(f"\n[bold green]Done.[/bold green] {validated} contacts updated.")
    finally:
        db.close()
