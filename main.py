"""Azure Provisioner CLI entrypoint."""
import sys
import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from typing import List, Optional

from provisioner.quota.checker import QuotaChecker
from provisioner.quota.resolver import SDKResolver
from provisioner.bicep.generator import BicepGenerator
from provisioner.manifest.parser import ManifestParser

app = typer.Typer(help="Azure Provisioner - Quota-aware Bicep generator and region selector")
console = Console()

@app.command("quota-check")
def quota_check(
    config: str = typer.Option("infra.yaml", "--config", "-c", help="Path to the infrastructure YAML file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't update the manifest with selected region"),
    output: str = typer.Option("region-analysis.json", "--output", "-o", help="Path for quota analysis output"),
    auto_select: bool = typer.Option(False, "--auto-select", help="Automatically select a viable region"),
    debug: bool = typer.Option(False, "--debug", help="Print verbose debug information including all Azure CLI commands")
):
    """Check quotas and select a viable region for deployment."""
    console.print("[bold blue]Checking quotas and viable regions...[/]")
    
    try:
        # Resolve and install required SDKs
        resolver = SDKResolver(config)
        resolver.install_required_sdks()
        
        # Check quotas
        checker = QuotaChecker(config, dry_run=dry_run, debug=debug)
        analysis = checker.check_quotas()
        
        # Save analysis
        analysis.save(output)
        console.print(f"[green]Quota analysis saved to {output}[/]")
        
        # Print viable regions with detailed comparison
        table = Table(title="Regions Quota Analysis")
        table.add_column("Region", style="cyan")
        table.add_column("Status", style="green")
        
        if len(analysis.regions) > 0:
            # Add resource types as columns for comparison
            resource_types = set()
            for quotas in analysis.regions.values():
                for quota in quotas:
                    resource_types.add(quota.resource_type)
            
            for resource_type in sorted(resource_types):
                table.add_column(resource_type.split('/')[-1], justify="right")
            
            # Add rows for each region with quota status
            for region, quotas in sorted(analysis.regions.items()):
                row = [region]
                
                # Status column
                if region in analysis.viable_regions:
                    row.append("✓ VIABLE")
                else:
                    row.append("❌ INSUFFICIENT QUOTA")
                
                # Add quota details for each resource type
                resource_quotas = {q.resource_type: q for q in quotas}
                for resource_type in sorted(resource_types):
                    if resource_type in resource_quotas:
                        quota = resource_quotas[resource_type]
                        quota_summary = []
                        for unit, info in quota.quotas.items():
                            quota_summary.append(f"{unit}: {info.available}/{info.required}")
                        row.append("\n".join(quota_summary))
                    else:
                        row.append("")
                
                table.add_row(*row)
            
            console.print(table)
            
            # Print viable regions summary
            if analysis.viable_regions:
                viable_table = Table(title="Viable Regions Summary")
                viable_table.add_column("Region", style="cyan")
                
                for region in sorted(analysis.viable_regions):
                    viable_table.add_row(region)
                
                console.print(viable_table)
                
                # Link to quota increase if needed
                if len(analysis.viable_regions) < len(analysis.regions):
                    console.print("\n[yellow]Some regions have insufficient quota. To request a quota increase, visit:[/]")
                    console.print("[link]https://portal.azure.com/#blade/Microsoft_Azure_Capacity/QuotaMenuBlade/myQuotas[/link]")
            else:
                console.print("[bold red]NO VIABLE REGIONS FOUND![/]")
                console.print("\n[yellow]To request a quota increase, visit:[/]")
                console.print("[link]https://portal.azure.com/#blade/Microsoft_Azure_Capacity/QuotaMenuBlade/myQuotas[/link]")
                return 2
        else:
            console.print("[bold red]No regions analyzed. Check your configuration.[/]")
            return 1
        
        # Select region
        if auto_select and analysis.viable_regions:
            selected_region = checker.select_region(analysis)
            checker.update_manifest_region(selected_region)
            console.print(f"\n[green]Selected region: {selected_region}[/]")
        elif analysis.viable_regions:
            console.print(f"\n[yellow]Please choose a region from the viable list and update your manifest or run again with --auto-select[/]")
        
        return 0
    
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/]")
        return 1

@app.command("generate")
def generate(
    config: str = typer.Option("infra.yaml", "--config", "-c", help="Path to the infrastructure YAML file"),
    output_dir: str = typer.Option(None, "--output-dir", "-o", help="Directory for generated Bicep files"),
    debug: bool = typer.Option(False, "--debug", help="Print verbose debug information including generated Bicep")
):
    """Generate Bicep template and parameters file from YAML manifest."""
    console.print("[bold blue]Generating Bicep files...[/]")
    
    try:
        # Check that region is specified in the manifest
        manifest = ManifestParser.load(config)
        if not manifest.region:
            console.print("[bold yellow]WARNING: No region specified in manifest. Run quota-check first to select an optimal region.[/]")
            console.print("[yellow]Continuing with generation, but deployment may fail without a valid region.[/]")
        
        # Generate Bicep files
        generator = BicepGenerator(config, output_dir, debug=debug)
        bicep_path, params_path = generator.generate()
        
        # Display results
        console.print(f"[green]Bicep template generated at {bicep_path}[/]")
        console.print(f"[green]Parameters file generated at {params_path}[/]")
        
        # In debug mode, display the generated Bicep
        if debug:
            console.print("\n[bold blue]Generated Bicep Template:[/]")
            with open(bicep_path, 'r') as f:
                console.print(f.read())
            
            console.print("\n[bold blue]Generated Parameters File:[/]")
            with open(params_path, 'r') as f:
                console.print(f.read())
        
        return 0
    
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/]")
        return 1

@app.command("deploy")
def deploy(
    config: str = typer.Option("infra.yaml", "--config", "-c", help="Path to the infrastructure YAML file"),
    prune: bool = typer.Option(False, "--prune", help="Delete orphaned resources"),
    what_if: bool = typer.Option(False, "--what-if", help="Show what would be deployed without making changes"),
    debug: bool = typer.Option(False, "--debug", help="Print verbose debug information including all Azure CLI commands")
):
    """Deploy resources to Azure using generated Bicep files."""
    import subprocess
    import json
    from datetime import datetime
    
    console.print("[bold blue]Deploying resources...[/]")
    
    try:
        # Load manifest to get region
        manifest = ManifestParser.load(config)
        if not manifest.region:
            console.print("[bold red]No region specified in manifest. Run quota-check first.[/]")
            return 1
        
        # Generate Bicep files if they don't exist
        bicep_path = Path("main.bicep")
        params_path = Path("main.parameters.json")
        
        if not bicep_path.exists() or not params_path.exists():
            console.print("[yellow]Bicep files not found. Generating...[/]")
            generator = BicepGenerator(config)
            bicep_path, params_path = generator.generate()
        
        # Create unique deployment name
        deployment_name = f"{manifest.metadata.name}-{manifest.metadata.version}"
        if what_if:
            deployment_name += f"-whatif-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Build deployment command
        cmd = [
            "az", "deployment", "sub", 
            "what-if" if what_if else "create",
            "--location", manifest.region,
            "--name", deployment_name,
            "--template-file", str(bicep_path),
            "--parameters", f"@{str(params_path)}"
        ]
        
        # Add deletion mode if pruning
        if prune and not what_if:
            cmd.extend(["--mode", "Complete"])
        
        # Display command
        cmd_display = " ".join(cmd)
        console.print(f"Running: [bold]{cmd_display}[/]")
        
        # Capture command output for debugging
        if debug:
            console.print("\n[blue]Debug: Full Azure CLI command:[/]")
            console.print(f"[dim]{cmd_display}[/]")
            
            if what_if:
                # For what-if, add --no-pretty-print to get JSON output we can parse
                debug_cmd = cmd.copy()
                debug_cmd.append("--no-pretty-print")
                
                # Run command and capture output
                result = subprocess.run(debug_cmd, capture_output=True, text=True, check=True)
                what_if_output = json.loads(result.stdout)
                
                # Print detailed breakdown of changes
                console.print("\n[blue]Debug: Deployment changes:[/]")
                console.print(f"Changes: {len(what_if_output.get('changes', []))}")
                
                for change in what_if_output.get('changes', []):
                    console.print(f"- {change.get('resourceId')}: {change.get('changeType')}")
            else:
                # Execute deployment with output being displayed in real-time
                subprocess.run(cmd, check=True)
        else:
            # Execute deployment normally
            subprocess.run(cmd, check=True)
        
        if what_if:
            console.print("\n[green]What-if deployment analysis completed. No resources were modified.[/]")
        else:
            console.print("\n[green]Deployment completed successfully![/]")
            console.print("You can view deployment details in the Azure Portal.")
        
        return 0
        
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Deployment failed: {e}[/]")
        if debug:
            console.print("\n[blue]Debug: Command output:[/]")
            console.print(e.stdout if hasattr(e, 'stdout') else "No output captured")
            console.print("\n[blue]Debug: Error output:[/]")
            console.print(e.stderr if hasattr(e, 'stderr') else "No error output captured")
        return 1
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/]")
        return 1

@app.command("destroy")
def destroy(
    config: str = typer.Option("infra.yaml", "--config", "-c", help="Path to the infrastructure YAML file"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    debug: bool = typer.Option(False, "--debug", help="Print verbose debug information including all Azure CLI commands")
):
    """Delete all resources deployed from this manifest."""
    import subprocess
    
    console.print("[bold red]WARNING: This will delete all resources in the resource group![/]")
    
    try:
        # Load manifest
        manifest = ManifestParser.load(config)
        rg_name = manifest.resource_group.name
        
        # Confirm deletion
        if not force:
            confirmed = typer.confirm(f"Are you sure you want to delete resource group '{rg_name}'?")
            if not confirmed:
                console.print("Deletion cancelled")
                return 0
        
        # Delete resource group
        console.print(f"[yellow]Deleting resource group {rg_name}...[/]")
        cmd = ["az", "group", "delete", "--name", rg_name, "--yes"]
        
        # Display command in debug mode
        if debug:
            console.print("\n[blue]Debug: Full Azure CLI command:[/]")
            console.print(f"[dim]{' '.join(cmd)}[/]")
        
        # Execute command
        subprocess.run(cmd, check=True)
        
        console.print(f"[green]Resource group {rg_name} deleted successfully[/]")
        return 0
        
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Deletion failed: {e}[/]")
        if debug:
            console.print("\n[blue]Debug: Error output:[/]")
            console.print(e.stderr if hasattr(e, 'stderr') else "No error output captured")
        return 1
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/]")
        return 1

if __name__ == "__main__":
    app()