import glob
import json
import os
from datetime import datetime

import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from app.db import SessionLocal
from app.models import Contact, Company

load_dotenv()

app = typer.Typer(help="Import leads from a JSON file into the database")
console = Console()

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/raw_leads"))


def _map_contact(r: dict) -> dict:
    data = {
        "first_name":      r.get("first_name"),
        "last_name":       r.get("last_name"),
        "email":           r.get("email"),
        "personal_email":  r.get("personal_email"),
        "mobile_number":   r.get("mobile_number"),
        "profile_url":     r.get("linkedin"),
        "job_title":       r.get("job_title"),
        "industry":        r.get("industry"),
        "headline":        r.get("headline"),
        "seniority_level": r.get("seniority_level"),
        "functional_level":r.get("functional_level"),
        "city":            r.get("city"),
        "state":           r.get("state"),
        "country":         r.get("country"),
    }
    # ZB fields — only carry over if present
    for field in ("zb_status", "zb_sub_status", "zb_free_email", "zb_did_you_mean"):
        if r.get(field) is not None:
            data[field] = r[field]
    if data.get("zb_status"):
        data["email_validated_at"] = datetime.utcnow()
    return data


def _map_company(r: dict) -> dict:
    size = r.get("company_size")
    return {
        "name":                 r.get("company_name"),
        "website":              r.get("company_website"),
        "profile_url":          r.get("company_linkedin"),
        "company_size":         str(size) if size is not None else None,
        "domain":               r.get("company_domain"),
        "phone":                r.get("company_phone"),
        "linkedin_uid":         r.get("company_linkedin_uid"),
        "founded_year":         r.get("company_founded_year"),
        "annual_revenue":       r.get("company_annual_revenue"),
        "annual_revenue_clean": r.get("company_annual_revenue_clean"),
        "description":          r.get("company_description"),
        "total_funding":        r.get("company_total_funding"),
        "total_funding_clean":  r.get("company_total_funding_clean"),
        "keywords":             r.get("keywords"),
        "technologies":         r.get("company_technologies"),
        "street_address":       r.get("company_street_address"),
        "full_address":         r.get("company_full_address"),
        "city":                 r.get("company_city"),
        "state":                r.get("company_state"),
        "country":              r.get("company_country"),
        "postal_code":          r.get("company_postal_code"),
    }


def _merge_nulls(existing_obj, incoming: dict) -> bool:
    """Write incoming values into null fields on existing_obj. Returns True if anything changed."""
    changed = False
    for key, val in incoming.items():
        if val is not None and getattr(existing_obj, key, None) is None:
            setattr(existing_obj, key, val)
            changed = True
    return changed


def _find_contact_dupe(db, data: dict):
    """Returns (Contact, match_reason) or (None, '')."""
    if data.get("email"):
        c = db.query(Contact).filter(Contact.email == data["email"]).first()
        if c:
            return c, "email"
    if data.get("profile_url"):
        c = db.query(Contact).filter(Contact.profile_url == data["profile_url"]).first()
        if c:
            return c, "linkedin"
    if data.get("first_name") and data.get("last_name"):
        c = db.query(Contact).filter(
            Contact.first_name == data["first_name"],
            Contact.last_name  == data["last_name"],
        ).first()
        if c:
            return c, "name"
    return None, ""


def _show_contact_diff(existing: Contact, incoming: dict, incoming_company: str) -> None:
    table = Table(title="Potential Duplicate", header_style="bold cyan", show_lines=True)
    table.add_column("Field",    style="bold", width=18)
    table.add_column("In DB",    min_width=28)
    table.add_column("Incoming", min_width=28)

    fields = [
        ("first_name",    "First name"),
        ("last_name",     "Last name"),
        ("email",         "Email"),
        ("profile_url",   "LinkedIn"),
        ("job_title",     "Job title"),
        ("headline",      "Headline"),
        ("city",          "City"),
        ("state",         "State"),
        ("zb_status",     "ZB status"),
    ]
    for attr, label in fields:
        db_val  = str(getattr(existing, attr) or "—")
        inc_val = str(incoming.get(attr) or "—")
        style   = "yellow" if db_val != inc_val else "dim"
        table.add_row(label, db_val, inc_val, style=style)

    existing_company = existing.company.name if existing.company else "—"
    style = "yellow" if existing_company != incoming_company else "dim"
    table.add_row("Company", existing_company, incoming_company or "—", style=style)

    console.print()
    console.print(table)


def _prompt_action(match_reason: str) -> str:
    confidence = "high" if match_reason in ("email", "linkedin") else "low"
    color      = "green" if confidence == "high" else "yellow"
    rprint(f"  Match on [bold {color}]{match_reason}[/] (confidence: {confidence})")

    choices = {"m": "merge (fill nulls)", "s": "skip"}
    if match_reason == "name":
        choices["n"] = "create new record anyway"

    options_str = "  ".join(f"[[cyan]{k}[/]] {v}" for k, v in choices.items())
    rprint(f"  {options_str}")

    while True:
        choice = typer.prompt("  Action").strip().lower()
        if choice in choices:
            return choice
        rprint(f"  [red]Enter one of: {', '.join(choices)}[/red]")


def _pick_file() -> str:
    pattern = os.path.join(DATA_ROOT, "**/*.json")
    files   = sorted(glob.glob(pattern, recursive=True))
    if not files:
        rprint(f"[red]No JSON files found under {DATA_ROOT}[/red]")
        raise typer.Exit(1)

    rprint("\n[bold]Available lead files:[/bold]\n")
    for idx, fp in enumerate(files, 1):
        with open(fp) as f:
            size = len(json.load(f))
        rprint(f"  [cyan]{idx}[/cyan]. {os.path.relpath(fp)}  [dim]({size} records)[/dim]")

    rprint()
    raw = typer.prompt("Enter number")
    try:
        return os.path.abspath(files[int(raw) - 1])
    except (ValueError, IndexError):
        rprint("[red]Invalid selection.[/red]")
        raise typer.Exit(1)


@app.command("run")
def run_import(
    path: str       = typer.Argument(None, help="Path to JSON leads file (prompts if omitted)"),
    dry_run: bool   = typer.Option(False, "--dry-run",    help="Preview without writing anything"),
    auto_merge: bool= typer.Option(False, "--auto-merge", help="Merge all dupes without prompting"),
):
    """Import leads from a JSON file into the database."""
    filepath = os.path.abspath(path) if path else _pick_file()

    if not os.path.exists(filepath):
        rprint(f"[red]File not found:[/red] {filepath}")
        raise typer.Exit(1)

    with open(filepath) as f:
        records = json.load(f)

    rprint(f"\n[bold]File:[/bold] {os.path.relpath(filepath)}  [dim]({len(records)} records)[/dim]")
    if dry_run:
        rprint("[bold yellow]DRY RUN — nothing will be written[/bold yellow]")
    rprint()

    db = SessionLocal()
    stats = {
        "created": 0, "merged": 0, "skipped": 0, "new_from_dupe": 0,
        "co_created": 0, "co_merged": 0,
    }

    try:
        for i, record in enumerate(records, 1):
            contact_data = _map_contact(record)
            company_data = _map_company(record)

            label = (
                f"{contact_data.get('first_name', '')} {contact_data.get('last_name', '')}".strip()
                or f"record {i}"
            )
            console.print(f"[dim]{i}/{len(records)}[/dim] {label}", end=" ")

            # ── Company ────────────────────────────────────────────
            company = None
            if company_data.get("name"):
                company = db.query(Company).filter(Company.name == company_data["name"]).first()
                if company:
                    if not dry_run and _merge_nulls(company, company_data):
                        stats["co_merged"] += 1
                else:
                    if not dry_run:
                        company = Company(**{k: v for k, v in company_data.items() if v is not None})
                        db.add(company)
                        db.flush()  # get company.id before linking contact
                    stats["co_created"] += 1

            # ── Contact ────────────────────────────────────────────
            existing, match_reason = _find_contact_dupe(db, contact_data)

            if existing:
                console.print(f"[yellow]dupe ({match_reason})[/yellow]")
                _show_contact_diff(existing, contact_data, company_data.get("name", "—"))

                action = "m" if auto_merge else _prompt_action(match_reason)
                if auto_merge:
                    rprint("  [dim]Auto-merging.[/dim]")

                if action == "m":
                    if not dry_run:
                        _merge_nulls(existing, contact_data)
                        if company and not existing.company_id:
                            existing.company_id = company.id
                    stats["merged"] += 1
                elif action == "n":
                    if not dry_run:
                        c = Contact(**{k: v for k, v in contact_data.items() if v is not None})
                        if company:
                            c.company_id = company.id
                        db.add(c)
                    stats["new_from_dupe"] += 1
                else:
                    stats["skipped"] += 1
            else:
                console.print("[green]new[/green]")
                if not dry_run:
                    c = Contact(**{k: v for k, v in contact_data.items() if v is not None})
                    if company:
                        c.company_id = company.id
                    db.add(c)
                stats["created"] += 1

        if not dry_run:
            db.commit()
            rprint(f"\n[bold green]Import complete.[/bold green]")
        else:
            rprint(f"\n[bold yellow]Dry run complete — nothing written.[/bold yellow]")

        table = Table(title="Import Summary", show_header=False, min_width=36)
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right", style="cyan")
        table.add_row("Contacts created",              str(stats["created"]))
        table.add_row("Contacts merged",               str(stats["merged"]))
        table.add_row("Contacts skipped",              str(stats["skipped"]))
        table.add_row("New records (from dupe prompt)", str(stats["new_from_dupe"]))
        table.add_row("─" * 24, "─" * 5)
        table.add_row("Companies created",             str(stats["co_created"]))
        table.add_row("Companies updated",             str(stats["co_merged"]))
        console.print()
        console.print(table)

    except Exception as e:
        db.rollback()
        rprint(f"\n[bold red]Import failed:[/bold red] {e}")
        raise
    finally:
        db.close()
