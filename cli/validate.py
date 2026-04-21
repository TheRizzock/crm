import glob
import json
import os
import time

import dns.resolver
import requests
import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from cli import state

load_dotenv()

app = typer.Typer(help="Email validation commands (ZeroBounce)")
console = Console()

API_KEY = os.getenv("ZEROBOUNCE_API_KEY")
BATCH_ENDPOINT = "https://api.zerobounce.net/v2/validatebatch"
BATCH_SIZE = 200

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/raw_leads"))


# ── helpers ──────────────────────────────────────────────────────────────────

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


def _has_mx(domain: str) -> bool:
    try:
        dns.resolver.resolve(domain, "MX", lifetime=3)
        return True
    except Exception:
        return False


def _is_validatable(c: dict) -> bool:
    """Contact needs ZeroBounce validation: has email, not already sent, not already validated."""
    return (
        bool(c.get("email"))
        and c.get("send_status") != "sent"
        and not c.get("zb_status")
    )


def _validate_batch_api(emails: list[dict]) -> dict[str, dict]:
    payload = {"api_key": API_KEY, "email_batch": emails}
    resp = requests.post(BATCH_ENDPOINT, json=payload, timeout=60)
    resp.raise_for_status()
    results = {}
    for item in resp.json().get("email_batch", []):
        addr = item.get("address", "").lower()
        results[addr] = {
            "zb_status": item.get("status"),
            "zb_sub_status": item.get("sub_status"),
            "zb_free_email": item.get("free_email"),
            "zb_did_you_mean": item.get("did_you_mean") or None,
        }
    return results


def _run_validation(filepath: str, limit: int | None = None) -> None:
    if not API_KEY:
        rprint("[bold red]ZEROBOUNCE_API_KEY not set.[/bold red] Add it to your .env file.")
        raise typer.Exit(1)

    contacts = _load(filepath)
    pending_indices = [i for i, c in enumerate(contacts) if _is_validatable(c)]

    if not pending_indices:
        rprint("[yellow]No contacts left to validate.[/yellow]")
        return

    target = pending_indices[:limit] if limit else pending_indices
    batches = [target[i:i + BATCH_SIZE] for i in range(0, len(target), BATCH_SIZE)]

    rprint(f"\n[bold]Validating [cyan]{len(target)}[/cyan] contacts in [cyan]{len(batches)}[/cyan] batch(es)...[/bold]")

    validated = 0
    for batch_num, batch_indices in enumerate(batches, 1):
        email_payloads = [
            {"email_address": contacts[i]["email"], "ip_address": ""}
            for i in batch_indices
        ]
        console.print(f"  Batch {batch_num}/{len(batches)} — {len(email_payloads)} emails", end=" ")
        try:
            results = _validate_batch_api(email_payloads)
            for i in batch_indices:
                email = contacts[i]["email"].lower()
                contacts[i].update(results.get(email, {}))
                validated += 1
            _save(filepath, contacts)
            console.print("[green]✓[/green]")
        except requests.HTTPError as e:
            console.print(f"[red]HTTP error: {e}[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

        if batch_num < len(batches):
            time.sleep(1)

    rprint(f"\n[bold green]Done.[/bold green] Validated {validated} contacts. File saved.")


# ── commands ──────────────────────────────────────────────────────────────────

@app.command()
def stats():
    """Count emails ready to validate: valid format, MX record exists, not yet ZeroBounced."""
    filepath = _require_file()
    contacts = _load(filepath)

    total = len(contacts)
    already_sent = sum(1 for c in contacts if c.get("send_status") == "sent")
    already_validated = sum(1 for c in contacts if c.get("zb_status") and c.get("send_status") != "sent")
    no_email = sum(1 for c in contacts if not c.get("email"))

    pending = [c for c in contacts if _is_validatable(c)]

    rprint(f"\n[bold]Checking MX records for [cyan]{len(pending)}[/cyan] pending contacts...[/bold]")

    mx_ok = 0
    mx_fail = 0
    seen_domains: dict[str, bool] = {}

    with console.status("Resolving MX records..."):
        for c in pending:
            domain = c["email"].split("@")[-1].lower()
            if domain not in seen_domains:
                seen_domains[domain] = _has_mx(domain)
            if seen_domains[domain]:
                mx_ok += 1
            else:
                mx_fail += 1

    table = Table(title=f"Validate Stats — {os.path.basename(filepath)}", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right", style="cyan")

    table.add_row("Total contacts", str(total))
    table.add_row("Already sent (skipped)", str(already_sent))
    table.add_row("Already ZeroBounced", str(already_validated))
    table.add_row("No email address", str(no_email))
    table.add_row("─" * 20, "─" * 6)
    table.add_row("Pending validation", str(len(pending)))
    table.add_row("  ↳ MX record found", str(mx_ok))
    table.add_row("  ↳ MX record missing", str(mx_fail))

    console.print()
    console.print(table)
    console.print()


@app.command(name="run")
def run(
    all: bool = typer.Option(False, "--all", help="Validate all remaining contacts"),
    number: int = typer.Option(None, "--number", "-n", help="Validate the next N contacts"),
):
    """Validate emails via ZeroBounce. Use --all or --number N."""
    if not all and number is None:
        rprint("[bold red]Specify --all or --number N.[/bold red]")
        raise typer.Exit(1)

    filepath = _require_file()
    limit = None if all else number
    _run_validation(filepath, limit=limit)


@app.command(name="set-file")
def set_file(
    path: str = typer.Argument(None, help="Path to the JSON leads file"),
):
    """Set the active leads file for this session. Prompts with a selection menu if no path given."""
    if path:
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            rprint(f"[red]File not found:[/red] {abs_path}")
            raise typer.Exit(1)
        state.set_active_file(abs_path)
        rprint(f"[green]Active file set:[/green] {abs_path}")
        return

    # discover all JSON files under data/raw_leads/
    pattern = os.path.join(DATA_ROOT, "**/*.json")
    files = sorted(glob.glob(pattern, recursive=True))

    if not files:
        rprint(f"[red]No JSON files found under {DATA_ROOT}[/red]")
        raise typer.Exit(1)

    rprint("\n[bold]Available lead files:[/bold]\n")
    for idx, fp in enumerate(files, 1):
        rel = os.path.relpath(fp)
        size = len(_load(fp))
        rprint(f"  [cyan]{idx}[/cyan]. {rel}  [dim]({size} contacts)[/dim]")

    rprint()
    choice = typer.prompt("Enter number")

    try:
        selected = files[int(choice) - 1]
    except (ValueError, IndexError):
        rprint("[red]Invalid selection.[/red]")
        raise typer.Exit(1)

    state.set_active_file(os.path.abspath(selected))
    rprint(f"\n[green]Active file set:[/green] {os.path.relpath(selected)}")
