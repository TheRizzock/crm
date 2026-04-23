import json
import os
from typing import Optional

import openai
import requests
import typer
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from sqlalchemy import func

from app.db import SessionLocal
from app.models import Company, Contact

load_dotenv()

app     = typer.Typer(help="Scrape company websites to hydrate missing CRM fields")
console = Console()

OPENAI_CLIENT = None  # lazy init

# Fields we can realistically extract from a website
HYDRATEABLE_FIELDS = [
    "description",
    "phone",
    "street_address",
    "full_address",
    "city",
    "state",
    "country",
    "postal_code",
    "founded_year",
    "technologies",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

DETECT_PROMPT = """\
Given the following information about a company, provide their most likely official website URL.
Only suggest a URL if you are reasonably confident it is correct — do not guess randomly.
Return ONLY a valid JSON object: {{"website": "https://example.com"}} or {{"website": null}} if unsure.

Company name: {name}
Domain hint: {domain}
LinkedIn URL: {linkedin}
Location: {city}, {state}, {country}
Description: {description}
"""

EXTRACT_PROMPT = """\
You are a data extraction assistant. Given the text content scraped from a company website, \
extract the following fields if you can find them with reasonable confidence.

Fields to extract:
- description: A concise company description (2-4 sentences max). Write it yourself based on what you read — do not copy marketing fluff.
- phone: Main office phone number (formatted as found)
- street_address: Street address only (no city/state)
- full_address: Full mailing address as a single string
- city: City of headquarters
- state: State/province of headquarters
- country: Country of headquarters
- postal_code: ZIP or postal code
- founded_year: Year the company was founded (4-digit string)
- technologies: Comma-separated list of notable software/tech stack mentioned on the site

Return ONLY a valid JSON object with the fields you found. Omit any field you are not confident about. \
Do not include null values — just omit the key entirely.

Website URL: {url}

Website content:
{content}
"""


def _get_client() -> openai.OpenAI:
    global OPENAI_CLIENT
    if OPENAI_CLIENT is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            rprint("[bold red]OPENAI_API_KEY not set.[/bold red] Add it to your .env file.")
            raise typer.Exit(1)
        OPENAI_CLIENT = openai.OpenAI(api_key=api_key)
    return OPENAI_CLIENT


def _fetch_text(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch a URL and return stripped plain text, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        # collapse whitespace and truncate to keep tokens manageable
        text = " ".join(text.split())
        return text[:5000]
    except Exception:
        return None


def _scrape_website(url: str) -> Optional[str]:
    """Try homepage, then /about. Return best content found."""
    text = _fetch_text(url)

    about_url = url.rstrip("/") + "/about"
    about_text = _fetch_text(about_url)

    if text and about_text:
        # combine — about page often has the best structured info
        return (text + " " + about_text)[:5000]
    return text or about_text


def _extract_fields(url: str, content: str) -> dict:
    """Call Claude Haiku to extract structured fields from website text."""
    client = _get_client()
    prompt = EXTRACT_PROMPT.format(url=url, content=content)

    response = client.chat.completions.create(
        model="gpt-4.1-nano",
        max_tokens=512,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )

    return json.loads(response.choices[0].message.content)


def _validate_url(url: str) -> bool:
    """HEAD request to confirm the URL is reachable."""
    try:
        resp = requests.head(url, headers=HEADERS, timeout=6, allow_redirects=True)
        return resp.status_code < 400
    except Exception:
        return False


def _detect_website(company: Company) -> Optional[tuple[str, str]]:
    """
    Try to find the company's website. Returns (url, source) or None.
    Sources: 'domain' | 'gpt' | 'web_search'
    """
    # 1. construct from domain field if present
    if company.domain:
        url = f"https://{company.domain.lstrip('https://').lstrip('http://')}"
        if _validate_url(url):
            return url, "domain"

    # 2. ask GPT (static knowledge — free, instant)
    prompt = DETECT_PROMPT.format(
        name=company.name or "",
        domain=company.domain or "",
        linkedin=company.profile_url or "",
        city=company.city or "",
        state=company.state or "",
        country=company.country or "",
        description=company.description or "",
    )
    try:
        response = _get_client().chat.completions.create(
            model="gpt-4.1-nano",
            max_tokens=64,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(response.choices[0].message.content)
        url  = data.get("website")
        if url and _validate_url(url):
            return url, "gpt"
    except Exception:
        pass

    # 3. web search via OpenAI Responses API
    try:
        location = ", ".join(p for p in [company.city, company.state, company.country] if p)
        query = f'What is the official website URL for the company "{company.name}"'
        if location:
            query += f" located in {location}"
        query += "? Reply with only the URL."
        resp = _get_client().responses.create(
            model="gpt-4o-mini",
            tools=[{"type": "web_search_preview"}],
            input=query,
        )
        url = (resp.output_text or "").strip().rstrip("/")
        if url.startswith("http") and "." in url and _validate_url(url):
            return url, "web_search"
    except Exception:
        pass

    return None


def _missing_field_count(company: Company) -> int:
    return sum(1 for f in HYDRATEABLE_FIELDS if not getattr(company, f))


def _show_diff(company: Company, proposed: dict) -> dict:
    """
    Display a diff table and return the subset of proposed values that would
    actually change something (new value for a null field, or any value if --force).
    Always returns all proposed fields — caller decides what to apply.
    """
    table = Table(
        title=f"Proposed updates — {company.name}",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("Field",    style="bold", width=18)
    table.add_column("Current",  min_width=28, style="dim")
    table.add_column("Proposed", min_width=28)

    has_changes = False
    for field, value in proposed.items():
        current = getattr(company, field, None)
        current_str  = str(current) if current else "[dim](empty)[/dim]"
        proposed_str = str(value)
        style = "yellow" if current else "green"
        table.add_row(field, current_str, f"[{style}]{proposed_str}[/]")
        has_changes = True

    if has_changes:
        console.print()
        console.print(table)
    else:
        rprint("  [dim]No extractable fields found.[/dim]")

    return proposed


def _apply_updates(company: Company, proposed: dict, force: bool) -> int:
    """Write proposed values to company. If not force, only fill nulls. Returns count changed."""
    changed = 0
    for field, value in proposed.items():
        current = getattr(company, field, None)
        if force or not current:
            setattr(company, field, value)
            changed += 1
    return changed


def _resolve_url(company: Company, db, auto_approve: bool) -> Optional[str]:
    """
    Return the company's URL, detecting or prompting as needed.
    Saves to company.website if a new URL is found.
    """
    url = company.website or (f"https://{company.domain}" if company.domain else None)
    if url:
        return url

    console.print("  [dim]No URL — attempting detection...[/dim]", end=" ")
    result = _detect_website(company)

    if result:
        url, source = result
        console.print(f"[cyan]found via {source}:[/cyan] {url}")
        if not auto_approve and not typer.confirm(f"  Save {url} as website?"):
            return None
        company.website = url
        db.commit()
        return url

    console.print("[red]not found[/red]")

    if auto_approve:
        return None

    # show contact LinkedIn URLs as a hint so the user can look up the site
    contacts = db.query(Contact).filter(Contact.company_id == company.id).all()
    li_urls = [c.profile_url for c in contacts if c.profile_url]
    if li_urls:
        rprint("  [dim]Contact LinkedIn URLs — may help you find their site:[/dim]")
        for lu in li_urls[:3]:
            rprint(f"    [blue]{lu}[/blue]")

    manual = typer.prompt("  Enter website URL manually (or press Enter to skip)", default="").strip()
    if not manual:
        return None
    if not manual.startswith("http"):
        manual = "https://" + manual
    if _validate_url(manual):
        company.website = manual
        db.commit()
        rprint("  [bold green]✓ Saved.[/bold green]")
        return manual
    rprint("  [red]URL not reachable — skipping.[/red]")
    return None


def _process_company(company: Company, db, force: bool, auto_approve: bool) -> str:
    """
    Scrape and update one company. Returns status string:
    'updated', 'skipped', 'no_content', 'no_fields', 'no_url', 'error'
    """
    url = _resolve_url(company, db, auto_approve)
    if not url:
        return "no_url"

    if not url.startswith("http"):
        url = "https://" + url

    console.print(f"  [dim]Fetching {url}...[/dim]", end=" ")
    content = _scrape_website(url)
    if not content:
        console.print("[red]no content[/red]")
        return "no_content"
    console.print("[green]ok[/green]")

    try:
        proposed = _extract_fields(url, content)
    except Exception as e:
        rprint(f"  [red]Extraction failed: {e}[/red]")
        return "error"

    if not proposed:
        rprint("  [dim]Nothing extracted.[/dim]")
        return "no_fields"

    # filter to only fields that matter (nulls unless force)
    relevant = {k: v for k, v in proposed.items() if force or not getattr(company, k, None)}
    if not relevant:
        rprint("  [dim]No missing fields to fill.[/dim]")
        return "no_fields"

    _show_diff(company, relevant)

    if not auto_approve:
        if not typer.confirm("  Apply these changes?"):
            return "skipped"

    changed = _apply_updates(company, relevant, force=force)
    db.commit()
    rprint(f"  [bold green]✓ {changed} field(s) updated.[/bold green]")
    return "updated"


# ── commands ──────────────────────────────────────────────────────────────────

@app.command("company")
def scrape_company(
    company_id: str  = typer.Argument(..., help="Company ID to scrape"),
    force:      bool = typer.Option(False, "--force", help="Overwrite existing values, not just nulls"),
    yes:        bool = typer.Option(False, "--yes",   "-y", help="Auto-approve all changes"),
):
    """Scrape a single company's website and hydrate missing fields."""
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            rprint(f"[red]Company not found:[/red] {company_id}")
            raise typer.Exit(1)

        rprint(f"\n[bold]{company.name}[/bold]  [dim]{company.website or company.domain or 'no URL'}[/dim]")
        _process_company(company, db, force=force, auto_approve=yes)
    finally:
        db.close()


@app.command("detect-company")
def detect_company(
    company_id: str  = typer.Argument(..., help="Company ID to find a website for"),
    yes:        bool = typer.Option(False, "--yes", "-y", help="Auto-save without prompting"),
):
    """Detect and save a website URL for a single company."""
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            rprint(f"[red]Company not found:[/red] {company_id}")
            raise typer.Exit(1)

        rprint(f"\n[bold]{company.name}[/bold]  [dim]current: {company.website or '(none)'}[/dim]")
        url = _resolve_url(company, db, auto_approve=yes)
        if url:
            rprint(f"  [bold green]✓ Website:[/bold green] {url}  Run [cyan]crm scrape company {company_id}[/cyan] to enrich it.")
        else:
            rprint("[yellow]No website found or saved.[/yellow]")
    finally:
        db.close()


@app.command("detect")
def scrape_detect(
    limit:   int  = typer.Option(20,    "--limit",  "-n", help="Max companies to process"),
    yes:     bool = typer.Option(False, "--yes",    "-y", help="Auto-save detected URLs without prompting"),
    dry_run: bool = typer.Option(False, "--dry-run",      help="Show candidates without making any requests"),
):
    """
    Find websites for companies that don't have one.

    Tries the domain field first, then asks GPT. Validates every URL with a
    HEAD request before saving. Runs detect → enrich automatically.
    """
    db = SessionLocal()
    try:
        candidates = (
            db.query(Company)
            .filter(Company.website.is_(None))
            .all()
        )

        if not candidates:
            rprint("[yellow]All companies already have a website.[/yellow]")
            return

        # prioritise companies with a domain hint or LinkedIn URL (more likely to succeed)
        candidates.sort(key=lambda c: (0 if c.domain else 1, 0 if c.profile_url else 1))
        candidates = candidates[:limit]

        rprint(f"\n[bold]Companies without a website:[/bold] {len(candidates)}\n")

        if dry_run:
            table = Table(header_style="bold cyan")
            table.add_column("Company",  min_width=28)
            table.add_column("Domain",   min_width=20)
            table.add_column("LinkedIn", min_width=20)
            for c in candidates:
                table.add_row(c.name or "—", c.domain or "—", c.profile_url or "—")
            console.print(table)
            return

        stats = {"saved": 0, "skipped": 0, "not_found": 0}

        for i, company in enumerate(candidates, 1):
            rprint(f"\n[bold][{i}/{len(candidates)}][/bold] {company.name}")
            console.print(f"  [dim]Detecting...[/dim]", end=" ")

            result = _detect_website(company)
            if not result:
                console.print("[red]not found[/red]")
                stats["not_found"] += 1
                continue

            url, source = result
            console.print(f"[cyan]{source}[/cyan] → {url}")

            if not yes:
                if not typer.confirm(f"  Save as website?"):
                    stats["skipped"] += 1
                    continue

            company.website = url
            db.commit()
            stats["saved"] += 1
            rprint(f"  [bold green]✓ Saved.[/bold green]")

        table = Table(title="Detect Summary", show_header=False, min_width=26)
        table.add_column("Result", style="bold")
        table.add_column("Count",  justify="right", style="cyan")
        table.add_row("Websites saved", str(stats["saved"]))
        table.add_row("Skipped",        str(stats["skipped"]))
        table.add_row("Not found",      str(stats["not_found"]))
        console.print()
        console.print(table)
    finally:
        db.close()


@app.command("run")
def scrape_run(
    limit:  int  = typer.Option(10,    "--limit",  "-n", help="Max companies to process"),
    force:  bool = typer.Option(False, "--force",        help="Overwrite existing values, not just nulls"),
    yes:    bool = typer.Option(False, "--yes",    "-y", help="Auto-approve all changes"),
    dry_run:bool = typer.Option(False, "--dry-run",      help="Show which companies would be scraped, then exit"),
):
    """
    Batch scrape companies with the most missing fields.

    Companies without a website will have detection attempted automatically.
    Prioritises companies with the most missing hydrateable fields.
    """
    db = SessionLocal()
    try:
        # include ALL companies — _process_company handles detection for those without a URL
        candidates = db.query(Company).all()

        # sort by most missing fields descending
        candidates.sort(key=_missing_field_count, reverse=True)

        # if not force, skip companies that already have all fields populated
        if not force:
            candidates = [c for c in candidates if _missing_field_count(c) > 0]

        candidates = candidates[:limit]

        if not candidates:
            rprint("[yellow]No companies to scrape.[/yellow]")
            return

        rprint(f"\n[bold]Companies to scrape:[/bold] {len(candidates)}\n")

        if dry_run:
            table = Table(header_style="bold cyan")
            table.add_column("Company",       min_width=28)
            table.add_column("URL",           min_width=30)
            table.add_column("Missing fields", justify="right")
            for c in candidates:
                table.add_row(
                    c.name or "—",
                    c.website or c.domain or "—",
                    str(_missing_field_count(c)),
                )
            console.print(table)
            return

        stats = {"updated": 0, "skipped": 0, "no_content": 0, "no_fields": 0, "no_url": 0, "error": 0}


        for i, company in enumerate(candidates, 1):
            rprint(f"\n[bold][{i}/{len(candidates)}][/bold] {company.name}")
            result = _process_company(company, db, force=force, auto_approve=yes)
            stats[result] = stats.get(result, 0) + 1

        table = Table(title="Scrape Summary", show_header=False, min_width=30)
        table.add_column("Result", style="bold")
        table.add_column("Count", justify="right", style="cyan")
        table.add_row("Updated",      str(stats["updated"]))
        table.add_row("Skipped",      str(stats["skipped"]))
        table.add_row("No content",   str(stats["no_content"]))
        table.add_row("Nothing found",str(stats["no_fields"]))
        table.add_row("No URL",       str(stats["no_url"]))
        table.add_row("Errors",       str(stats["error"]))
        console.print()
        console.print(table)
    finally:
        db.close()
