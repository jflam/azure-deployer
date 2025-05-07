# Quota-Aware Bicep Generator & Region-Selector — Implementation Plan

## Executive Summary

This implementation plan details how to create a Python CLI tool that:

1. **Checks quota availability** across Azure regions for a set of resources defined in a YAML manifest
2. **Presents users with viable regions** that have sufficient quota for all resources
3. **Generates Bicep files** that can be deployed to the selected region
4. **Provides enhanced debugging capabilities** with the `--debug` flag

The tool will have the following key features:

- **Clear, detailed output** showing available regions with quota analysis
- **Informative error messages** with links to request quota increases if needed
- **Debug mode** that shows all Azure CLI commands and Bicep output for diagnostics
- **Quota-aware region selection** to avoid deployment failures

All of this functionality will be implemented in Python with proper error handling, output formatting, and user feedback.

## 1. Project Structure

```
/
├── pyproject.toml          # Project metadata and dependencies
├── uv.lock                 # UV lock file for reproducible builds
├── main.py                 # CLI entrypoint
├── provisioner/            # Main package
│   ├── __init__.py
│   ├── quota/              # Quota checking components
│   │   ├── __init__.py
│   │   ├── resolver.py     # SDK auto-resolver
│   │   ├── checker.py      # Quota check implementation
│   │   ├── providers.py    # Provider-specific quota adapters
│   │   ├── models.py       # Data models for quota information
│   │   └── matrix.py       # Quota matrix generator
│   ├── bicep/              # Bicep generation components
│   │   ├── __init__.py
│   │   ├── generator.py    # Main generator orchestration
│   │   ├── builders/       # Resource type-specific builders
│   │   │   ├── __init__.py
│   │   │   ├── static_site.py
│   │   │   ├── postgres.py
│   │   │   ├── container_env.py
│   │   │   └── log_analytics.py
│   │   ├── templates/      # Bicep templates (optional Jinja2)
│   │   │   ├── base.bicep
│   │   │   └── parameters.json
│   │   └── models.py       # Shared data models
│   ├── manifest/           # YAML manifest handling
│   │   ├── __init__.py
│   │   ├── parser.py       # Manifest parser and validator
│   │   ├── schema.py       # Schema definitions (Pydantic models)
│   │   └── updater.py      # Handle in-place YAML updates
│   └── common/             # Shared utilities
│       ├── __init__.py
│       ├── azure_auth.py   # Azure authentication helpers 
│       ├── exceptions.py   # Custom exceptions
│       └── logging.py      # Logging configuration
├── scripts/                # Utility scripts
│   ├── resolve_sdks.py     # SDK dependency resolution helper
│   └── quota_check.py      # Standalone quota checker script
└── tests/                  # Unit and integration tests
    ├── __init__.py
    ├── test_quota/
    ├── test_bicep/
    └── test_manifest/
```

## 2. Development Environment Setup

### 2.1 Prerequisites

- Python 3.11+
- UV package manager
- Azure CLI 2.54+ (for local testing)

### 2.2 Initial Project Setup

```bash
# Create project directory
mkdir -p azure-provisioner/provisioner/{quota,bicep,manifest,common}
mkdir -p azure-provisioner/provisioner/bicep/{builders,templates}
mkdir -p azure-provisioner/scripts
mkdir -p azure-provisioner/tests/{test_quota,test_bicep,test_manifest}

# Initialize pyproject.toml
cat > azure-provisioner/pyproject.toml << EOL
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "azure-provisioner"
version = "0.1.0"
description = "Quota-aware Bicep generator and region selector for Azure deployments"
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}
authors = [
    {name = "Azure Provisioner Team", email = "example@example.com"},
]
dependencies = [
    "pyyaml>=6.0",
    "pydantic>=2.0.0",
    "jinja2>=3.1.2",
    "azure-identity>=1.13.0",
    "azure-mgmt-quota>=1.0.0",
    "rich>=13.4.2",
    "typer>=0.9.0",
    "tenacity>=8.2.2",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.3.1",
    "black>=23.3.0",
    "isort>=5.12.0",
    "mypy>=1.3.0",
    "pytest-cov>=4.1.0",
]

[project.scripts]
provisioner = "main:app"

[tool.black]
line-length = 88
target-version = ["py311"]

[tool.isort]
profile = "black"
EOL

# Install project with dev dependencies using UV
cd azure-provisioner
uv pip install -e ".[dev]"
```

## 3. Implementation Plan

### 3.1 Core Components Implementation

#### 3.1.1 YAML Manifest Parser (provisioner/manifest/)

**Purpose**: Parse and validate the YAML infrastructure manifest, providing a structured representation for other components.

**Key Classes**:
- **`ManifestSchema`** (schema.py): Pydantic model representing the schema described in §3 of the PRD.
- **`ManifestParser`** (parser.py): Loads and validates YAML files against the schema.
- **`ManifestUpdater`** (updater.py): Handles in-place updates to the YAML file (e.g., writing selected region).

**Implementation Tasks**:
1. Define the Pydantic models for manifest validation
2. Implement manifest loading and validation
3. Create a function to update specific fields in the YAML file without altering structure

```python
# Example schema.py
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field

class ServiceCapacity(BaseModel):
    unit: str
    required: int

class ServiceSecret(BaseModel):
    alias: str
    name: str

class Service(BaseModel):
    name: str
    type: str
    region: Optional[str] = None
    sku: str
    capacity: Optional[ServiceCapacity] = None
    secrets: Optional[Dict[str, str]] = None
    properties: Optional[Dict[str, Union[str, int, bool, Dict]]] = None
    skip_quota_check: bool = False

class ResourceGroup(BaseModel):
    name: str
    region: Optional[str] = None

class Metadata(BaseModel):
    name: str
    description: Optional[str] = None
    version: str

class Manifest(BaseModel):
    metadata: Metadata
    subscription: Optional[str] = None
    resource_group: ResourceGroup
    region: str = ""
    allowed_regions: List[str] = Field(default_factory=list)
    deployment: Optional[Dict[str, str]] = None
    tags: Dict[str, str] = Field(default_factory=dict)
    key_vault: Optional[str] = None
    services: List[Service]
```

```python
# Example parser.py
import yaml
from pathlib import Path
from .schema import Manifest

class ManifestParser:
    @staticmethod
    def load(file_path: str) -> Manifest:
        """Load and validate a YAML manifest file."""
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        return Manifest.model_validate(data)
```

```python
# Example updater.py
import yaml
from pathlib import Path

class ManifestUpdater:
    @staticmethod
    def update_region(file_path: str, region: str) -> None:
        """Update the region field in the YAML manifest."""
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        
        # Update region
        data['region'] = region
        
        # Write back to file, preserving format
        with open(file_path, 'w') as f:
            yaml.dump(data, f, sort_keys=False)
```

#### 3.1.2 SDK Resolver (provisioner/quota/resolver.py)

**Purpose**: Automatically identify and install SDK packages needed for provider-native quota checks.

**Key Components**:
- **`SDKResolver`**: Maps resource types to the appropriate Azure SDK package and generates a requirements file.
- **Quota Matrix**: Builds a JSON file mapping resource providers to their SDK packages and quota endpoints.

**Implementation Tasks**:
1. Create a mapping of resource types to SDK packages and APIs
2. Implement the resolver to generate requirements for installation
3. Add functionality to check for installed SDKs

```python
# Example resolver.py
import importlib
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Provider to SDK package mapping
SDK_MAPPING = {
    "Microsoft.Web": "azure-mgmt-web",
    "Microsoft.DBforPostgreSQL": "azure-mgmt-rdbms",
    "Microsoft.App": "azure-mgmt-app",
    "Microsoft.OperationalInsights": "azure-mgmt-loganalytics",
    # Add other mappings as needed
}

class SDKResolver:
    def __init__(self, manifest_path: str):
        self.manifest_path = manifest_path
        self.required_sdks = set()
    
    def analyze_manifest(self) -> Set[str]:
        """Parse the manifest and identify required SDK packages."""
        import yaml
        with open(self.manifest_path, 'r') as f:
            data = yaml.safe_load(f)
        
        for service in data.get('services', []):
            provider = service.get('type').split('/')[0]
            if provider in SDK_MAPPING:
                self.required_sdks.add(SDK_MAPPING[provider])
        
        # Always include quota client for fallback
        self.required_sdks.add("azure-mgmt-quota")
        self.required_sdks.add("azure-identity")
        
        return self.required_sdks
    
    def generate_requirements(self, output_path: str = "requirements.txt") -> None:
        """Generate a requirements.txt file with the required SDKs."""
        sdks = self.analyze_manifest()
        
        with open(output_path, 'w') as f:
            for sdk in sorted(sdks):
                f.write(f"{sdk}\n")
        
        print(f"Generated requirements file at {output_path}")
    
    def install_required_sdks(self) -> None:
        """Install required SDKs using UV."""
        self.analyze_manifest()
        cmd = ["uv", "pip", "install"] + list(self.required_sdks)
        subprocess.run(cmd, check=True)
        print(f"Installed required SDKs: {', '.join(self.required_sdks)}")
    
    @staticmethod
    def generate_quota_matrix(output_path: str = "build/quota_matrix.json") -> None:
        """Generate a comprehensive quota matrix JSON file."""
        matrix = {
            "providers": {
                "Microsoft.Compute": {
                    "sdk": "azure-mgmt-compute",
                    "client_class": "ComputeManagementClient",
                    "quota_method": "usage.list",
                    "quota_units": ["vCPUs", "StandardDSv5Family"]
                },
                "Microsoft.Web": {
                    "sdk": "azure-mgmt-web",
                    "client_class": "WebSiteManagementClient",
                    "quota_method": "usages.list_by_location",
                    "quota_units": ["Cores", "AppServicePlans"]
                },
                # Add other providers here
            }
        }
        
        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(matrix, f, indent=2)
        
        print(f"Generated quota matrix at {output_path}")
```

#### 3.1.3 Quota Checker (provisioner/quota/)

**Purpose**: Implement the two-tier quota checking algorithm described in §4 of the PRD.

**Key Classes**:
- **`QuotaChecker`** (checker.py): Implements the quota checking algorithm.
- **`ProviderAdapter`** (providers.py): Base class for provider-specific quota checks.
- **`ProviderAdapterRegistry`**: Registry of provider adapters and fallback logic.
- **`QuotaResult`** (models.py): Data structure for quota check results.

**Implementation Tasks**:
1. Create the quota checking workflow
2. Implement provider-specific quota adapters
3. Add fallback to Microsoft.Quota
4. Build region intersection logic
5. Handle edge cases as described in §4.3

```python
# Example models.py
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class QuotaInfo:
    unit: str
    current_usage: float
    limit: float
    required: float
    
    @property
    def available(self) -> float:
        return self.limit - self.current_usage
    
    @property
    def is_sufficient(self) -> bool:
        return self.available >= self.required

@dataclass
class ResourceQuota:
    resource_type: str
    region: str
    quotas: Dict[str, QuotaInfo]
    
    def is_sufficient(self) -> bool:
        """Check if all quotas are sufficient."""
        return all(q.is_sufficient for q in self.quotas.values())

@dataclass
class RegionAnalysis:
    regions: Dict[str, List[ResourceQuota]]
    viable_regions: List[str]
    
    def save(self, output_path: str) -> None:
        """Save region analysis to JSON file."""
        import json
        # Convert to dict structure
        result = {
            "viable_regions": self.viable_regions,
            "regions": {
                region: [
                    {
                        "resource_type": quota.resource_type,
                        "quotas": {
                            unit: {
                                "current": q.current_usage,
                                "limit": q.limit,
                                "required": q.required,
                                "available": q.available,
                                "sufficient": q.is_sufficient
                            } for unit, q in quota.quotas.items()
                        }
                    } for quota in quotas
                ] for region, quotas in self.regions.items()
            }
        }
        
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
```

```python
# Example providers.py
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import importlib
from azure.identity import DefaultAzureCredential
from .models import QuotaInfo, ResourceQuota

class ProviderAdapter(ABC):
    """Base class for provider-specific quota adapters."""
    
    def __init__(self, subscription_id: str):
        self.subscription_id = subscription_id
        self.credential = DefaultAzureCredential()
    
    @abstractmethod
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        """Check quotas for a specific resource type in a region."""
        pass

class ComputeProviderAdapter(ProviderAdapter):
    """Adapter for Microsoft.Compute quota checks."""
    
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        from azure.mgmt.compute import ComputeManagementClient
        
        client = ComputeManagementClient(self.credential, self.subscription_id)
        usages = client.usage.list(region)
        
        result = ResourceQuota(resource_type, region, {})
        
        # Map capacity units to Azure usage names
        unit_mappings = {
            "vCores": "standardDSv3Family",
            # Add other mappings
        }
        
        for usage in usages:
            # Check if this usage matches what we need
            if usage.name.value.lower() == unit_mappings.get(capacity["unit"].lower()):
                quota_info = QuotaInfo(
                    unit=capacity["unit"],
                    current_usage=usage.current_value,
                    limit=usage.limit,
                    required=capacity["required"]
                )
                result.quotas[capacity["unit"]] = quota_info
                break
        
        return result

# Additional provider adapters would be implemented here

class QuotaClientAdapter(ProviderAdapter):
    """Fallback adapter using Microsoft.Quota."""
    
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        from azure.mgmt.quota import QuotaManagementClient
        
        client = QuotaManagementClient(self.credential, self.subscription_id)
        quotas = client.quotas.list(resource_type, region)
        
        result = ResourceQuota(resource_type, region, {})
        
        for quota in quotas:
            if quota.properties.limit_name.lower() == capacity["unit"].lower():
                quota_info = QuotaInfo(
                    unit=capacity["unit"],
                    current_usage=quota.properties.current_value,
                    limit=quota.properties.limit_value,
                    required=capacity["required"]
                )
                result.quotas[capacity["unit"]] = quota_info
                break
        
        return result

class ProviderAdapterRegistry:
    """Registry of provider adapters with fallback logic."""
    
    def __init__(self, subscription_id: str):
        self.subscription_id = subscription_id
        self.adapters = {
            "Microsoft.Compute": ComputeProviderAdapter(subscription_id),
            # Register other provider adapters
        }
        self.fallback = QuotaClientAdapter(subscription_id)
    
    def get_adapter(self, resource_type: str) -> ProviderAdapter:
        """Get the appropriate adapter for a resource type, with fallback."""
        provider = resource_type.split('/')[0]
        return self.adapters.get(provider, self.fallback)
```

```python
# Example checker.py
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple
from azure.identity import DefaultAzureCredential
from .models import RegionAnalysis, ResourceQuota
from .providers import ProviderAdapterRegistry
from ..manifest.parser import ManifestParser
from ..manifest.updater import ManifestUpdater

class QuotaChecker:
    """Implements the quota checking algorithm."""
    
    def __init__(self, manifest_path: str, dry_run: bool = False, debug: bool = False):
        self.manifest_path = manifest_path
        self.manifest = ManifestParser.load(manifest_path)
        self.dry_run = dry_run
        self.debug = debug
        self.subscription_id = self.manifest.subscription or self._get_default_subscription()
        self.adapter_registry = ProviderAdapterRegistry(self.subscription_id)
    
    def _get_default_subscription(self) -> str:
        """Get the default subscription ID from Azure CLI."""
        import subprocess
        import json
        
        cmd = ["az", "account", "show", "--query", "id", "-o", "tsv"]
        
        # In debug mode, print the command
        if self.debug:
            print(f"Debug: Running command: {' '.join(cmd)}")
            
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        subscription_id = result.stdout.strip()
        
        if self.debug:
            print(f"Debug: Using subscription ID: {subscription_id}")
            
        return subscription_id
    
    def check_quotas(self) -> RegionAnalysis:
        """Check quotas for all services in the manifest."""
        # Get all Azure regions if needed
        all_regions = self._get_all_regions() if not self.manifest.region else [self.manifest.region]
        
        # Filter regions if allowedRegions is specified
        if self.manifest.allowed_regions:
            all_regions = [r for r in all_regions if r in self.manifest.allowed_regions]
        
        # Initialize region analysis
        region_quotas = {region: [] for region in all_regions}
        
        # Check each service
        for service in self.manifest.services:
            # Skip services with no capacity requirements
            if not service.capacity or service.skip_quota_check:
                continue
            
            # Determine which regions to check for this service
            service_regions = [service.region] if service.region else all_regions
            
            for region in service_regions:
                try:
                    adapter = self.adapter_registry.get_adapter(service.type)
                    quota_result = adapter.check_quota(
                        service.type,
                        region,
                        service.capacity.model_dump()
                    )
                    region_quotas[region].append(quota_result)
                except Exception as e:
                    print(f"Error checking quota for {service.type} in {region}: {e}")
                    # Keep track of the error but continue
        
        # Determine viable regions (where all services have sufficient quota)
        viable_regions = []
        for region, quotas in region_quotas.items():
            if all(q.is_sufficient() for q in quotas):
                viable_regions.append(region)
        
        return RegionAnalysis(region_quotas, viable_regions)
    
    def _get_all_regions(self) -> List[str]:
        """Get all available Azure regions."""
        import subprocess
        import json
        
        cmd = ["az", "account", "list-locations", "--query", "[].name", "-o", "json"]
        
        # In debug mode, print the command
        if self.debug:
            print(f"Debug: Running command: {' '.join(cmd)}")
            
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        regions = json.loads(result.stdout)
        
        if self.debug:
            print(f"Debug: Found {len(regions)} available regions")
            
        return regions
    
    def select_region(self, analysis: RegionAnalysis) -> str:
        """Select a region from viable regions."""
        if not analysis.viable_regions:
            raise ValueError("No viable regions found that satisfy quota requirements")
        
        # For now, just select the first viable region
        # Future: implement more sophisticated region selection
        return analysis.viable_regions[0]
    
    def update_manifest_region(self, region: str) -> None:
        """Update the manifest with the selected region."""
        if not self.dry_run:
            ManifestUpdater.update_region(self.manifest_path, region)
        print(f"Selected region: {region}")
```

#### 3.1.4 Bicep Generator (provisioner/bicep/)

**Purpose**: Transform the YAML manifest into Bicep templates and parameter files.

**Key Classes**:
- **`BicepGenerator`** (generator.py): Orchestrates the Bicep generation process.
- Resource builders (builders/): Type-specific builders for each supported resource type.
- **`ParameterFileGenerator`**: Creates the parameters.json file with Key Vault references.

**Implementation Tasks**:
1. Implement the core generator class
2. Create resource-specific builders for each supported resource type
3. Implement parameter file generation

```python
# Example generator.py
import os
from pathlib import Path
from typing import Dict, List, Set
from jinja2 import Environment, FileSystemLoader
from ..manifest.parser import ManifestParser

class BicepGenerator:
    """Generates Bicep templates from YAML manifests."""
    
    def __init__(self, manifest_path: str, output_dir: str = None, debug: bool = False):
        self.manifest_path = manifest_path
        self.manifest = ManifestParser.load(manifest_path)
        self.output_dir = output_dir or Path(manifest_path).parent
        self.debug = debug
        
        # Set up Jinja2 environment
        template_dir = Path(__file__).parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Resource builder mapping
        from .builders.static_site import StaticSiteBuilder
        from .builders.postgres import PostgresBuilder
        from .builders.container_env import ContainerEnvBuilder
        from .builders.log_analytics import LogAnalyticsBuilder
        
        self.builders = {
            "Microsoft.Web/staticSites": StaticSiteBuilder(),
            "Microsoft.DBforPostgreSQL/flexibleServers": PostgresBuilder(),
            "Microsoft.App/managedEnvironments": ContainerEnvBuilder(),
            "Microsoft.OperationalInsights/workspaces": LogAnalyticsBuilder()
        }
    
    def generate(self) -> Tuple[str, str]:
        """Generate Bicep template and parameters file."""
        if self.debug:
            print(f"Debug: Generating Bicep files from {self.manifest_path}")
            print(f"Debug: Output directory: {self.output_dir}")
            
        bicep_content = self._generate_bicep_file()
        params_content = self._generate_parameters_file()
        
        # Write files
        bicep_path = os.path.join(self.output_dir, "main.bicep")
        params_path = os.path.join(self.output_dir, "main.parameters.json")
        
        with open(bicep_path, 'w') as f:
            f.write(bicep_content)
        
        with open(params_path, 'w') as f:
            f.write(params_content)
        
        if self.debug:
            print(f"Debug: Bicep file written to {bicep_path}")
            print(f"Debug: Parameters file written to {params_path}")
            
        return bicep_path, params_path
    
    def _generate_bicep_file(self) -> str:
        """Generate the main Bicep file content."""
        # Collect secure parameters needed
        used_secrets = self._collect_used_secrets()
        
        # Generate resource snippets and track dependencies
        resources = self._generate_resources()
        
        # Render the full template
        template = self.jinja_env.get_template("base.bicep")
        return template.render(
            manifest=self.manifest,
            resources=resources,
            secrets=used_secrets
        )
    
    def _generate_parameters_file(self) -> str:
        """Generate the parameters JSON file with Key Vault references."""
        template = self.jinja_env.get_template("parameters.json")
        
        # Collect secrets used in the template
        used_secrets = self._collect_used_secrets()
        
        # Build parameters object
        parameters = {}
        
        # Add secrets as Key Vault references
        for secret_param in used_secrets:
            secret_name = self.manifest.secrets.get(secret_param)
            if secret_name:
                parameters[secret_param] = {
                    "reference": {
                        "keyVault": {
                            "id": self.manifest.key_vault
                        },
                        "secretName": secret_name
                    }
                }
        
        return template.render(parameters=parameters)
    
    def _collect_used_secrets(self) -> Set[str]:
        """Collect all secret names that are used in the manifest."""
        used_secrets = set()
        
        for service in self.manifest.services:
            if service.secrets:
                for secret_name in service.secrets.values():
                    used_secrets.add(secret_name)
        
        return used_secrets
    
    def _generate_resources(self) -> List[str]:
        """Generate Bicep code for all resources."""
        # Determine resource ordering for dependencies
        ordered_services = self._order_services_by_dependencies()
        
        # Generate code for each resource
        resources = []
        for service in ordered_services:
            builder = self.builders.get(service.type)
            if not builder:
                raise ValueError(f"Unsupported resource type: {service.type}")
            
            # Generate resource snippet
            snippet = builder.build(service, self.manifest)
            resources.append(snippet)
        
        return resources
    
    def _order_services_by_dependencies(self) -> List:
        """Order services to ensure dependencies are deployed first."""
        # Simple implementation - this would need enhancement for complex dependencies
        # Put Log Analytics workspaces first since Container Environments may depend on them
        
        ordered = []
        log_analytics = []
        container_envs = []
        others = []
        
        for service in self.manifest.services:
            if service.type == "Microsoft.OperationalInsights/workspaces":
                log_analytics.append(service)
            elif service.type == "Microsoft.App/managedEnvironments":
                container_envs.append(service)
            else:
                others.append(service)
        
        return log_analytics + container_envs + others
```

```python
# Example static_site.py
from typing import Dict, Any
from ..models import ServiceModel, ManifestModel

class StaticSiteBuilder:
    """Builds Bicep code for Static Web Apps."""
    
    def __init__(self):
        self.api_version = "2023-01-01"  # Latest stable API version
    
    def build(self, service: ServiceModel, manifest: ManifestModel) -> str:
        """Build a Bicep resource snippet for Static Web App."""
        region = service.region or manifest.region
        
        # Merge tags
        tags = {**manifest.tags, **(service.properties.get("tags", {}))}
        
        # Build SKU object
        sku_name = service.sku
        sku_block = f"""sku: {{
  name: '{sku_name}'
  tier: '{sku_name}'
}}"""
        
        # Build identity block if needed
        identity_block = ""
        if service.identity == "SystemAssigned":
            identity_block = """identity: {
  type: 'SystemAssigned'
}"""
        
        # Build properties
        properties = {}
        
        # Add repository settings if present
        if hasattr(service, "repo") and service.repo:
            repo = service.repo
            properties.update({
                "repositoryUrl": repo.url,
                "branch": repo.branch,
                "repositoryToken": repo.token if not repo.token.startswith('"') else repo.token[1:-1],
                "provider": repo.provider
            })
        
        # Format properties block
        props_block = "properties: {\n"
        for k, v in properties.items():
            if isinstance(v, str) and not v.startswith('"'):
                props_block += f"  {k}: '{v}'\n"
            else:
                props_block += f"  {k}: {v}\n"
        props_block += "}"
        
        # Build tags block
        tags_block = "tags: {\n"
        for k, v in tags.items():
            tags_block += f"  {k}: '{v}'\n"
        tags_block += "}"
        
        # Assemble resource block
        return f"""resource {service.name} 'Microsoft.Web/staticSites@{self.api_version}' = {{
  name: '{service.name}'
  location: '{region}'
  {sku_block}
  {identity_block}
  {props_block}
  {tags_block}
}}
"""
```

Similar builder classes would be created for other resource types following the same pattern.

### 3.2 CLI Implementation (main.py)

**Purpose**: Provide a command-line interface for the provisioner tools.

**Key Components**:
- **`app`**: Typer CLI application with commands for each lifecycle operation.
- Command implementations for quota-check, generate, deploy, and destroy operations.

**Implementation Tasks**:
1. Set up the Typer CLI structure
2. Implement each command with appropriate options and help text
3. Add error handling and output formatting

```python
# Example main.py
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
```

### 3.3 Utility Scripts (scripts/)

**Purpose**: Provide standalone utility scripts for CI/CD integration.

**Key Scripts**:
- **`resolve_sdks.py`**: Resolves required SDKs based on a manifest.
- **`quota_check.py`**: Standalone quota check script for CI/CD.

**Implementation Tasks**:
1. Implement SDK resolver script
2. Create the quota check script with appropriate exit codes

```python
# Example resolve_sdks.py
#!/usr/bin/env python
import sys
import argparse
from provisioner.quota.resolver import SDKResolver

def main():
    parser = argparse.ArgumentParser(description="Resolve Azure SDK dependencies for quota checks")
    parser.add_argument("manifest", help="Path to infrastructure YAML manifest")
    parser.add_argument("--output", "-o", default="requirements.txt", help="Output requirements file")
    args = parser.parse_args()
    
    try:
        resolver = SDKResolver(args.manifest)
        resolver.generate_requirements(args.output)
        return 0
    except Exception as e:
        print(f"Error resolving SDKs: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

```python
# Example quota_check.py
#!/usr/bin/env python
import sys
import argparse
from provisioner.quota.checker import QuotaChecker

def main():
    parser = argparse.ArgumentParser(description="Check Azure quota availability for infrastructure manifest")
    parser.add_argument("--config", "-c", default="infra.yaml", help="Path to infrastructure YAML manifest")
    parser.add_argument("--output", "-o", default="region-analysis.json", help="Output analysis file")
    parser.add_argument("--dry-run", action="store_true", help="Don't update the manifest with selected region")
    parser.add_argument("--auto-select", action="store_true", help="Automatically select a viable region")
    args = parser.parse_args()
    
    try:
        checker = QuotaChecker(args.config, dry_run=args.dry_run)
        analysis = checker.check_quotas()
        analysis.save(args.output)
        
        if not analysis.viable_regions:
            print("No viable regions found that satisfy quota requirements", file=sys.stderr)
            return 2
        
        if args.auto_select:
            selected_region = checker.select_region(analysis)
            checker.update_manifest_region(selected_region)
            print(f"Selected region: {selected_region}")
        
        return 0
    except Exception as e:
        print(f"Error checking quotas: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

## 4. Testing Strategy

### 4.1 Unit Tests

Unit tests should be created for each component, focusing on the following:

- **Manifest Parser Tests**: Ensure the parser correctly validates YAML files against the schema.
- **Quota Check Tests**: Test quota check logic with mocked Azure API responses.
- **Bicep Generator Tests**: Verify the generation of correct Bicep code for each resource type.
- **Dependency Resolution Tests**: Test the dependency ordering and inheritance logic.

Example test setup:

```python
# Example test_manifest_parser.py
import pytest
from provisioner.manifest.parser import ManifestParser
from provisioner.manifest.schema import Manifest

def test_valid_manifest():
    # Test with a minimal valid manifest
    yaml_content = """
    metadata:
      name: test
      version: "1.0"
    resource_group:
      name: test-rg
    region: eastus
    services:
      - name: test-site
        type: Microsoft.Web/staticSites
        sku: Free
    """
    with open("test_manifest.yaml", "w") as f:
        f.write(yaml_content)
    
    manifest = ManifestParser.load("test_manifest.yaml")
    assert isinstance(manifest, Manifest)
    assert manifest.metadata.name == "test"
    assert manifest.resource_group.name == "test-rg"
    assert manifest.region == "eastus"
    assert len(manifest.services) == 1
    assert manifest.services[0].name == "test-site"
```

### 4.2 Integration Tests

Integration tests should be created to test the end-to-end workflow:

- **Manifest to Bicep**: Test the full conversion from YAML to Bicep.
- **Quota Checking**: Test the quota checking with real (but read-only) Azure API calls.
- **CLI Tests**: Test the CLI with various arguments and options.

### 4.3 Mocking Azure APIs

For testing, you'll need to mock the Azure APIs to avoid making real calls:

```python
# Example test_quota_checker.py with mocks
import pytest
from unittest.mock import patch, MagicMock
from provisioner.quota.checker import QuotaChecker
from provisioner.quota.models import QuotaInfo, ResourceQuota, RegionAnalysis

@pytest.fixture
def mock_quotas():
    # Create mock quota results
    return {
        "eastus": [
            ResourceQuota(
                resource_type="Microsoft.Web/staticSites",
                region="eastus",
                quotas={
                    "instances": QuotaInfo(
                        unit="instances",
                        current_usage=1,
                        limit=10,
                        required=1
                    )
                }
            )
        ],
        "westus2": [
            ResourceQuota(
                resource_type="Microsoft.Web/staticSites",
                region="westus2",
                quotas={
                    "instances": QuotaInfo(
                        unit="instances",
                        current_usage=9,
                        limit=10,
                        required=2
                    )
                }
            )
        ]
    }

@patch("provisioner.quota.checker.ProviderAdapterRegistry")
def test_quota_checker(mock_registry, mock_quotas):
    # Setup mock adapter to return predefined quotas
    mock_adapter = MagicMock()
    mock_adapter.check_quota.side_effect = lambda resource_type, region, capacity: mock_quotas[region][0]
    
    mock_registry_instance = MagicMock()
    mock_registry_instance.get_adapter.return_value = mock_adapter
    mock_registry.return_value = mock_registry_instance
    
    # Create the checker with a test manifest
    checker = QuotaChecker("test_manifest.yaml", dry_run=True)
    
    # Run the check
    analysis = checker.check_quotas()
    
    # Verify results
    assert "eastus" in analysis.viable_regions
    assert "westus2" not in analysis.viable_regions
```

## 5. Implementation Phases

### 5.1 Phase 1: Core Infrastructure

1. Set up the project structure and package management with UV
2. Implement the YAML manifest parsing and validation
3. Create the basic CLI structure

### 5.2 Phase 2: Quota Checking

1. Implement the SDK resolver
2. Create provider-specific quota adapters
3. Implement the quota checking algorithm
4. Add region selection logic

### 5.3 Phase 3: Bicep Generation

1. Implement the core Bicep generator
2. Create resource-specific builders for each supported type
3. Implement parameter file generation for secrets

### 5.4 Phase 4: Testing and Integration

1. Add unit tests for all components
2. Create integration tests for the end-to-end workflow
3. Implement CI/CD scripts for GitHub Actions

### 5.5 Phase 5: Documentation and Packaging

1. Create comprehensive documentation
2. Package the application for distribution
3. Create sample manifests and tutorials

## 6. Dependencies and External Services

### 6.1 Required Python Packages

- **Core Dependencies**:
  - `pyyaml`: YAML parsing and serialization
  - `pydantic`: Data validation and schema definition
  - `jinja2`: Template rendering for Bicep files
  - `azure-identity`: Azure authentication
  - `azure-mgmt-quota`: Generic quota client
  - `typer`: CLI interface
  - `rich`: Terminal formatting and output
  - `tenacity`: Retries for Azure API calls

- **Provider-Specific SDKs** (auto-resolved based on manifest):
  - `azure-mgmt-web`: For Microsoft.Web resources
  - `azure-mgmt-rdbms`: For PostgreSQL resources
  - `azure-mgmt-app`: For Container Apps resources
  - `azure-mgmt-loganalytics`: For Log Analytics resources

### 6.2 Azure Dependencies

- Azure CLI for authentication and deployment
- Access to the Azure APIs with appropriate permissions

## 7. Conclusion

This implementation plan details how to build a quota-aware Bicep generator for Azure resources based on the PRD and research. The application will be built in Python, managed with UV, and provide a clean CLI interface for each stage of the workflow.

The architecture is modular and extensible, allowing for:
- Addition of new resource types
- Support for different quota checking methods
- Extension to additional cloud operations

By following the phased approach, the team can build, test, and deliver the application incrementally, ensuring each component works correctly before moving to the next phase.