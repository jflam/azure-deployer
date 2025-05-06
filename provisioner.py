#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "pyyaml>=6",
#   "rich>=13",
#   "jinja2>=3",
# ]
# ///
"""
Quota-Aware Bicep Generator & Region-Selector – Provisioner CLI
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml
from jinja2 import Environment, BaseLoader
from rich.console import Console
from rich.table import Table

# Initialize Rich console
console = Console()

# Embedded Bicep Templates
TEMPLATES = {
    "main": """targetScope = 'subscription'

param location string = '{{ location }}'
param resourceGroupName string = '{{ resource_group.name }}'

// Resource Group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupName
  location: location
}

{% for service in services %}
module {{ service.name }} './modules/{{ service.type | replace('/', '_') }}.bicep' = {
  name: '{{ service.name }}-deployment'
  scope: rg
  params: {
    name: '{{ service.name }}'
    location: '{{ service.effective_region }}'
    {% if service.sku %}sku: '{{ service.sku }}'{% endif %}
    {% if service.capacity %}
    capacity: {{ service.capacity.required }}{% endif %}
    {% if service.properties %}
    properties: {{ service.properties | tojson }}
    {% endif %}
  }
}
{% endfor %}
""",

    "default": """param name string
param location string
param sku string = 'Standard'
param capacity int = 1
param properties object = {}

resource service '{{ type }}@2021-04-01' = {
  name: name
  location: location
  sku: {
    name: sku
    capacity: capacity
  }
}
""",

    "Microsoft.Web/staticSites": """param name string
param location string
param sku string = 'Free'
param properties object = {}

resource staticSite 'Microsoft.Web/staticSites@2021-02-01' = {
  name: name
  location: location
  sku: {
    name: sku
  }
  properties: properties
}
""",

    "Microsoft.DBforPostgreSQL/flexibleServers": """param name string
param location string
param sku string
param capacity int
param properties object

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2021-06-01' = {
  name: name
  location: location
  sku: {
    name: sku
    tier: properties.tier
  }
  properties: {
    version: properties.version
    storage: {
      storageSizeGB: properties.storageGB
    }
    backup: properties.backup
    network: properties.network
    administratorLogin: properties.administratorLogin
    administratorLoginPassword: properties.administratorLoginPassword
  }
}
"""
}

class RollbackType(Enum):
    NONE = "none"
    LAST_SUCCESSFUL = "lastSuccessful"
    NAMED = "named"  # For future use with named:<deploymentName>

class ManifestError(Exception):
    """Raised when the infrastructure manifest is invalid."""
    pass

class InfraManifest:
    """Loads and validates the infrastructure manifest."""
    
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {}
        self.load()
        self.validate()
        
    def load(self) -> None:
        """Load the YAML manifest file."""
        try:
            with open(self.path) as f:
                self.data = yaml.safe_load(f)
        except Exception as e:
            raise ManifestError(f"Failed to load manifest: {e}")
            
    def validate(self) -> None:
        """Validate the manifest structure and required fields."""
        required_top_level = ["metadata", "resourceGroup", "services"]
        
        # Check required top-level keys
        for key in required_top_level:
            if key not in self.data:
                raise ManifestError(f"Missing required top-level key: {key}")
                
        # Validate metadata section
        metadata = self.data["metadata"]
        if not isinstance(metadata, dict):
            raise ManifestError("metadata must be a dictionary")
        if "name" not in metadata:
            raise ManifestError("metadata.name is required")
            
        # Validate services section
        services = self.data["services"]
        if not isinstance(services, list):
            raise ManifestError("services must be a list")
        
        for idx, service in enumerate(services):
            if not isinstance(service, dict):
                raise ManifestError(f"Service at index {idx} must be a dictionary")
            if "name" not in service:
                raise ManifestError(f"Service at index {idx} missing required 'name' field")
            if "type" not in service:
                raise ManifestError(f"Service at index {idx} missing required 'type' field")

    def get_effective_region(self, service: Dict[str, Any]) -> str:
        """Get the effective region for a service, considering inheritance."""
        if "region" in service:
            return service["region"]
        return self.data.get("region", "")

    def expand_regions(self) -> None:
        """Expand effective_region for all services."""
        for service in self.data["services"]:
            service["effective_region"] = self.get_effective_region(service)

    def get_rollback_type(self) -> RollbackType:
        """Get the rollback type from deployment settings."""
        deployment = self.data.get("deployment", {})
        rollback = deployment.get("rollback", "lastSuccessful")
        
        if rollback == "none":
            return RollbackType.NONE
        elif rollback == "lastSuccessful":
            return RollbackType.LAST_SUCCESSFUL
        elif rollback.startswith("named:"):
            return RollbackType.NAMED
        else:
            return RollbackType.LAST_SUCCESSFUL  # Default

def run_command(cmd: List[str], check: bool = True, verbose: bool = False) -> Tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    if verbose:
        console.print(f"[cyan]Executing command:[/cyan] {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            check=check,
            text=True,
            capture_output=True
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        return e.returncode, e.stdout, e.stderr

def setup_azure_cli(verbose: bool = False) -> None:
    """Configure Azure CLI for dynamic extension installation and ensure quota extension is present."""
    console.print("[blue]Configuring Azure CLI for dynamic extension installation...[/blue]")
    returncode, stdout, stderr = run_command(
        ["az", "config", "set", "extension.use_dynamic_install=yes_without_prompt"],
        check=False,
        verbose=verbose
    )
    if returncode != 0:
        console.print(f"[yellow]Warning: Failed to set Azure CLI dynamic extension install config. Proceeding anyway. Stderr: {stderr}[/yellow]")
    else:
        console.print("[green]Azure CLI configured for dynamic extension installation.[/green]")

    console.print("[blue]Ensuring 'quota' Azure CLI extension is installed...[/blue]")
    returncode, stdout, stderr = run_command(
        ["az", "extension", "add", "--name", "quota", "--upgrade"],
        check=False,
        verbose=verbose
    )
    if returncode != 0:
        if stderr and "already installed" in stderr.lower():
            console.print("[green]'quota' extension is already installed.[/green]")
        else:
            console.print(f"[yellow]Warning: Failed to install/upgrade 'quota' CLI extension. Quota checks might fail.[/yellow]")
            if stderr:
                console.print(f"[yellow]Stderr: {stderr.strip()}[/yellow]")
            if stdout:
                console.print(f"[yellow]Stdout: {stdout.strip()}[/yellow]")
    else:
        console.print("[green]'quota' extension installed/upgraded successfully.[/green]")

class QuotaResolver:
    """Handles quota checking and region selection."""
    
    def __init__(self, manifest: InfraManifest, verbose: bool = False):
        self.manifest = manifest
        self.verbose = verbose
        self.analysis: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regions": defaultdict(dict),
            "services": [],
            "viable_regions": set(),
            "selected_region": None
        }
        self._subscription_id: Optional[str] = None  # Cache for subscription ID

    def check(self) -> Dict[str, Any]:
        """
        Performs a full quota check for all services against candidate regions
        and determines viable regions for deployment.
        """
        console.print("\n[blue]Starting quota analysis...[/blue]")
        self.manifest.expand_regions()  # Ensure effective_region is set for all services

        all_candidate_regions = self.get_candidate_regions()
        if not all_candidate_regions:
            console.print("[red]No candidate regions found to check.[/red]")
            self.analysis["viable_regions"] = set()
            return self.analysis

        # Store services in analysis for reference
        self.analysis["services"] = [
            {
                "name": s["name"],
                "type": s["type"],
                "capacity": s.get("capacity"),
                "effective_region": s["effective_region"]
            } for s in self.manifest.data["services"]
        ]

        # Regions where all services (that need checking in that region) pass
        potentially_viable_regions = set(all_candidate_regions)

        for service in self.manifest.data["services"]:
            if service.get("skipQuotaCheck", False) or not service.get("capacity"):
                console.print(f"[grey]Skipping quota analysis for {service['name']} (marked as skip or no capacity).[/grey]")
                continue

            service_effective_region = service["effective_region"]
            
            # Determine regions to check for this service
            regions_to_check_for_service: Set[str]
            if service_effective_region:  # Service has a specific region defined
                if service_effective_region not in all_candidate_regions:
                    console.print(f"[yellow]Warning: Service '{service['name']}' effective region '{service_effective_region}' is not in the list of allowed/available regions.[/yellow]")
                    regions_to_check_for_service = {service_effective_region} & all_candidate_regions
                    if not regions_to_check_for_service:
                        console.print(f"[red]Error: Service '{service['name']}' is fixed to region '{service_effective_region}', which is not in the available/allowed candidate regions.[/red]")
                else:
                    regions_to_check_for_service = {service_effective_region}
            else:  # Service inherits global region, check against all candidates
                regions_to_check_for_service = set(all_candidate_regions)

            for region_candidate in list(potentially_viable_regions):  # Iterate over a copy as we might modify the set
                # If service is fixed to a region, and it's not this one, it doesn't affect this region_candidate's viability
                if service_effective_region and service_effective_region != region_candidate:
                    continue

                # Check quota for the service in region_candidate
                if not self.check_quota(service, region_candidate):
                    # If this service fails in this region_candidate, then this region_candidate is not viable
                    if region_candidate in potentially_viable_regions:
                        potentially_viable_regions.remove(region_candidate)
                        console.print(f"[yellow]Region {region_candidate} is no longer viable due to {service['name']}.[/yellow]")

        self.analysis["viable_regions"] = list(potentially_viable_regions)  # Convert set to list for JSON
        if self.analysis["viable_regions"]:
            console.print(f"\n[green]Viable regions found: {', '.join(self.analysis['viable_regions'])}[/green]")
        else:
            console.print("\n[red]No viable regions found that satisfy all quota requirements.[/red]")

        # Save analysis to file
        analysis_file = "region-analysis.json"
        try:
            with open(analysis_file, "w") as f:
                json.dump(self.analysis, f, indent=2)
            console.print(f"[blue]Quota analysis saved to {analysis_file}[/blue]")
        except IOError as e:
            console.print(f"[red]Error saving quota analysis to {analysis_file}: {e}[/red]")
            
        return self.analysis

    def select_region(self, auto_select: bool) -> Optional[str]:
        """
        Selects a region from the list of viable regions.
        Prompts user or auto-selects based on the flag.
        Updates self.analysis["selected_region"].
        """
        viable_regions = self.analysis.get("viable_regions", [])
        if not isinstance(viable_regions, list):  # Ensure it's a list if loaded from old file
            viable_regions = list(viable_regions)

        if not viable_regions:
            console.print("[yellow]No viable regions to select from.[/yellow]")
            self.analysis["selected_region"] = None
            return None

        if auto_select:
            selected_region = viable_regions[0]
            console.print(f"[green]Auto-selected region: {selected_region}[/green]")
            self.analysis["selected_region"] = selected_region
            return selected_region
        else:
            console.print("\n[blue]Please select a region from the viable options:[/blue]")
            for i, region_name in enumerate(viable_regions):
                console.print(f"{i+1}. {region_name}")
            
            while True:
                try:
                    choice_str = input(f"Enter number (1-{len(viable_regions)}): ")
                    choice = int(choice_str) - 1
                    if 0 <= choice < len(viable_regions):
                        selected_region = viable_regions[choice]
                        console.print(f"[green]Selected region: {selected_region}[/green]")
                        self.analysis["selected_region"] = selected_region
                        return selected_region
                    else:
                        console.print("[red]Invalid choice. Please try again.[/red]")
                except ValueError:
                    console.print("[red]Invalid input. Please enter a number.[/red]")
                except KeyboardInterrupt:
                    console.print("\n[yellow]Region selection cancelled.[/yellow]")
                    self.analysis["selected_region"] = None
                    return None

    def _get_subscription_id(self) -> str:
        """Get the current Azure subscription ID."""
        if self._subscription_id is None:
            console.print("[blue]Fetching Azure subscription ID...[/blue]")
            returncode, stdout, stderr = run_command(
                ["az", "account", "show", "--query", "id", "-o", "tsv"],
                check=True,
                verbose=self.verbose
            )
            if returncode != 0 or not stdout.strip():
                console.print(f"[red]Error: Failed to fetch Azure subscription ID. Stderr: {stderr}[/red]")
                raise RuntimeError("Failed to fetch Azure subscription ID")
            self._subscription_id = stdout.strip()
            console.print(f"[green]Using subscription ID: {self._subscription_id}[/green]")
        return self._subscription_id
        
    def check_quota(self, service: Dict[str, Any], region: str) -> bool:
        """Check quota for a single service in a region."""
        if service.get("skipQuotaCheck", False) or not service.get("capacity"):
            console.print(f"[grey]Skipping quota check for {service['name']} (no capacity requirements)[/grey]")
            return True
            
        service_type_full = service["type"]  # e.g., "Microsoft.DBforPostgreSQL/flexibleServers"
        capacity = service["capacity"]
        required = capacity.get("required", 0)
        unit = capacity.get("unit", "")
        
        if not required or not unit:
            console.print(f"[grey]Skipping quota check for {service['name']} (no required capacity or unit)[/grey]")
            return True
            
        console.print(f"[blue]Checking quota for {service['name']} ({service_type_full}) in {region}...[/blue]")
        
        try:
            subscription_id = self._get_subscription_id()
        except RuntimeError as e:
            console.print(f"[red]Error: {e}. Skipping quota check for {service['name']}.[/red]")
            return False
            
        provider_parts = service_type_full.split('/', 1)
        if len(provider_parts) != 2:
            console.print(f"[yellow]Warning: Service type '{service_type_full}' for '{service['name']}' does not follow 'Namespace/ResourceType' format. Skipping quota check.[/yellow]")
            return False
            
        namespace = provider_parts[0]  # e.g., "Microsoft.DBforPostgreSQL"
        
        scope = f"/subscriptions/{subscription_id}/providers/{namespace}/locations/{region}"
        
        cmd = [
            "az", "quota", "list",
            "--scope", scope,
            "-o", "json"
        ]
        
        returncode, stdout, stderr = run_command(cmd, check=False, verbose=self.verbose)
        if returncode != 0:
            console.print(f"[yellow]Warning: Failed to check quota for {service_type_full} in {region}. RC: {returncode}[/yellow]")
            if stderr:
                console.print(f"[yellow]Stderr from 'az quota list': {stderr.strip()}[/yellow]")
            if stdout:
                console.print(f"[yellow]Stdout from 'az quota list': {stdout.strip()}[/yellow]")
            # Record failure in analysis
            self.analysis["regions"][region][f"{service_type_full}_{unit}"] = {
                "error": f"Failed to retrieve quota. RC: {returncode}",
                "stderr": stderr.strip() if stderr else None,
                "stdout": stdout.strip() if stdout else None
            }
            return False
            
        try:
            quotas = json.loads(stdout)
            for quota in quotas:
                if quota.get("name", {}).get("value", "").lower() == unit.lower():
                    limit = quota.get("limit", 0)
                    usage = quota.get("currentValue", 0)
                    available = limit - usage
                    
                    self.analysis["regions"][region][f"{service_type_full}_{unit}"] = {
                        "limit": limit,
                        "usage": usage,
                        "available": available,
                        "required": required,
                        "sufficient": available >= required
                    }
                    
                    if available >= required:
                        console.print(f"[green]✓ {service['name']} has sufficient quota in {region} ({available} {unit} available, {required} required)[/green]")
                    else:
                        console.print(f"[red]✗ {service['name']} has insufficient quota in {region} ({available} {unit} available, {required} required)[/red]")
                    
                    return available >= required
        except json.JSONDecodeError:
            console.print(f"[yellow]Warning: Invalid JSON response for {service_type_full} quota check[/yellow]")
            return False
            
        return False
        
    def get_candidate_regions(self) -> Set[str]:
        """Get list of candidate regions to check."""
        console.print("\n[blue]Fetching list of Azure regions...[/blue]")
        
        allowed_regions = set(self.manifest.data.get("allowedRegions", []))
        if allowed_regions:
            console.print(f"[blue]Filtering regions to allowed list: {', '.join(allowed_regions)}[/blue]")
        
        # Get list of all regions from Azure
        cmd = ["az", "account", "list-locations", "--query", "[].name", "-o", "json"]
        returncode, stdout, stderr = run_command(cmd, verbose=self.verbose)
        
        if returncode != 0:
            raise ManifestError("Failed to fetch Azure regions")
            
        all_regions = set(json.loads(stdout))
        console.print(f"[green]Found {len(all_regions)} available Azure regions[/green]")
        
        # If allowedRegions is specified, intersect with all regions
        result = allowed_regions & all_regions if allowed_regions else all_regions
        if allowed_regions:
            console.print(f"[blue]Filtered to {len(result)} allowed regions[/blue]")
        
        return result

class BicepGenerator:
    """Generates Bicep templates from the manifest."""
    
    def __init__(self, manifest: InfraManifest, verbose: bool = False):
        self.manifest = manifest
        self.verbose = verbose
        self.env = Environment(loader=BaseLoader())
        self.env.filters["tojson"] = json.dumps
        
    def get_template(self, service_type: str) -> str:
        """Get the appropriate template for a service type."""
        # Replace / with _ for template lookup
        template_key = service_type.replace("/", "_")
        return TEMPLATES.get(template_key, TEMPLATES["default"])
        
    def detect_orphans(self) -> List[Dict[str, str]]:
        """Detect resources in Azure that aren't in the manifest."""
        rg_name = self.manifest.data["resourceGroup"]["name"]
        
        cmd = [
            "az", "resource", "list",
            "--resource-group", rg_name,
            "--query", "[].{id:id, type:type}",
            "-o", "json"
        ]
        
        returncode, stdout, stderr = run_command(cmd, verbose=self.verbose)
        if returncode != 0:
            console.print("[yellow]Warning: Failed to check for orphaned resources[/yellow]")
            return []
            
        try:
            existing = json.loads(stdout)
            planned = {s["type"] for s in self.manifest.data["services"]}
            
            orphans = []
            for resource in existing:
                if resource["type"] not in planned:
                    orphans.append(resource)
            
            return orphans
            
        except json.JSONDecodeError:
            console.print("[yellow]Warning: Invalid JSON response when checking orphans[/yellow]")
            return []

    def generate(self) -> None:
        """Generate Bicep templates and parameter files."""
        self.manifest.expand_regions()
        
        # Create modules directory
        os.makedirs("modules", exist_ok=True)
        
        # Generate service-specific module files
        for service in self.manifest.data["services"]:
            template = self.get_template(service["type"])
            module_name = service["type"].replace("/", "_")
            
            with open(f"modules/{module_name}.bicep", "w") as f:
                f.write(template)
                
        # Generate main.bicep
        template = self.env.from_string(TEMPLATES["main"])
        main_content = template.render(
            location=self.manifest.data.get("region", ""),
            resource_group=self.manifest.data["resourceGroup"],
            services=self.manifest.data["services"]
        )
        
        with open("main.bicep", "w") as f:
            f.write(main_content)
            
        # Generate parameters file
        parameters = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {}
        }
        
        with open("main.parameters.json", "w") as f:
            json.dump(parameters, f, indent=2)
            
        # Check for orphaned resources
        orphans = self.detect_orphans()
        if orphans:
            console.print("\n[yellow]Warning: Detected orphaned resources:[/yellow]")
            table = Table()
            table.add_column("Resource Type")
            table.add_column("Resource ID")
            
            for orphan in orphans:
                table.add_row(orphan["type"], orphan["id"])
                
            console.print(table)
            console.print("[yellow]Use --prune with deploy to remove these resources.[/yellow]")

class ARMProvisioner:
    """Handles ARM deployments with rollback support."""
    
    def provision(self, prune: bool = False) -> bool:
        """Provision the infrastructure with optional pruning."""
        # First, run quota check
        resolver = QuotaResolver(self.manifest, verbose=self.verbose)
        analysis = resolver.check()

        selected_manifest_region = self.manifest.data.get("region", "")

        if not selected_manifest_region:  # If no global region is pre-defined in the manifest
            if not analysis.get("viable_regions"):
                console.print("[red]Error: Quota check found no viable regions for deployment.[/red]")
                return False
            
            # Auto-select the first viable region for provisioning
            selected_region_for_deployment = resolver.select_region(auto_select=True)
            if not selected_region_for_deployment:
                console.print("[red]Error: Failed to auto-select a region for deployment.[/red]")
                return False
            
            # Update the manifest in memory for this provisioning run
            self.manifest.data["region"] = selected_region_for_deployment
            console.print(f"[blue]Auto-selected region for this deployment: {selected_region_for_deployment}[/blue]")
        else:
            # A global region is already set in the manifest
            console.print(f"[blue]Using pre-configured global region from manifest: {selected_manifest_region}[/blue]")
            if selected_manifest_region not in analysis.get("viable_regions", []):
                console.print(f"[red]Error: The pre-configured global region '{selected_manifest_region}' is not viable based on current quota analysis.[/red]")
                console.print(f"[red]Viable global regions are: {', '.join(analysis.get('viable_regions', []))}. Please run 'quota-check' or update manifest.[/red]")
                return False
            resolver.analysis["selected_region"] = selected_manifest_region

        # Save the analysis JSON
        analysis_file = "region-analysis-provision.json"
        try:
            with open(analysis_file, "w") as f:
                json.dump(resolver.analysis, f, indent=2)
            console.print(f"[blue]Quota analysis for provision step saved to {analysis_file}[/blue]")
        except IOError as e:
            console.print(f"[yellow]Warning: Could not save provision step analysis to {analysis_file}: {e}[/yellow]")

        # Generate templates
        generator = BicepGenerator(self.manifest, verbose=self.verbose)
        generator.generate()
        
        # Handle orphaned resources if pruning
        if prune:
            orphans = generator.detect_orphans()
            if orphans:
                console.print("\n[yellow]Pruning orphaned resources...[/yellow]")
                for orphan in orphans:
                    cmd = [
                        "az", "resource", "delete",
                        "--ids", orphan["id"],
                        "--yes"
                    ]
                    returncode, _, _ = run_command(cmd, verbose=self.verbose)
                    if returncode != 0:
                        console.print(f"[red]Failed to delete orphaned resource: {orphan['id']}[/red]")
                        
        # Prepare deployment command
        deployment_name = f"{self.manifest.data['metadata']['name']}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        region = self.manifest.data.get("region", "")
        
        cmd = [
            "az", "deployment", "sub", "create",
            "--location", region,
            "--name", deployment_name,
            "--template-file", "main.bicep",
            "--parameters", "@main.parameters.json"
        ]
        
        # Add rollback flag if enabled
        if self.manifest.get_rollback_type() != RollbackType.NONE:
            cmd.append("--rollback-on-error")
            
        # Execute deployment
        console.print(f"\n[blue]Starting deployment: {deployment_name}[/blue]")
        returncode, stdout, stderr = run_command(cmd, verbose=self.verbose)
        
        if returncode != 0:
            console.print("[red]Deployment failed[/red]")
            console.print(f"[red]Error: {stderr}[/red]")
            return False
            
        try:
            result = json.loads(stdout)
            if result.get("properties", {}).get("provisioningState") == "Succeeded":
                console.print("[green]Deployment succeeded[/green]")
                return True
            else:
                console.print("[red]Deployment failed[/red]")
                return False
        except json.JSONDecodeError:
            console.print("[red]Failed to parse deployment result[/red]")
            return False

class Destroyer:
    """Handles infrastructure teardown in the correct order."""
    
    def __init__(self, manifest: InfraManifest, verbose: bool = False):
        self.manifest = manifest
        self.verbose = verbose
        
    def confirm_destruction(self, skip_confirmation: bool = False) -> bool:
        """Get user confirmation for destruction."""
        if skip_confirmation:
            return True
            
        rg_name = self.manifest.data["resourceGroup"]["name"]
        console.print(f"\n[red]WARNING: This will destroy all resources in resource group '{rg_name}'![/red]")
        console.print("[red]This action cannot be undone.[/red]")
        
        try:
            response = input("\nType 'yes' to confirm: ")
            return response.lower() == 'yes'
        except KeyboardInterrupt:
            return False
            
    def destroy(self, skip_confirmation: bool = False) -> bool:
        """Destroy all resources in the correct order."""
        if not self.confirm_destruction(skip_confirmation):
            console.print("[yellow]Destruction cancelled.[/yellow]")
            return False
            
        rg_name = self.manifest.data["resourceGroup"]["name"]
        
        # Get list of resources to destroy
        cmd = [
            "az", "resource", "list",
            "--resource-group", rg_name,
            "--query", "[].{id:id, type:type, name:name}",
            "-o", "json"
        ]
        
        returncode, stdout, stderr = run_command(cmd, verbose=self.verbose)
        if returncode != 0:
            console.print("[red]Failed to list resources[/red]")
            return False
            
        try:
            resources = json.loads(stdout)
        except json.JSONDecodeError:
            console.print("[red]Failed to parse resource list[/red]")
            return False
            
        # Define deletion order by resource type
        deletion_order = [
            # 1. Data tier
            "Microsoft.DBforPostgreSQL/flexibleServers",
            # 2. Compute / Registry
            "Microsoft.App/containerApps",
            "Microsoft.App/managedEnvironments",
            "Microsoft.ContainerRegistry/registries",
            # 3. Identity / Secrets
            "Microsoft.KeyVault/vaults",
            # 4. Monitoring
            "Microsoft.OperationalInsights/workspaces",
            # 5. Static Web
            "Microsoft.Web/staticSites",
            # Everything else
            "*"
        ]
        
        # Group resources by type
        resources_by_type = defaultdict(list)
        for resource in resources:
            resources_by_type[resource["type"]].append(resource)
            
        # Delete resources in order
        for resource_type in deletion_order:
            if resource_type == "*":
                # Delete remaining resources
                for type_name, resources in resources_by_type.items():
                    if resources:  # If any resources of this type haven't been deleted
                        self._delete_resources(resources)
            else:
                if resource_type in resources_by_type:
                    self._delete_resources(resources_by_type[resource_type])
                    resources_by_type[resource_type] = []  # Mark as deleted
                    
        # Finally, delete the resource group
        console.print(f"\n[blue]Deleting resource group '{rg_name}'...[/blue]")
        cmd = ["az", "group", "delete", "--name", rg_name, "--yes"]
        returncode, _, stderr = run_command(cmd, verbose=self.verbose)
        
        if returncode != 0:
            console.print(f"[red]Failed to delete resource group: {stderr}[/red]")
            console.print("[yellow]Note: Resource group deletion might be blocked by Key Vault purge protection.[/yellow]")
            return False
            
        console.print("[green]Infrastructure destroyed successfully[/green]")
        return True
        
    def _delete_resources(self, resources: List[Dict[str, str]]) -> None:
        """Delete a list of resources of the same type."""
        for resource in resources:
            console.print(f"[blue]Deleting {resource['type']} '{resource['name']}'...[/blue]")
            cmd = ["az", "resource", "delete", "--ids", resource["id"], "--yes"]
            returncode, _, stderr = run_command(cmd, verbose=self.verbose)
            
            if returncode != 0:
                console.print(f"[yellow]Warning: Failed to delete {resource['name']}: {stderr}[/yellow]")

def main() -> int:
    parser = argparse.ArgumentParser(description="Quota-aware Bicep generator and region selector")
    parser.add_argument("-c", "--config", default="infra.yaml", help="Path to infra.yaml (default: ./infra.yaml)")
    parser.add_argument("--auto-select", action="store_true", help="Auto-select first viable region")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # quota-check command
    quota_parser = subparsers.add_parser("quota-check", help="Validate quotas & optionally auto-select region")
    
    # generate command
    generate_parser = subparsers.add_parser("generate", help="Generate Bicep & parameter files")
    
    # provision command
    provision_parser = subparsers.add_parser(
        "provision", help="Provision the infrastructure")
    provision_parser.add_argument("--prune", action="store_true",
                                  help="Delete orphaned resources")
    
    # destroy command
    destroy_parser = subparsers.add_parser("destroy", help="Tear down the infrastructure")
    destroy_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    
    args = parser.parse_args()
    
    try:
        # Set up Azure CLI for dynamic extension installation
        setup_azure_cli(verbose=args.verbose)
        
        manifest = InfraManifest(args.config)
        
        if args.command == "quota-check":
            resolver = QuotaResolver(manifest, verbose=args.verbose)
            # The check method now performs the full analysis and saves the report
            analysis_result = resolver.check() 
            
            if not analysis_result.get("viable_regions"):
                console.print("[red]Quota check failed: No viable regions found.[/red]")
                return 2  # Exit code 2 for no viable regions
                
            # Proceed to select region
            selected_region = resolver.select_region(args.auto_select)
            if not selected_region:
                console.print("[yellow]Region selection aborted or failed.[/yellow]")
                return 1  # Exit code 1 for other errors
                
            # Update manifest with selected region
            manifest.data["region"] = selected_region
            
            try:
                with open(args.config, "w") as f:
                    yaml.dump(manifest.data, f)
                console.print(f"[green]Updated {args.config} with selected global region: {selected_region}[/green]")
            except IOError as e:
                console.print(f"[red]Error updating manifest file {args.config}: {e}[/red]")
                return 1

            # Save final analysis with selection
            analysis_file = "region-analysis.json"
            try:
                with open(analysis_file, "w") as f:
                    json.dump(resolver.analysis, f, indent=2)
                console.print(f"[blue]Final quota analysis with selection saved to {analysis_file}[/blue]")
            except IOError as e:
                console.print(f"[red]Error saving final quota analysis to {analysis_file}: {e}[/red]")
            
            return 0

        elif args.command == "generate":
            generator = BicepGenerator(manifest, verbose=args.verbose)
            generator.generate()
            console.print("[green]Generated Bicep templates and parameter files[/green]")
            return 0
            
        elif args.command == "provision":
            provisioner = ARMProvisioner(manifest, verbose=args.verbose)
            success = provisioner.provision(args.prune)
            return 0 if success else 1
            
        elif args.command == "destroy":
            destroyer = Destroyer(manifest, verbose=args.verbose)
            success = destroyer.destroy(args.yes)
            return 0 if success else 1
            
    except ManifestError as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        return 1
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {str(e)}")
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())