"""Backfill email statuses from Resend for activities still marked 'scheduled'.

Usage:
    python -m cli.sync_resend              # interactive: preview list, pick one or all
    python -m cli.sync_resend --all        # update every null-status activity
    python -m cli.sync_resend --dry-run    # show what would change, no writes
    python -m cli.sync_resend --limit 200  # cap how many records are inspected
"""
import os
import time

import resend
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from app.db import SessionLocal
from app.models import Activity, Contact

load_dotenv()

app     = typer.Typer(help="Backfill email statuses from Resend")
console = Console()

resend.api_key = os.getenv("RESEND_API_KEY")

RESEND_STATUS_MAP = {
    "sent":             "sent",
    "delivered":        "delivered",
    "bounced":          "bounced",
    "opened":           "opened",
    "clicked":          "clicked",
    "complained":       "bounced",
    "delivery_delayed": "sent",
}


def _fetch_status(resend_id: str) -> str | None:
    try:
        email = resend.Emails.get(resend_id)
        raw = (
            email.get("last_event") if isinstance(email, dict)
            else getattr(email, "last_event", None)
        )
        return RESEND_STATUS_MAP.get(raw) if raw else None
    except Exception as e:
        console.print(f"  [red]ERR[/red] {resend_id[:24]}: {e}")
        return None


def _build_table(activities) -> Table:
    table = Table(show_lines=False, header_style="bold")
    table.add_column("#",         style="dim",   width=4)
    table.add_column("Contact",   style="cyan",  no_wrap=True)
    table.add_column("Resend ID", style="dim",   no_wrap=True, max_width=26)
    table.add_column("Sent at",   style="white", no_wrap=True)
    for i, act in enumerate(activities, 1):
        email = act.contact.email if act.contact else "—"
        sent  = act.created_at.strftime("%Y-%m-%d %H:%M") if act.created_at else "—"
        table.add_row(str(i), email, act.resend_id[:24] + "…", sent)
    return table


def _apply(act: Activity, db, dry_run: bool, delay: float = 0.0) -> str | None:
    status = _fetch_status(act.resend_id)
    if delay:
        time.sleep(delay)
    if status:
        if not dry_run:
            act.status = status
            if status == "bounced" and act.contact:
                act.contact.do_not_email = True
        return status
    return None


@app.command()
def sync(
    all_records: bool  = typer.Option(False, "--all",     help="Update every null-status activity without prompting"),
    dry_run:     bool  = typer.Option(False, "--dry-run", help="Print changes without saving"),
    limit:       int   = typer.Option(500,   "--limit",   help="Max activities to inspect"),
    delay:       float = typer.Option(0.25,  "--delay",   help="Seconds between Resend API calls"),
):
    """Backfill status for email activities still marked 'scheduled'."""
    db = SessionLocal()
    try:
        activities = (
            db.query(Activity)
            .join(Contact, Activity.contact_id == Contact.id, isouter=True)
            .filter(
                Activity.type == "email",
                Activity.resend_id.isnot(None),
                Activity.resend_id != "",
                Activity.resend_id != "?",
                Activity.status == "scheduled",
            )
            .order_by(Activity.created_at.desc())
            .limit(limit)
            .all()
        )

        if not activities:
            rprint("[yellow]No email activities with status 'scheduled' found.[/yellow]")
            return

        console.print(_build_table(activities))
        rprint(f"\n[dim]{len(activities)} activit{'y' if len(activities) == 1 else 'ies'} with no status[/dim]")

        # --all flag: skip prompting
        if all_records:
            updated = errors = 0
            for act in activities:
                status = _apply(act, db, dry_run, delay)
                if status:
                    label = "[dim](dry)[/dim] " if dry_run else ""
                    contact = act.contact.email if act.contact else act.resend_id[:20]
                    rprint(f"  {label}[cyan]{contact}[/cyan] → [green]{status}[/green]")
                    updated += 1
                else:
                    errors += 1

            if not dry_run:
                db.commit()

            tag = " [dim](dry run)[/dim]" if dry_run else ""
            rprint(f"\nDone{tag}. Updated: [green]{updated}[/green]  No data: [red]{errors}[/red]")
            return

        # Interactive mode
        rprint("\nEnter a [bold]row number[/bold] to update one, [bold]a[/bold] to update all, or [bold]q[/bold] to quit.")
        choice = typer.prompt("Choice").strip().lower()

        if choice == "q":
            return

        if choice == "a":
            targets = activities
        else:
            try:
                idx = int(choice) - 1
                if idx < 0 or idx >= len(activities):
                    rprint("[red]Invalid number.[/red]")
                    return
                targets = [activities[idx]]
            except ValueError:
                rprint("[red]Invalid input.[/red]")
                return

        updated = errors = 0
        for act in targets:
            status = _apply(act, db, dry_run, delay if len(targets) > 1 else 0.0)
            if status:
                contact = act.contact.email if act.contact else act.resend_id[:20]
                tag = " [dim](dry)[/dim]" if dry_run else ""
                rprint(f"  [cyan]{contact}[/cyan]{tag} → [green]{status}[/green]")
                updated += 1
            else:
                errors += 1

        if not dry_run:
            db.commit()

        tag = " [dim](dry run)[/dim]" if dry_run else ""
        rprint(f"\nDone{tag}. Updated: [green]{updated}[/green]  No data: [red]{errors}[/red]")

    finally:
        db.close()


if __name__ == "__main__":
    app()
