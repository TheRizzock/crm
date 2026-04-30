import os
import random
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import resend
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from sqlalchemy import exists, func

from app.db import SessionLocal
from app.models import Contact, Activity
from cli import config as cli_config

load_dotenv()

app = typer.Typer(help="Email sending commands")
console = Console()

resend.api_key = os.getenv("RESEND_API_KEY")

TIERS = {
    1: (5,  15,  "Warmup    — 5–15 emails"),
    2: (15, 30,  "Light     — 15–30 emails"),
    3: (30, 60,  "Medium    — 30–60 emails"),
    4: (60, 100, "Full send — 60–100 emails"),
}

SENDABLE_ZB = {"valid", "catch-all"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _sendable_contacts(db, days_since: int | None = None) -> list[Contact]:
    bounced_sq = (
        db.query(Activity.contact_id)
        .filter(Activity.type == "email", Activity.status == "bounced")
        .subquery()
    )

    q = db.query(Contact).filter(
        Contact.email.isnot(None),
        Contact.zb_status.in_(SENDABLE_ZB),
        Contact.do_not_email.isnot(True),
        ~exists().where(Contact.id == bounced_sq.c.contact_id),
    )

    if days_since is not None:
        # contacts never emailed OR last email was > N days ago
        cutoff = datetime.utcnow() - timedelta(days=days_since)
        last_email_sq = (
            db.query(
                Activity.contact_id,
                func.max(Activity.created_at).label("last_at"),
            )
            .filter(Activity.type == "email")
            .group_by(Activity.contact_id)
            .subquery()
        )
        q = (
            q.outerjoin(last_email_sq, Contact.id == last_email_sq.c.contact_id)
            .filter(
                (last_email_sq.c.last_at.is_(None)) |
                (last_email_sq.c.last_at < cutoff)
            )
        )
    else:
        # default: never emailed at all
        q = q.filter(
            ~exists().where(
                (Activity.contact_id == Contact.id) &
                (Activity.type == "email")
            )
        )

    return q.all()


def _random_send_times(n: int, tz_name: str, eod_hour: int) -> list[datetime]:
    tz  = ZoneInfo(tz_name)
    now = datetime.now(tz)
    eod = now.replace(hour=eod_hour, minute=0, second=0, microsecond=0)

    if now >= eod:
        tomorrow = now + timedelta(days=1)
        start = tomorrow.replace(hour=9,        minute=0, second=0, microsecond=0)
        eod   = tomorrow.replace(hour=eod_hour, minute=0, second=0, microsecond=0)
    else:
        start = now + timedelta(minutes=20)

    window_seconds = max(int((eod - start).total_seconds()), 3600)
    offsets = sorted(random.randint(0, window_seconds) for _ in range(n))
    return [start + timedelta(seconds=s) for s in offsets]


def _build_preview_table(queue: list[dict], mock: bool, cfg: dict) -> Table:
    title = "[bold yellow]MOCK PREVIEW[/bold yellow]" if mock else "[bold green]SEND QUEUE[/bold green]"
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("#",         width=4,  justify="right")
    table.add_column("Name",      min_width=18)
    table.add_column("Title",     min_width=20)
    table.add_column("Email",     min_width=24)
    table.add_column("ZB Status", width=12)
    table.add_column("Scheduled", width=19)
    table.add_column("Template",  min_width=38)

    zb_colors = {"valid": "green", "catch-all": "yellow"}

    for idx, item in enumerate(queue, 1):
        c         = item["contact"]
        zb        = c.zb_status or "—"
        scheduled = item["scheduled_at"].strftime("%m/%d %I:%M:%S %p") if not mock else "[dim]mock[/dim]"
        table.add_row(
            str(idx),
            f"{c.first_name or ''} {c.last_name or ''}".strip(),
            (c.job_title or "")[:28],
            c.email,
            f"[{zb_colors.get(zb, 'red')}]{zb}[/]",
            scheduled,
            f"[dim]{cfg['template_id']}[/dim]",
        )

    return table


def _do_send(db, queue: list[dict], cfg: dict) -> None:
    rprint(f"\n[bold]Scheduling [cyan]{len(queue)}[/cyan] emails via Resend...[/bold]\n")
    rprint(f"  [dim]From:     {cfg['from_address']}[/dim]")
    rprint(f"  [dim]Template: {cfg['template_id']}[/dim]")
    if cfg.get("subject"):
        rprint(f"  [dim]Subject:  {cfg['subject']}[/dim]")
    rprint()

    sent = 0
    for idx, item in enumerate(queue, 1):
        contact      = item["contact"]
        scheduled_at = item["scheduled_at"]
        scheduled_str = scheduled_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        params = {
            "from":         cfg["from_address"],
            "to":           [contact.email],
            "scheduled_at": scheduled_str,
            "template": {
                "id": cfg["template_id"],
                "variables": {"FIRST_NAME": contact.first_name or "there"},
            },
        }

        try:
            resp      = resend.Emails.send(params)
            resend_id = resp.get("id", "?") if isinstance(resp, dict) else getattr(resp, "id", "?")

            db.add(Activity(
                contact_id=contact.id,
                type="email",
                subject=cfg.get("subject") or None,
                body=cfg["template_id"],
                status="scheduled",
                resend_id=resend_id,
            ))
            db.commit()
            sent += 1

            console.print(
                f"  [green]✓[/green] [{idx}/{len(queue)}] {contact.email}"
                f" → {scheduled_at.strftime('%I:%M %p')}  [dim]{resend_id}[/dim]"
            )
        except Exception as e:
            db.rollback()
            console.print(f"  [red]✗[/red] [{idx}/{len(queue)}] {contact.email} — {e}")

        time.sleep(0.25)  # stay under Resend's 5 req/sec rate limit

    rprint(f"\n[bold green]Done.[/bold green] {sent}/{len(queue)} emails scheduled.")


# ── commands ──────────────────────────────────────────────────────────────────

@app.command()
def test(email: str = typer.Argument(None, help="Recipient email address")):
    """Send a test email to check deliverability and spam placement."""
    cfg = cli_config.require_config()

    if not email:
        default = cfg.get("test_email") or ""
        email   = typer.prompt("Send test to" + (f" [{default}]" if default else ""), default=default)

    if not email:
        rprint("[red]No email address provided.[/red]")
        raise typer.Exit(1)

    params = {
        "from":    cfg["from_address"],
        "to":      [email],
        "subject": "Test Email",
        "html": (
            "<p>Hi,</p>"
            "<p>This is a test email sent from the CRM CLI to check deliverability and spam placement.</p>"
            "<p>If you're seeing this in your inbox — we're good to go.</p>"
            "<p>— Dan</p>"
        ),
    }

    rprint(f"\n  [bold]From:[/bold]    {cfg['from_address']}")
    rprint(f"  [bold]To:[/bold]      {email}")
    rprint(f"  [bold]Subject:[/bold] Test Email\n")

    try:
        resp      = resend.Emails.send(params)
        resend_id = resp.get("id", "?") if isinstance(resp, dict) else getattr(resp, "id", "?")
        rprint(f"[bold green]✓ Sent.[/bold green] Resend ID: [dim]{resend_id}[/dim]")
    except Exception as e:
        rprint(f"[bold red]✗ Failed:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def schedule(
    tier:       int  = typer.Option(None,  "--tier",       "-t", help="Warming tier 1–4 (overrides config default)"),
    mock:       bool = typer.Option(False, "--mock",       "-m", help="Preview only — no emails sent"),
    tz:         str  = typer.Option(None,  "--tz",               help="Timezone override"),
    days_since: int  = typer.Option(None,  "--days-since",       help="Include contacts not emailed in the last N days (default: never emailed only)"),
):
    """
    Schedule a batch of emails randomly between now and end of business.

    By default targets contacts that have never been emailed.
    Use --days-since 7 to also include contacts not emailed in 7+ days (follow-ups).
    """
    cfg = cli_config.require_config()

    effective_tier = tier if tier is not None else int(cfg.get("default_tier", 1))
    effective_tz   = tz   if tz   is not None else cfg.get("timezone", "America/New_York")
    effective_eod  = int(cfg.get("eod_hour", 17))

    if effective_tier not in TIERS:
        rprint(f"[red]Invalid tier.[/red] Choose 1–4.")
        raise typer.Exit(1)

    db = SessionLocal()
    try:
        sendable = _sendable_contacts(db, days_since=days_since)

        if not sendable:
            label = f"not emailed in {days_since}+ days" if days_since is not None else "never emailed"
            rprint(f"[yellow]No sendable contacts ({label}, ZB valid/catch-all).[/yellow]")
            raise typer.Exit(0)

        t_min, t_max, t_label = TIERS[effective_tier]
        n          = min(random.randint(t_min, t_max), len(sendable))
        selected   = random.sample(sendable, n)
        send_times = _random_send_times(n, tz_name=effective_tz, eod_hour=effective_eod)

        queue = [
            {"contact": c, "scheduled_at": send_times[i]}
            for i, c in enumerate(selected)
        ]

        filter_label = f"not emailed in {days_since}+ days" if days_since is not None else "never emailed"
        rprint(f"\n[bold]Tier {effective_tier}[/bold] — {t_label}")
        rprint(f"[bold]From:[/bold]          {cfg['from_address']}")
        rprint(f"[bold]Filter:[/bold]        {filter_label}")
        rprint(f"[bold]Sendable pool:[/bold] {len(sendable)}   [bold]Selected:[/bold] {n}")
        if mock:
            rprint("[bold yellow]\n⚠  MOCK MODE — nothing will be sent\n[/bold yellow]")

        console.print()
        console.print(_build_preview_table(queue, mock=mock, cfg=cfg))
        console.print()

        if mock:
            rprint("[dim]Run without --mock to send for real.[/dim]")
            return

        if not typer.confirm(f"Send {n} emails as scheduled above?"):
            rprint("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

        _do_send(db, queue, cfg)
    finally:
        db.close()
