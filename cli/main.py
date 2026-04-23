import typer
from cli import validate, send, config, backfill, scrape, enrich, workflow
import cli.import_leads as import_leads

app = typer.Typer(
    name="crm",
    help="CRM command-line toolkit",
    no_args_is_help=True,
)

app.add_typer(validate.app,  name="validate",  help="Email validation via ZeroBounce")
app.add_typer(send.app,      name="send",       help="Email scheduling and sending")
app.add_typer(config.app,    name="config",     help="Manage CLI configuration")
app.add_typer(backfill.app,      name="backfill", help="One-time data backfill commands")
app.add_typer(import_leads.app,  name="import",   help="Import leads from JSON into the database")
app.add_typer(scrape.app,        name="scrape",   help="Scrape company websites to hydrate missing fields")
app.add_typer(enrich.app,        name="enrich",   help="Find missing emails, phones and info for contacts")
app.add_typer(workflow.app,      name="workflow", help="Guided workflows that chain multiple enrichment steps together")

if __name__ == "__main__":
    app()
