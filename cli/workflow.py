import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from sqlalchemy import func

from app.db import SessionLocal
from app.models import Company, Contact
from cli.scrape import _process_company, HYDRATEABLE_FIELDS
from cli.enrich import run_enrich_contacts, run_discover_contacts

load_dotenv()

app     = typer.Typer(help="Guided workflows that chain multiple enrichment steps together")
console = Console()

PAGE_SIZE = 10


def _priority_score(company: Company, contact_count: int) -> int:
    missing = sum(1 for f in HYDRATEABLE_FIELDS if not getattr(company, f))
    return missing + (max(0, 3 - contact_count) * 4)


def _load_candidates(db) -> list[tuple[Company, int]]:
    """All companies with their contact counts, sorted by priority descending."""
    counts = dict(
        db.query(Contact.company_id, func.count(Contact.id))
        .group_by(Contact.company_id)
        .all()
    )
    companies = db.query(Company).all()
    rows = [(c, counts.get(c.id, 0)) for c in companies]
    rows.sort(key=lambda r: _priority_score(r[0], r[1]), reverse=True)
    return rows


def _print_page(rows: list[tuple[Company, int]], offset: int, total: int) -> None:
    table = Table(
        title=f"Companies needing attention  ({offset + 1}–{min(offset + PAGE_SIZE, total)} of {total})",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("#",               width=4,  justify="right", style="bold cyan")
    table.add_column("Company",         min_width=28)
    table.add_column("Contacts",        width=10, justify="right")
    table.add_column("Missing fields",  width=14, justify="right")
    table.add_column("Has website",     width=11, justify="center")

    for i, (company, count) in enumerate(rows, 1):
        missing  = sum(1 for f in HYDRATEABLE_FIELDS if not getattr(company, f))
        has_site = bool(company.website or company.domain)
        table.add_row(
            str(i),
            company.name or "—",
            str(count),
            str(missing),
            "[green]✓[/green]" if has_site else "[red]✗[/red]",
        )

    console.print()
    console.print(table)


def _run_company_workflow(company: Company, db) -> None:
    """Full scrape → enrich contacts → discover contacts pipeline for one company."""
    rprint(f"\n[bold cyan]{'─' * 60}[/bold cyan]")
    rprint(f"[bold]{company.name}[/bold]  [dim]{company.website or company.domain or 'no URL'}[/dim]")
    rprint(f"[bold cyan]{'─' * 60}[/bold cyan]\n")

    # ── step 1: scrape company ────────────────────────────────────────────────
    rprint("[bold]Step 1 — Scrape company details[/bold]")
    result = _process_company(company, db, force=False, auto_approve=False)
    rprint(f"  [dim]Result: {result}[/dim]")

    # ── step 2: enrich existing contacts ─────────────────────────────────────
    rprint("\n[bold]Step 2 — Enrich existing contacts[/bold]")
    contact_count = db.query(func.count(Contact.id)).filter(Contact.company_id == company.id).scalar()

    if contact_count == 0:
        rprint("  [dim]No existing contacts to enrich.[/dim]")
    else:
        rprint(f"  {contact_count} contact(s) on file.")
        if typer.confirm("  Enrich them now?", default=True):
            stats = run_enrich_contacts(company, db, auto_approve=False)
            rprint(f"  [dim]Updated: {stats['updated']}  Skipped: {stats['skipped']}  Nothing found: {stats['nothing_found']}[/dim]")
        else:
            rprint("  [dim]Skipped.[/dim]")

    # ── step 3: discover new contacts ────────────────────────────────────────
    rprint("\n[bold]Step 3 — Discover new contacts from team page[/bold]")
    if typer.confirm("  Scrape team page for new contacts?", default=True):
        stats = run_discover_contacts(company, db, auto_approve=False)
        rprint(f"  [dim]Added: {stats['added']}  Skipped: {stats['skipped']}  Already in CRM: {stats['exists']}[/dim]")
    else:
        rprint("  [dim]Skipped.[/dim]")

    rprint(f"\n[bold cyan]{'─' * 60}[/bold cyan]")
    rprint(f"[bold green]Done with {company.name}.[/bold green]")


@app.command("companies")
def companies_workflow():
    """
    Guided company enrichment workflow.

    Lists companies sorted by how much they need attention (few contacts +
    missing fields first). Select one by number to run the full pipeline:
    scrape details → enrich contacts → discover new contacts.
    """
    db = SessionLocal()
    try:
        all_rows = _load_candidates(db)
        total    = len(all_rows)

        if not total:
            rprint("[yellow]No companies found.[/yellow]")
            return

        offset = 0

        while True:
            page = all_rows[offset: offset + PAGE_SIZE]
            _print_page(page, offset, total)

            has_prev = offset > 0
            has_next = offset + PAGE_SIZE < total
            nav = []
            if has_next: nav.append("[n]ext")
            if has_prev: nav.append("[p]rev")
            nav.append("[1–10] select")
            nav.append("[q]uit")

            console.print(f"\n  {' · '.join(nav)}")
            choice = typer.prompt("  >", default="").strip().lower()

            if choice == "q":
                break
            elif choice == "n" and has_next:
                offset += PAGE_SIZE
            elif choice == "p" and has_prev:
                offset -= PAGE_SIZE
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(page):
                    company, _ = page[idx]
                    _run_company_workflow(company, db)
                    # refresh scores after changes
                    all_rows = _load_candidates(db)
                    total    = len(all_rows)
                else:
                    rprint(f"  [red]Enter a number between 1 and {len(page)}.[/red]")
            else:
                rprint("  [red]Invalid input.[/red]")

    finally:
        db.close()
