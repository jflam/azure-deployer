import os
import time
from azure.identity import DefaultAzureCredential
from azure.mgmt.subscription import SubscriptionClient
from azure.mgmt.postgresqlflexibleservers import PostgreSQLManagementClient
from azure.core.exceptions import HttpResponseError
from rich.console import Console
from rich.progress import Progress, TextColumn, BarColumn, SpinnerColumn, TimeElapsedColumn

sub_id = "a2f3511c-c2c5-434b-89e9-8632a6a46d01"
cred   = DefaultAzureCredential()
console = Console()

# 1) All regions visible to the subscription
console.print("[bold blue]Fetching all Azure regions for subscription...[/bold blue]")
sub_client = SubscriptionClient(cred)
regions = [loc.name for loc in sub_client.subscriptions.list_locations(sub_id)]
console.print(f"[green]Found {len(regions)} regions[/green]")

# 2) Probe each region for Flexible-Server availability
pg_client = PostgreSQLManagementClient(cred, sub_id)
allowed = []

with Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TimeElapsedColumn(),
) as progress:
    task = progress.add_task("[cyan]Checking PostgreSQL Flexible Server availability...[/cyan]", total=len(regions))
    
    for region in regions:
        try:
            progress.update(task, description=f"[cyan]Checking region: [bold]{region}[/bold][/cyan]")
            for cap in pg_client.location_based_capabilities.execute(region):
                if cap.status == "Available":
                    allowed.append(region)
                    progress.update(task, description=f"[green]Found available region: [bold]{region}[/bold][/green]")
                    time.sleep(0.2)  # Small delay for visibility
                    break  # no need to scan further pages
        except HttpResponseError as e:
            # Service not offered in this region → skip it quietly
            if isinstance(e, HttpResponseError) and "NoRegisteredProviderFound" in str(e):
                progress.update(task, description=f"[yellow]Region not supported: [bold]{region}[/bold][/yellow]")
                time.sleep(0.1)  # Small delay for visibility
                continue
            # Anything else is unexpected → re-raise for visibility
            progress.update(task, description=f"[red]Error in region {region}: {str(e)}[/red]")
            raise
        
        # Update progress
        progress.update(task, advance=1)

# Final output with rich formatting
console.print(f"\n[bold green]✓[/bold green] [bold]PostgreSQL Flexible Server is available in {len(allowed)} regions:[/bold]")
for region in allowed:
    console.print(f"  [green]●[/green] {region}")