"""
CLI config — persists to .cli_config.json at project root.

Required fields (CLI will block and prompt if missing):
  from_address, template_id

Optional fields (have sensible defaults):
  test_email, timezone, eod_hour, default_tier
"""

import json
import os

import typer
from rich import print as rprint
from rich.table import Table
from rich.console import Console

CONFIG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.cli_config.json"))

console = Console()

# Fields that must be set before any send command runs
REQUIRED = ["from_address", "template_id"]

DEFAULTS = {
    "timezone":     "America/New_York",
    "eod_hour":     17,
    "default_tier": 1,
    "test_email":   "",
}

FIELD_DESCRIPTIONS = {
    "from_address":  "Sender name + email  e.g. Dan Kowalsky <dan@yourdomain.com>",
    "template_id":   "Resend template ID   e.g. 90376431-09d5-4e5d-8981-24a072db23f5",
    "test_email":    "Test recipient email e.g. you@yourdomain.com",
    "timezone":      "Scheduling timezone  e.g. America/New_York",
    "eod_hour":      "End-of-day hour (24h) e.g. 17 = 5 PM",
    "default_tier":  "Default warming tier (1–4)",
}


# ── persistence ───────────────────────────────────────────────────────────────

def load() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save(cfg: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def get(key: str):
    cfg = load()
    return cfg.get(key, DEFAULTS.get(key))


def set_value(key: str, value) -> None:
    cfg = load()
    cfg[key] = value
    save(cfg)


# ── guard — call this at the top of any send command ─────────────────────────

def require_config() -> dict:
    """
    Returns the full config dict. Exits with a helpful message if any
    required field is missing.
    """
    cfg = {**DEFAULTS, **load()}
    missing = [k for k in REQUIRED if not cfg.get(k)]

    if missing:
        rprint("\n[bold red]Missing required config fields:[/bold red]")
        for k in missing:
            rprint(f"  [cyan]{k}[/cyan] — {FIELD_DESCRIPTIONS.get(k, '')}")
        rprint(f"\nRun [bold]./crm config set <field> <value>[/bold] or [bold]./crm config init[/bold] to set up.\n")
        raise typer.Exit(1)

    return cfg


# ── typer command group ───────────────────────────────────────────────────────

app = typer.Typer(help="Manage CLI configuration")


@app.command(name="show")
def show():
    """Display current config."""
    cfg = {**DEFAULTS, **load()}

    table = Table(title="CRM CLI Config", show_header=True, header_style="bold cyan")
    table.add_column("Field",       style="bold",  min_width=16)
    table.add_column("Value",       min_width=40)
    table.add_column("Required",    width=10, justify="center")
    table.add_column("Description", style="dim")

    for key, desc in FIELD_DESCRIPTIONS.items():
        val = cfg.get(key, "")
        required = "✓" if key in REQUIRED else ""
        display = f"[red](not set)[/red]" if not val else str(val)
        table.add_row(key, display, required, desc)

    console.print()
    console.print(table)
    console.print()


@app.command(name="set")
def set_cmd(
    field: str = typer.Argument(..., help="Config field name"),
    value: str = typer.Argument(..., help="Value to set"),
):
    """Set a single config field.  e.g.  ./crm config set from_address 'Dan <dan@domain.com>'"""
    if field not in FIELD_DESCRIPTIONS:
        rprint(f"[red]Unknown field:[/red] {field}")
        rprint(f"Valid fields: {', '.join(FIELD_DESCRIPTIONS.keys())}")
        raise typer.Exit(1)

    # coerce numeric fields
    if field in ("eod_hour", "default_tier"):
        try:
            value = int(value)
        except ValueError:
            rprint(f"[red]{field} must be an integer.[/red]")
            raise typer.Exit(1)

    set_value(field, value)
    rprint(f"[green]✓[/green] [bold]{field}[/bold] = {value}")


@app.command(name="init")
def init():
    """Interactive setup wizard — walks through every config field."""
    cfg = {**DEFAULTS, **load()}

    rprint("\n[bold]CRM CLI Setup[/bold]  (press Enter to keep current value)\n")

    for key, desc in FIELD_DESCRIPTIONS.items():
        current = cfg.get(key, "")
        prompt_text = f"  {key}  [dim]({desc})[/dim]"
        placeholder = f"[dim]{current}[/dim]" if current else "[dim](none)[/dim]"
        rprint(f"{prompt_text}")
        new_val = typer.prompt(f"  Current: {current or '(not set)'}\n  New value", default=str(current) if current else "")

        if new_val:
            if key in ("eod_hour", "default_tier"):
                try:
                    new_val = int(new_val)
                except ValueError:
                    rprint(f"  [red]Must be an integer, keeping current.[/red]")
                    new_val = current
            cfg[key] = new_val

        rprint()

    save(cfg)
    rprint("[bold green]Config saved.[/bold green]")
    show()
