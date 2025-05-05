#!/usr/bin/env python3
"""
Quota-Aware Bicep Generator & Region-Selector

Requirements for uv:
pyyaml>=6
rich>=13
jinja2>=3
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
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
    {% if service.capacity %}capacity: {{ service.capacity.required }}{% endif %}
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
  properties: properties
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

def run_command(cmd: List[str], check: bool = True) -> Tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
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

class QuotaResolver:
    """Handles quota checking and region selection."""
    
    def __init__(self, manifest: InfraManifest):
        self.manifest = manifest
        self.analysis: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "regions": defaultdict(dict),
            "services": [],
            "viable_regions": set(),
            "selected_region": None
        }
        
    def check_quota(self, service: Dict[str, Any], region: str) -> bool:
        """Check quota for a single service in a region."""
        if service.get("skipQuotaCheck", False) or not service.get("capacity"):
            return True
            
        provider = service["type"]
        capacity = service["capacity"]
        required = capacity.get("required", 0)
        unit = capacity.get("unit", "")
        
        if not required or not unit:
            return True
            
        cmd = [
            "az", "quota", "list",
            "--location", region,
            "--resource-type", provider,
            "-o", "json"
        ]
        
        returncode, stdout, stderr = run_command(cmd)
        if returncode != 0:
            console.print(f"[yellow]Warning: Failed to check quota for {provider} in {region}[/yellow]")
            return False
            
        try:
            quotas = json.loads(stdout)
            for quota in quotas:
                if quota.get("name", {}).get("value", "").lower() == unit.lower():
                    limit = quota.get("limit", 0)
                    usage = quota.get("currentValue", 0)
                    available = limit - usage
                    
                    self.analysis["regions"][region][f"{provider}_{unit}"] = {
                        "limit": limit,
                        "usage": usage,
                        "available": available,
                        "required": required,
                        "sufficient": available >= required
                    }
                    
                    return available >= required
        except json.JSONDecodeError:
            console.print(f"[yellow]Warning: Invalid JSON response for {provider} quota check[/yellow]")
            return False
            
        return False
        
    def get_candidate_regions(self) -> Set[str]:
        """Get list of candidate regions to check."""
        allowed_regions = set(self.manifest.data.get("allowedRegions", []))
        
        # Get list of all regions from Azure
        cmd = ["az", "account", "list-locations", "--query", "[].name", "-o", "json"]
        returncode, stdout, stderr = run_command(cmd)
        
        if returncode != 0:
            raise ManifestError("Failed to fetch Azure regions")
            
        all_regions = set(json.loads(stdout))
        
        # If allowedRegions is specified, intersect with all regions
        return allowed_regions & all_regions if allowed_regions else all_regions
        
    def check(self) -> Dict[str, Any]:
        """Run the quota check algorithm and return analysis."""
        self.manifest.expand_regions()
        
        # Collect services that need quota checking
        services_to_check = []
        for service in self.manifest.data["services"]:
            if not service.get("skipQuotaCheck", False) and service.get("capacity"):
                services_to_check.append(service)
                self.analysis["services"].append({
                    "name": service["name"],
                    "type": service["type"],
                    "capacity": service["capacity"],
                    "effective_region": service["effective_region"]
                })
        
        # If no services need quota checking, return early
        if not services_to_check:
            self.analysis["viable_regions"] = list(self.get_candidate_regions())
            return self.analysis
            
        # Check quotas for each service in candidate regions
        candidate_regions = self.get_candidate_regions()
        viable_regions = set()
        
        for region in candidate_regions:
            region_viable = True
            for service in services_to_check:
                if not self.check_quota(service, region):
                    region_viable = False
                    break
            
            if region_viable:
                viable_regions.add(region)
                
        self.analysis["viable_regions"] = list(viable_regions)
        
        # Write analysis to file
        with open("region-analysis.json", "w") as f:
            json.dump(self.analysis, f, indent=2)
            
        # Print summary table
        table = Table(title="Region Analysis")
        table.add_column("Region")
        table.add_column("Status")
        table.add_column("Details")
        
        for region in candidate_regions:
            status = "[green]VIABLE[/green]" if region in viable_regions else "[red]BLOCKED[/red]"
            details = []
            for key, data in self.analysis["regions"][region].items():
                if not data["sufficient"]:
                    details.append(f"{key}: {data['available']}/{data['required']}")
            
            table.add_row(
                region,
                status,
                ", ".join(details) if details else "All quotas sufficient"
            )
            
        console.print(table)
        
        if not viable_regions:
            console.print("[red]Error: No regions satisfy quota requirements[/red]")
            return self.analysis
            
        return self.analysis
        
    def select_region(self, auto_select: bool = False) -> Optional[str]:
        """Select a region from viable options."""
        viable_regions = self.analysis["viable_regions"]
        
        if not viable_regions:
            return None
            
        if auto_select:
            selected = viable_regions[0]
            console.print(f"[green]Auto-selected region: {selected}[/green]")
            self.analysis["selected_region"] = selected
            return selected
            
        # Interactive selection
        console.print("\nViable regions:")
        for idx, region in enumerate(viable_regions, 1):
            console.print(f"{idx}. {region}")
            
        while True:
            try:
                choice = input("\nSelect region number (or 'q' to quit): ")
                if choice.lower() == 'q':
                    return None
                    
                idx = int(choice) - 1
                if 0 <= idx < len(viable_regions):
                    selected = viable_regions[idx]
                    self.analysis["selected_region"] = selected
                    return selected
                    
            except ValueError:
                pass
                
            console.print("[red]Invalid selection. Try again.[/red]")

class BicepGenerator:
    """Generates Bicep templates from the manifest."""
    
    def __init__(self, manifest: InfraManifest):
        self.manifest = manifest
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
        
        returncode, stdout, stderr = run_command(cmd)
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

class ARMDeployer:
    """Handles ARM deployments with rollback support."""
    
    def __init__(self, manifest: InfraManifest):
        self.manifest = manifest
        
    def deploy(self, prune: bool = False) -> bool:
        """Deploy the infrastructure with optional pruning."""
        # First, run quota check
        resolver = QuotaResolver(self.manifest)
        analysis = resolver.check()
        
        if not analysis["viable_regions"]:
            console.print("[red]Error: No viable regions for deployment[/red]")
            return False
            
        # Generate templates
        generator = BicepGenerator(self.manifest)
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
                    returncode, _, _ = run_command(cmd)
                    if returncode != 0:
                        console.print(f"[red]Failed to delete orphaned resource: {orphan['id']}[/red]")
                        
        # Prepare deployment command
        deployment_name = f"{self.manifest.data['metadata']['name']}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
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
        returncode, stdout, stderr = run_command(cmd)
        
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
    
    def __init__(self, manifest: InfraManifest):
        self.manifest = manifest
        
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
        
        returncode, stdout, stderr = run_command(cmd)
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
        returncode, _, stderr = run_command(cmd)
        
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
            returncode, _, stderr = run_command(cmd)
            
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
    
    # deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy the infrastructure")
    deploy_parser.add_argument("--prune", action="store_true", help="Delete orphaned resources")
    
    # destroy command
    destroy_parser = subparsers.add_parser("destroy", help="Tear down the infrastructure")
    destroy_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    
    args = parser.parse_args()
    
    try:
        manifest = InfraManifest(args.config)
        
        if args.command == "quota-check":
            resolver = QuotaResolver(manifest)
            analysis = resolver.check()
            
            if not analysis["viable_regions"]:
                return 2
                
            selected_region = resolver.select_region(args.auto_select)
            if not selected_region:
                return 1
                
            # Update manifest with selected region
            manifest.data["region"] = selected_region
            with open(args.config, "w") as f:
                yaml.dump(manifest.data, f)
                
            console.print(f"[green]Updated {args.config} with selected region: {selected_region}[/green]")
            return 0
            
        elif args.command == "generate":
            generator = BicepGenerator(manifest)
            generator.generate()
            console.print("[green]Generated Bicep templates and parameter files[/green]")
            return 0
            
        elif args.command == "deploy":
            deployer = ARMDeployer(manifest)
            success = deployer.deploy(args.prune)
            return 0 if success else 1
            
        elif args.command == "destroy":
            destroyer = Destroyer(manifest)
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