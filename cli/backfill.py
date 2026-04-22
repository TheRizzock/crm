import typer
from dotenv import load_dotenv
from rich.console import Console

from app.db import SessionLocal
from app.models import Contact, Activity

load_dotenv()

app = typer.Typer(help="One-time data backfill commands")
console = Console()


@app.command("linkedin-activities")
def backfill_linkedin_activities(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
):
    """Create a linkedin activity for every contact that doesn't already have one."""
    db = SessionLocal()
    try:
        contacts = db.query(Contact).all()

        existing_contact_ids = {
            a.contact_id
            for a in db.query(Activity).filter(Activity.type == "linkedin").all()
        }

        to_create = [c for c in contacts if c.id not in existing_contact_ids]

        console.print(f"Contacts total      : {len(contacts)}")
        console.print(f"Already have activity: {len(existing_contact_ids)}")
        console.print(f"Will create          : {len(to_create)}")

        if not to_create:
            console.print("[green]Nothing to do.[/green]")
            return

        if dry_run:
            console.print("[yellow]Dry run — no changes written.[/yellow]")
            return

        for contact in to_create:
            db.add(Activity(
                contact_id=contact.id,
                type="linkedin",
                status="sent",
                created_at=contact.created_at,
            ))

        db.commit()
        console.print(f"[green]Created {len(to_create)} linkedin activities.[/green]")
    finally:
        db.close()
