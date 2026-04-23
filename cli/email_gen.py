import os

import openai
import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel

from app.db import SessionLocal
from app.models import Contact, Company

load_dotenv()

app     = typer.Typer(help="AI-assisted email drafting (experimental)")
console = Console()

_CLIENT = None


def _get_client() -> openai.OpenAI:
    global _CLIENT
    if _CLIENT is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            rprint("[bold red]OPENAI_API_KEY not set.[/bold red]")
            raise typer.Exit(1)
        _CLIENT = openai.OpenAI(api_key=api_key)
    return _CLIENT


DRAFT_PROMPT = """\
You are writing a short, personalized cold outreach email on behalf of Dan Kowalsky.

Recipient:
  Name: {first_name} {last_name}
  Title: {job_title}
  Company: {company_name}
  Industry: {industry}
  Location: {location}
  Company description: {company_description}

Intention: {intention}

Guidelines:
- 3–5 sentences max. No fluff.
- Sound like a real person, not a sales bot.
- Do not mention you found them on LinkedIn.
- No subject line — body only.
- End with a soft call to action.
"""


@app.command("draft")
def draft_email(
    contact_id: str = typer.Argument(..., help="Contact ID to draft an email for"),
    intention: str  = typer.Option("", "--intention", "-i", help="What you want to achieve with this email"),
    model: str      = typer.Option("gpt-4.1-nano", "--model", "-m", help="OpenAI model to use"),
):
    """
    Generate a draft cold email for a contact using their CRM context.

    This is a sandbox — nothing is saved or sent. Use it to explore
    what AI-generated personalisation looks like before wiring it up.
    """
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            rprint(f"[red]Contact not found:[/red] {contact_id}")
            raise typer.Exit(1)

        company = db.query(Company).filter(Company.id == contact.company_id).first() if contact.company_id else None

        if not intention:
            intention = typer.prompt("  What's the intention for this email?")

        location = ", ".join(p for p in [contact.city, contact.state, contact.country] if p)

        prompt = DRAFT_PROMPT.format(
            first_name=contact.first_name or "",
            last_name=contact.last_name or "",
            job_title=contact.job_title or "unknown title",
            company_name=company.name if company else "their company",
            industry=contact.industry or (company.description[:80] if company and company.description else "unknown"),
            location=location or "unknown",
            company_description=company.description or "no description available",
            intention=intention,
        )

        rprint(f"\n[dim]Drafting for [bold]{contact.first_name} {contact.last_name}[/bold] · {contact.job_title or '—'} @ {company.name if company else '—'}[/dim]")
        rprint(f"[dim]Intention: {intention}[/dim]\n")

        response = _get_client().chat.completions.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        draft = response.choices[0].message.content.strip()
        console.print(Panel(draft, title="Draft", border_style="cyan", padding=(1, 2)))

    finally:
        db.close()
