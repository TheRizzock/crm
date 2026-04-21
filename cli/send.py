import json
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

from cli import state, config as cli_config

load_dotenv()

app = typer.Typer(help="Email sending commands")
console = Console()

resend.api_key = os.getenv("RESEND_API_KEY")

# ── Warming tiers ─────────────────────────────────────────────────────────────
TIERS = {
    1: (5,  15,  "Warmup    — 5–15 emails"),
    2: (15, 30,  "Light     — 15–30 emails"),
    3: (30, 60,  "Medium    — 30–60 emails"),
    4: (60, 100, "Full send — 60–100 emails"),
}

SENDABLE_ZB = {"valid", "catch-all"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _load(filepath: str) -> list[dict]:
    with open(filepath) as f:
        return json.load(f)


def _save(filepath: str, contacts: list[dict]) -> None:
    with open(filepath, "w") as f:
        json.dump(contacts, f, indent=2)


def _require_file() -> str:
    active = state.get_active_file()
    if not active or not os.path.exists(active):
        rprint("[bold red]No active file set.[/bold red] Run [cyan]validate set-file[/cyan] first.")
        raise typer.Exit(1)
    return active


def _sendable_contacts(contacts: list[dict]) -> list[dict]:
    return [
        c for c in contacts
        if c.get("email")
        and c.get("zb_status") in SENDABLE_ZB
        and c.get("send_status") not in {"sent", "delivered", "bounced", "skipped"}
    ]


def _random_send_times(n: int, tz_name: str, eod_hour: int) -> list[datetime]:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    eod = now.replace(hour=eod_hour, minute=0, second=0, microsecond=0)

    if now >= eod:
        tomorrow = now + timedelta(days=1)
        start = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
        eod = tomorrow.replace(hour=eod_hour, minute=0, second=0, microsecond=0)
    else:
        start = now + timedelta(minutes=20)  # Resend requires scheduled_at to be well in the future

    window_seconds = int((eod - start).total_seconds())
    if window_seconds <= 0:
        window_seconds = 3600

    offsets = sorted(random.randint(0, window_seconds) for _ in range(n))
    return [start + timedelta(seconds=s) for s in offsets]


def _build_preview_table(queue: list[dict], mock: bool, template_id: str) -> Table:
    title = "[bold yellow]MOCK PREVIEW[/bold yellow]" if mock else "[bold green]SEND QUEUE[/bold green]"
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("#",           width=4,  justify="right")
    table.add_column("Name",        min_width=18)
    table.add_column("Title",       min_width=20)
    table.add_column("Email",       min_width=24)
    table.add_column("ZB Status",   width=12)
    table.add_column("Send Status", width=12)
    table.add_column("Scheduled",   width=19)
    table.add_column("Template",    min_width=38)

    zb_colors = {"valid": "green", "catch-all": "yellow"}

    for idx, item in enumerate(queue, 1):
        c = item["contact"]
        zb = c.get("zb_status", "—")
        zb_styled = f"[{zb_colors.get(zb, 'red')}]{zb}[/]"
        send_st = c.get("send_status") or "—"
        scheduled = item["scheduled_at"].strftime("%m/%d %I:%M:%S %p") if not mock else "[dim]mock[/dim]"

        table.add_row(
            str(idx),
            f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
            (c.get("job_title") or "")[:28],
            c.get("email", ""),
            zb_styled,
            send_st,
            scheduled,
            f"[dim]{template_id}[/dim]",
        )

    return table


def _do_send(filepath: str, contacts: list[dict], queue: list[dict], cfg: dict) -> None:
    rprint(f"\n[bold]Scheduling [cyan]{len(queue)}[/cyan] emails via Resend...[/bold]\n")
    rprint(f"  [dim]From: {cfg['from_address']}[/dim]")
    rprint(f"  [dim]Template: {cfg['template_id']}[/dim]\n")

    for idx, item in enumerate(queue, 1):
        c = item["contact"]
        scheduled_at = item["scheduled_at"]
        contact_idx = item["index"]

        scheduled_str = scheduled_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        params = {
            "from": cfg["from_address"],
            "to": [c["email"]],
            "scheduled_at": scheduled_str,
            "template": {
                "id": cfg["template_id"],
                "variables": {
                    "FIRST_NAME": c.get("first_name", "there"),
                },
            },
        }

        try:
            resp = resend.Emails.send(params)
            resend_id = resp.get("id", "?") if isinstance(resp, dict) else getattr(resp, "id", "?")
            contacts[contact_idx]["send_status"] = "sent"
            contacts[contact_idx]["resend_id"] = resend_id
            contacts[contact_idx]["scheduled_at"] = scheduled_str
            console.print(f"  [green]✓[/green] [{idx}/{len(queue)}] {c.get('email')} → {scheduled_at.strftime('%I:%M %p')}")
        except Exception as e:
            console.print(f"  [red]✗[/red] [{idx}/{len(queue)}] {c.get('email')} — {e}")

        _save(filepath, contacts)
        time.sleep(0.25)  # stay under Resend's 5 req/sec rate limit

    rprint(f"\n[bold green]Done.[/bold green] File updated.")


# ── commands ─────────────────────────────────────────────────────────────────

@app.command()
def test(
    email: str = typer.Argument(None, help="Recipient email address"),
):
    """Send a test email to check deliverability and spam placement."""
    cfg = cli_config.require_config()

    if not email:
        default = cfg.get("test_email") or ""
        prompt = f"Send test to" + (f" [{default}]" if default else "")
        email = typer.prompt(prompt, default=default)

    if not email:
        rprint("[red]No email address provided.[/red]")
        raise typer.Exit(1)

    params = {
        "from": cfg["from_address"],
        "to": [email],
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
        resp = resend.Emails.send(params)
        resend_id = resp.get("id", "?") if isinstance(resp, dict) else getattr(resp, "id", "?")
        rprint(f"[bold green]✓ Sent.[/bold green] Resend ID: [dim]{resend_id}[/dim]")
    except Exception as e:
        rprint(f"[bold red]✗ Failed:[/bold red] {e}")
        raise typer.Exit(1)

@app.command()
def schedule(
    tier: int  = typer.Option(None,  "--tier", "-t", help="Warming tier 1–4 (overrides config default)"),
    mock: bool = typer.Option(False, "--mock", "-m", help="Preview only — no emails sent"),
    tz:   str  = typer.Option(None,  "--tz",         help="Timezone override (overrides config)"),
):
    """
    Schedule a batch of emails randomly between now and end of business.

    Use --mock to preview the queue without sending anything.
    Use --tier to control volume (1=warmup, 4=full).
    """
    cfg = cli_config.require_config()

    # CLI flags override config, config overrides built-in defaults
    effective_tier = tier if tier is not None else int(cfg.get("default_tier", 1))
    effective_tz   = tz   if tz   is not None else cfg.get("timezone", "America/New_York")
    effective_eod  = int(cfg.get("eod_hour", 17))

    if effective_tier not in TIERS:
        rprint(f"[red]Invalid tier.[/red] Choose 1–4.")
        raise typer.Exit(1)

    filepath = _require_file()
    contacts = _load(filepath)

    t_min, t_max, t_label = TIERS[effective_tier]
    sendable = _sendable_contacts(contacts)

    if not sendable:
        rprint("[yellow]No sendable contacts found.[/yellow] Make sure emails are ZeroBounce-validated first.")
        raise typer.Exit(0)

    n = min(random.randint(t_min, t_max), len(sendable))
    selected = random.sample(sendable, n)
    send_times = _random_send_times(n, tz_name=effective_tz, eod_hour=effective_eod)

    email_to_idx = {c["email"]: i for i, c in enumerate(contacts)}
    queue = [
        {
            "contact": c,
            "index": email_to_idx[c["email"]],
            "scheduled_at": send_times[i],
        }
        for i, c in enumerate(selected)
    ]

    rprint(f"\n[bold]Tier {effective_tier}[/bold] — {t_label}")
    rprint(f"[bold]From:[/bold]         {cfg['from_address']}")
    rprint(f"[bold]Sendable pool:[/bold] {len(sendable)} contacts   [bold]Selected:[/bold] {n}")
    rprint(f"[bold]File:[/bold]         {os.path.relpath(filepath)}")
    if mock:
        rprint("[bold yellow]\n⚠  MOCK MODE — nothing will be sent\n[/bold yellow]")

    console.print()
    console.print(_build_preview_table(queue, mock=mock, template_id=cfg["template_id"]))
    console.print()

    if mock:
        rprint("[dim]Run without --mock to send for real.[/dim]")
        return

    confirm = typer.confirm(f"Send {n} emails as scheduled above?")
    if not confirm:
        rprint("[yellow]Aborted.[/yellow]")
        raise typer.Exit(0)

    _do_send(filepath, contacts, queue, cfg)
