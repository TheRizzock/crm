import json
import os
import re
from collections import Counter
from typing import Optional

import openai
import requests
import typer
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from app.db import SessionLocal
from app.models import Contact, Company

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

load_dotenv()

app     = typer.Typer(help="Enrich contact records with missing emails, phones, and other info")
console = Console()

OPENAI_CLIENT = None

TEAM_PATHS = [
    "/team", "/our-team", "/about", "/about-us", "/leadership",
    "/people", "/staff", "/about/team", "/company/team", "/who-we-are",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

TEAM_DISCOVER_PROMPT = """\
Extract every individual team member listed on this website page.
Return a JSON object with a "members" array. Each member object may have:
  first_name, last_name, job_title, email, mobile_number, profile_url (LinkedIn URL)

Only include real people — not departments, companies, or generic roles.
Omit fields you cannot find. Do not invent or guess any values.

Website content:
{content}
"""

CONTACT_EXTRACT_PROMPT = """\
You are a contact data extraction assistant. Given website content from a company page, \
find contact information for the specific person described below. Only return information \
you find explicitly on the page — do not guess or construct anything.

Person to find:
  Name: {first_name} {last_name}
  Job title: {job_title}
  Company: {company_name}

Extract any of the following if found for this specific person:
- email: their work email address
- mobile_number: their direct phone or mobile number
- personal_email: a personal email if listed

Return ONLY a valid JSON object with the fields you found. Omit fields you could not find. \
Do not include null values.

Website content:
{content}
"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_client() -> openai.OpenAI:
    global OPENAI_CLIENT
    if OPENAI_CLIENT is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            rprint("[bold red]OPENAI_API_KEY not set.[/bold red] Add it to your .env file.")
            raise typer.Exit(1)
        OPENAI_CLIENT = openai.OpenAI(api_key=api_key)
    return OPENAI_CLIENT


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ", strip=True).split())


def _fetch_html(url: str, timeout: int = 8) -> Optional[str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        return resp.text if resp.status_code == 200 else None
    except Exception:
        return None


def _fetch_html_js(url: str, timeout_ms: int = 15000) -> Optional[str]:
    """Fetch fully-rendered HTML via headless browser, scrolling to trigger lazy loads."""
    if not PLAYWRIGHT_AVAILABLE:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            html = page.content()
            browser.close()
        return html
    except Exception:
        return None


def _extract_links_for_person(html: str, first_name: str, last_name: str) -> dict:
    """
    Find mailto:, tel:, and LinkedIn links inside the HTML card that holds the
    person's name. More reliable than asking GPT to find links in plain text.
    """
    soup   = BeautifulSoup(html, "html.parser")
    result = {}

    for node in soup.find_all(string=re.compile(re.escape(last_name), re.IGNORECASE)):
        container = node.find_parent()
        for _ in range(10):
            if not container:
                break
            ctx = container.get_text().lower()
            if first_name.lower() in ctx and last_name.lower() in ctx:
                for a in container.find_all("a", href=True):
                    href = a["href"].strip()
                    if href.startswith("mailto:") and "email" not in result:
                        email = href[len("mailto:"):].split("?")[0].strip()
                        if email:
                            result["email"] = email
                    elif href.startswith("tel:") and "mobile_number" not in result:
                        phone = href[len("tel:"):].strip()
                        if phone:
                            result["mobile_number"] = phone
                    elif "linkedin.com/in/" in href and "profile_url" not in result:
                        result["profile_url"] = href.split("?")[0].rstrip("/")
                if result:
                    return result
            container = container.find_parent()

    return result


def _extract_all_team_members(html: str, plain_text: str) -> list[dict]:
    """
    Use GPT to extract all team members from a page, then enrich each with
    direct link extraction from the HTML.
    """
    try:
        response = _get_client().chat.completions.create(
            model="gpt-4.1-nano",
            max_tokens=2048,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": TEAM_DISCOVER_PROMPT.format(content=plain_text[:7000])}],
        )
        data    = json.loads(response.choices[0].message.content)
        members = data.get("members", [])
    except Exception:
        return []

    # enrich each GPT result with direct HTML link extraction
    for member in members:
        first = member.get("first_name", "")
        last  = member.get("last_name", "")
        if first and last:
            links = _extract_links_for_person(html, first, last)
            for field, value in links.items():
                if field not in member or not member[field]:
                    member[field] = value

    return members


def _fetch_best_team_page(base_url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch the team/about page most likely to list staff. Returns (html, plain_text).
    Uses Playwright if the static render is thin.
    """
    base = base_url.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base

    best_html  = None
    best_score = 0

    for path in TEAM_PATHS:
        url  = base + path
        html = _fetch_html(url)
        if not html:
            continue

        text  = _html_to_text(html)
        score = len(text)

        # if content looks like a JS shell, try Playwright
        if score < 500:
            js_html = _fetch_html_js(url)
            if js_html:
                js_text = _html_to_text(js_html)
                if len(js_text) > score:
                    html  = js_html
                    score = len(js_text)

        if score > best_score:
            best_html  = html
            best_score = score

        if best_score > 4000:
            break   # good enough

    if not best_html:
        return None, None
    return best_html, _html_to_text(best_html)[:8000]


def _scrape_team_pages(base_url: str, last_name: str = "") -> tuple[Optional[str], Optional[str]]:
    """
    Try known team/people paths. Returns (html, plain_text) for the best page found.
    Falls back to Playwright if the person's name isn't found in the static render.
    """
    base = base_url.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base

    best_html = None
    texts     = []
    used_js   = False

    for path in TEAM_PATHS:
        url  = base + path
        html = _fetch_html(url)

        if html and last_name and last_name.lower() not in html.lower() and not used_js:
            js_html = _fetch_html_js(url)
            if js_html and last_name.lower() in js_html.lower():
                html    = js_html
                used_js = True

        if html:
            if last_name and last_name.lower() in html.lower():
                best_html = html   # keep the page most likely to have the person
            texts.append(_html_to_text(html)[:3000])

        if sum(len(t) for t in texts) > 8000:
            break

    plain = " ".join(texts)[:8000] if texts else None
    return best_html, plain


def _extract_contact_info(contact: Contact, company_name: str, content: str) -> dict:
    client = _get_client()
    prompt = CONTACT_EXTRACT_PROMPT.format(
        first_name=contact.first_name or "",
        last_name=contact.last_name or "",
        job_title=contact.job_title or "",
        company_name=company_name,
        content=content,
    )
    response = _get_client().chat.completions.create(
        model="gpt-4.1-nano",
        max_tokens=256,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(response.choices[0].message.content)


# ── email pattern inference ───────────────────────────────────────────────────

def _infer_email_pattern(emails: list[str], names: list[tuple[str, str]]) -> Optional[str]:
    """
    Given known (email, first_name, last_name) combos at a company, infer the pattern.
    Returns a pattern string like '{first}.{last}' or '{f}{last}', or None.
    """
    patterns: list[str] = []
    for email, first, last in zip(emails, [n[0] for n in names], [n[1] for n in names]):
        if not first or not last or not email:
            continue
        local = email.split("@")[0].lower()
        f = first.lower()
        l = last.lower()
        fi = f[0]
        li = l[0]

        if local == f"{f}.{l}":
            patterns.append("first.last")
        elif local == f"{f}{l}":
            patterns.append("firstlast")
        elif local == f"{fi}{l}":
            patterns.append("flast")
        elif local == f"{f}{li}":
            patterns.append("firstl")
        elif local == f:
            patterns.append("first")
        elif local == l:
            patterns.append("last")
        elif local == f"{f}_{l}":
            patterns.append("first_last")

    if not patterns:
        return None
    most_common = Counter(patterns).most_common(1)[0][0]
    return most_common if Counter(patterns)[most_common] >= max(1, len(patterns) // 2) else None


def _apply_pattern(pattern: str, first: str, last: str) -> Optional[str]:
    f  = (first or "").lower().strip()
    l  = (last  or "").lower().strip()
    if not f or not l:
        return None
    mapping = {
        "first.last": f"{f}.{l}",
        "firstlast":  f"{f}{l}",
        "flast":      f"{f[0]}{l}",
        "firstl":     f"{f}{l[0]}",
        "first":      f,
        "last":       l,
        "first_last": f"{f}_{l}",
    }
    return mapping.get(pattern)


def _suggest_email_from_pattern(contact: Contact, db) -> Optional[tuple[str, str]]:
    """
    Look at other contacts at the same company with known emails.
    Returns (suggested_email, confidence_note) or None.
    """
    if not contact.company_id:
        return None

    siblings = (
        db.query(Contact)
        .filter(
            Contact.company_id == contact.company_id,
            Contact.email.isnot(None),
            Contact.id != contact.id,
        )
        .limit(10)
        .all()
    )

    if not siblings:
        return None

    domain = siblings[0].email.split("@")[-1]
    emails = [s.email for s in siblings]
    names  = [(s.first_name, s.last_name) for s in siblings]

    pattern = _infer_email_pattern(emails, names)
    if not pattern:
        return None

    local = _apply_pattern(pattern, contact.first_name, contact.last_name)
    if not local:
        return None

    suggested = f"{local}@{domain}"
    note = f"pattern '{pattern}' inferred from {len(siblings)} colleague(s) at {domain}"
    return suggested, note


# ── core process ─────────────────────────────────────────────────────────────

def _process_contact(contact: Contact, db, force: bool, auto_approve: bool) -> str:
    company  = contact.company
    base_url = company.website or company.domain if company else None
    name     = f"{contact.first_name or ''} {contact.last_name or ''}".strip()

    rprint(f"  [dim]Company:[/dim] {company.name if company else '—'}  [dim]URL:[/dim] {base_url or '—'}")

    proposed: dict[str, tuple[str, str]] = {}  # field → (value, source)

    # ── 1. email pattern inference (free, fast) ───────────────────────────────
    if not contact.email or force:
        result = _suggest_email_from_pattern(contact, db)
        if result:
            suggested, note = result
            proposed["email"] = (suggested, f"[cyan]pattern[/cyan] {note}")

    # ── 2. website scraping + GPT extraction ─────────────────────────────────
    missing_fields = [
        f for f in ("email", "mobile_number", "personal_email")
        if not getattr(contact, f) or force
    ]

    if missing_fields and base_url:
        console.print(f"  [dim]Scraping team pages...[/dim]", end=" ")
        html, plain = _scrape_team_pages(base_url, last_name=contact.last_name or "")

        name_found = bool(html and contact.last_name and contact.last_name.lower() in html.lower())

        if not html and not plain:
            console.print("[red]no content[/red]")
        elif not name_found:
            console.print("[yellow]name not found on site[/yellow]")
        else:
            console.print("[green]found[/green]")

            # 1. direct HTML link extraction — fast, free, accurate
            if html and contact.first_name and contact.last_name:
                links = _extract_links_for_person(html, contact.first_name, contact.last_name)
                for field, value in links.items():
                    if field in missing_fields and value:
                        proposed[field] = (value, "[green]scraped (link)[/green]")

            # 2. GPT extraction for anything still missing
            still_missing = [f for f in missing_fields if f not in proposed]
            if still_missing and plain:
                try:
                    extracted = _extract_contact_info(contact, company.name if company else "", plain)
                    for field, value in extracted.items():
                        if field in still_missing and value:
                            proposed[field] = (value, "[cyan]scraped (gpt)[/cyan]")
                except Exception as e:
                    console.print(f"  [red]GPT extraction error: {e}[/red]")

    if not proposed:
        rprint("  [dim]Nothing found.[/dim]")
        return "nothing_found"

    # ── show diff table ───────────────────────────────────────────────────────
    table = Table(title=f"Proposed — {name}", header_style="bold cyan", show_lines=True)
    table.add_column("Field",      style="bold", width=16)
    table.add_column("Current",    min_width=24, style="dim")
    table.add_column("Proposed",   min_width=24)
    table.add_column("Source",     min_width=20)

    for field, (value, source) in proposed.items():
        current = getattr(contact, field, None)
        table.add_row(field, str(current) if current else "(empty)", value, source)

    console.print()
    console.print(table)

    if not auto_approve:
        if not typer.confirm("  Apply these changes?"):
            return "skipped"

    for field, (value, _) in proposed.items():
        if force or not getattr(contact, field):
            setattr(contact, field, value)

    db.commit()
    rprint(f"  [bold green]✓ {len(proposed)} field(s) updated.[/bold green]")
    return "updated"


# ── commands ──────────────────────────────────────────────────────────────────

@app.command("contact")
def enrich_contact(
    contact_id: str  = typer.Argument(..., help="Contact ID to enrich"),
    force:      bool = typer.Option(False, "--force", help="Overwrite existing values too"),
    yes:        bool = typer.Option(False, "--yes", "-y", help="Auto-approve changes"),
):
    """Enrich a single contact — find missing email, phone, etc."""
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            rprint(f"[red]Contact not found:[/red] {contact_id}")
            raise typer.Exit(1)

        name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        rprint(f"\n[bold]{name}[/bold]  [dim]{contact.job_title or ''}[/dim]")
        _process_contact(contact, db, force=force, auto_approve=yes)
    finally:
        db.close()


@app.command("run")
def enrich_run(
    limit:   int  = typer.Option(20,    "--limit",   "-n", help="Max contacts to process"),
    missing: str  = typer.Option("email", "--missing",     help="Field to target: email | mobile_number | any"),
    force:   bool = typer.Option(False,  "--force",        help="Overwrite existing values too"),
    yes:     bool = typer.Option(False,  "--yes",    "-y", help="Auto-approve all changes"),
    dry_run: bool = typer.Option(False,  "--dry-run",      help="Show candidates without processing"),
):
    """
    Batch enrich contacts with missing information.

    Targets contacts missing the specified field, prioritising those whose
    company has a website. Tries email pattern inference first, then website scraping.
    """
    db = SessionLocal()
    try:
        q = db.query(Contact).join(Company, Contact.company_id == Company.id, isouter=True)

        if missing == "email":
            q = q.filter(Contact.email.is_(None))
        elif missing == "mobile_number":
            q = q.filter(Contact.mobile_number.is_(None))
        elif missing != "any":
            rprint(f"[red]Unknown --missing value:[/red] {missing}. Use email, mobile_number, or any.")
            raise typer.Exit(1)

        candidates = q.limit(limit * 3).all()  # fetch extra since some will have no URL

        # prioritise contacts whose company has a website (more likely to succeed)
        candidates.sort(key=lambda c: 0 if (c.company and (c.company.website or c.company.domain)) else 1)
        candidates = candidates[:limit]

        if not candidates:
            rprint(f"[yellow]No contacts found missing {missing}.[/yellow]")
            return

        rprint(f"\n[bold]Contacts to enrich:[/bold] {len(candidates)}  [dim](missing: {missing})[/dim]\n")

        if dry_run:
            table = Table(header_style="bold cyan")
            table.add_column("Name",    min_width=22)
            table.add_column("Company", min_width=24)
            table.add_column("Has URL", width=9, justify="center")
            for c in candidates:
                has_url = bool(c.company and (c.company.website or c.company.domain))
                table.add_row(
                    f"{c.first_name or ''} {c.last_name or ''}".strip(),
                    c.company.name if c.company else "—",
                    "[green]✓[/green]" if has_url else "[red]✗[/red]",
                )
            console.print(table)
            return

        stats = {"updated": 0, "skipped": 0, "nothing_found": 0}

        for i, contact in enumerate(candidates, 1):
            name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
            rprint(f"\n[bold][{i}/{len(candidates)}][/bold] {name}  [dim]{contact.job_title or ''}[/dim]")
            result = _process_contact(contact, db, force=force, auto_approve=yes)
            stats[result] = stats.get(result, 0) + 1

        table = Table(title="Enrich Summary", show_header=False, min_width=28)
        table.add_column("Result", style="bold")
        table.add_column("Count",  justify="right", style="cyan")
        table.add_row("Updated",       str(stats["updated"]))
        table.add_row("Skipped",       str(stats["skipped"]))
        table.add_row("Nothing found", str(stats["nothing_found"]))
        console.print()
        console.print(table)
    finally:
        db.close()


def run_discover_contacts(company: Company, db, auto_approve: bool = False) -> dict:
    """
    Core discovery logic — importable by other modules (e.g. workflow).
    Returns stats dict: {added, skipped, exists}.
    """
    company_id = company.id
    base_url   = company.website or (f"https://{company.domain}" if company.domain else None)

    if not base_url:
        rprint(f"  [red]No website — run crm scrape detect-company {company_id} first.[/red]")
        return {"added": 0, "skipped": 0, "exists": 0}

    console.print("  [dim]Fetching team pages...[/dim]", end=" ")
    html, plain = _fetch_best_team_page(base_url)
    if not html:
        console.print("[red]no content[/red]")
        return {"added": 0, "skipped": 0, "exists": 0}
    console.print("[green]ok[/green]")

    console.print("  [dim]Extracting team members...[/dim]", end=" ")
    members = _extract_all_team_members(html, plain or "")
    if not members:
        console.print("[yellow]none found[/yellow]")
        return {"added": 0, "skipped": 0, "exists": 0}
    console.print(f"[green]{len(members)} found[/green]\n")

    stats = {"added": 0, "skipped": 0, "exists": 0}

    for i, member in enumerate(members, 1):
        first = (member.get("first_name") or "").strip()
        last  = (member.get("last_name")  or "").strip()
        if not first and not last:
            continue

        name = f"{first} {last}".strip()

        existing = None
        if member.get("email"):
            existing = db.query(Contact).filter(Contact.email == member["email"]).first()
        if not existing and member.get("profile_url"):
            existing = db.query(Contact).filter(Contact.profile_url == member["profile_url"]).first()
        if not existing and first and last:
            existing = db.query(Contact).filter(
                Contact.first_name == first,
                Contact.last_name  == last,
                Contact.company_id == company_id,
            ).first()

        if existing:
            rprint(f"  [dim][{i}/{len(members)}] {name} — already in CRM[/dim]")
            stats["exists"] += 1
            continue

        table = Table(title=f"New contact [{i}/{len(members)}]", header_style="bold cyan", show_lines=True)
        table.add_column("Field", style="bold", width=16)
        table.add_column("Value", min_width=32)
        for field, label in [("first_name","First name"),("last_name","Last name"),
                              ("job_title","Job title"),("email","Email"),
                              ("mobile_number","Phone"),("profile_url","LinkedIn")]:
            val = member.get(field)
            if val:
                table.add_row(label, str(val))
        table.add_row("Company", company.name)
        console.print(table)

        if not auto_approve:
            choice = typer.prompt("  Add this contact? (a=add, s=skip)", default="a").strip().lower()
            if choice != "a":
                stats["skipped"] += 1
                continue

        db.add(Contact(
            first_name    = first or None,
            last_name     = last or None,
            job_title     = member.get("job_title"),
            email         = member.get("email"),
            mobile_number = member.get("mobile_number"),
            profile_url   = member.get("profile_url"),
            company_id    = company_id,
        ))
        db.commit()
        stats["added"] += 1
        rprint("  [bold green]✓ Added.[/bold green]")

    return stats


def run_enrich_contacts(company: Company, db, auto_approve: bool = False) -> dict:
    """Enrich all existing contacts at a company. Importable by other modules."""
    contacts = db.query(Contact).filter(Contact.company_id == company.id).all()
    if not contacts:
        rprint("  [dim]No contacts to enrich.[/dim]")
        return {"updated": 0, "skipped": 0, "nothing_found": 0}

    stats = {"updated": 0, "skipped": 0, "nothing_found": 0}
    for i, contact in enumerate(contacts, 1):
        name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        rprint(f"\n  [bold][{i}/{len(contacts)}][/bold] {name}  [dim]{contact.job_title or ''}[/dim]")
        result = _process_contact(contact, db, force=False, auto_approve=auto_approve)
        stats[result] = stats.get(result, 0) + 1
    return stats


@app.command("discover-contacts")
def discover_contacts(
    company_id: str  = typer.Argument(..., help="Company ID to scrape for new contacts"),
    yes:        bool = typer.Option(False, "--yes", "-y", help="Auto-add all new contacts without prompting"),
):
    """Scrape a company's team pages and add any people not yet in the CRM."""
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            rprint(f"[red]Company not found:[/red] {company_id}")
            raise typer.Exit(1)

        rprint(f"\n[bold]{company.name}[/bold]  [dim]{company.website or company.domain or 'no URL'}[/dim]")
        stats = run_discover_contacts(company, db, auto_approve=yes)

        summary = Table(title="Discovery Summary", show_header=False, min_width=26)
        summary.add_column("Result", style="bold")
        summary.add_column("Count",  justify="right", style="cyan")
        summary.add_row("Added",          str(stats["added"]))
        summary.add_row("Skipped",        str(stats["skipped"]))
        summary.add_row("Already in CRM", str(stats["exists"]))
        console.print()
        console.print(summary)
    finally:
        db.close()
