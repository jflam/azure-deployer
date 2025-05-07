# Azure Provisioner

A quota-aware Bicep generator and region selector for Azure deployments. This tool helps you:
- Find regions with sufficient quota for your Azure resources
- Generate Bicep templates from YAML manifests
- Deploy and manage your Azure infrastructure

## Features

- **Quota-Aware Region Selection**: Automatically checks Azure quotas across regions to find viable deployment locations
- **YAML-Based Infrastructure Definition**: Define your Azure infrastructure using simple YAML manifests
- **Bicep Generation**: Generates Bicep templates and parameter files from your YAML definitions
- **Resource Support**:
  - Static Web Apps
  - PostgreSQL Flexible Servers
  - Container Apps Environments
  - Log Analytics Workspaces
  - More coming soon...
- **Azure SDK Auto-Resolution**: Automatically installs required Azure SDK packages based on your manifest

## Installation

Requires Python 3.12 or later.

```bash
# Clone the repository
git clone https://github.com/yourusername/azure-provisioner.git
cd azure-provisioner

# Install using uv (recommended)
uv pip install -e ".[dev]"

# Or using pip
pip install -e ".[dev]"
```

## Usage

### Basic Commands

```bash
# Check quotas and find viable regions
provisioner quota-check --config infra.yaml

# Generate Bicep files
provisioner generate --config infra.yaml

# Deploy resources
provisioner deploy --config infra.yaml

# Preview changes without deploying
provisioner deploy --config infra.yaml --what-if

# Delete resources
provisioner destroy --config infra.yaml
```

### Command Options

#### quota-check
```bash
provisioner quota-check [OPTIONS]
  --config, -c TEXT     Path to the infrastructure YAML file [default: infra.yaml]
  --dry-run            Don't update the manifest with selected region
  --output, -o TEXT    Path for quota analysis output [default: region-analysis.json]
  --auto-select        Automatically select a viable region
  --debug              Print verbose debug information
```

#### generate
```bash
provisioner generate [OPTIONS]
  --config, -c TEXT     Path to the infrastructure YAML file [default: infra.yaml]
  --output-dir, -o TEXT Directory for generated Bicep files
  --debug              Print verbose debug information
```

#### deploy
```bash
provisioner deploy [OPTIONS]
  --config, -c TEXT    Path to the infrastructure YAML file [default: infra.yaml]
  --prune             Delete orphaned resources
  --what-if           Show what would be deployed without making changes
  --debug             Print verbose debug information
```

#### destroy
```bash
provisioner destroy [OPTIONS]
  --config, -c TEXT    Path to the infrastructure YAML file [default: infra.yaml]
  --force, -f         Skip confirmation prompt
  --debug             Print verbose debug information
```

## Manifest Structure

Example YAML manifest:

```yaml
metadata:
  name: my-app
  version: "1.0"
  description: "My application infrastructure"

resource_group:
  name: my-app-rg

region: ""  # Will be set by quota-check
allowed_regions:
  - eastus
  - westus2
  - centralus

services:
  - name: my-static-site
    type: Microsoft.Web/staticSites
    sku: Free
    capacity:
      unit: instances
      required: 1

  - name: my-postgres
    type: Microsoft.DBforPostgreSQL/flexibleServers
    sku: Standard_B1ms
    capacity:
      unit: vCores
      required: 1
    properties:
      administratorLogin: pgadmin
      version: "16"
      storageGB: 32

  - name: my-container-env
    type: Microsoft.App/managedEnvironments
    sku: Consumption
    capacity:
      unit: Cores
      required: 4
      environment_name: my-container-env  # Required for core quota checking
      resource_group: my-app-rg           # Required for core quota checking
```

## Quota Checking Details

### Azure Container Apps Core Quotas

Azure Container Apps CPU core quotas are managed at the environment level, not at the region level. For Container Apps environments, the core quota is typically set to 100 cores per environment by default. The provisioner handles this special case as follows:

1. When checking core quotas for `Microsoft.App/managedEnvironments`:
   - The tool looks for `environment_name` and `resource_group` in the capacity section
   - It attempts to query the environment-level quotas using these values
   - If the environment doesn't exist yet (common during planning), it uses the default Azure limit of 100 cores

2. Required capacity configuration for Container Apps environments:

```yaml
capacity:
  unit: Cores
  required: 4  # Number of cores needed
  environment_name: my-container-env  # Name of the environment (can be planned)
  resource_group: my-resource-group   # Resource group for the environment
```

This approach allows accurate quota checking for both existing environments and environments that will be created as part of the deployment.

### Quota Analysis Output Format

The quota analysis output displays quota information in a user-friendly format:

1. **Required/Available Format**: Values are shown as "Required/Available" making it clear how much quota is needed versus how much is available.
2. **Color-Coded Values**: 
   - **Green** values indicate sufficient quota (Required ≤ Available)
   - **Red** values indicate insufficient quota (Required > Available)
3. **Comprehensive Legend**: The output includes a detailed legend explaining the meaning of the colors and status indicators.

1. For Container Apps (`Microsoft.App/managedEnvironments`), it checks quotas at the environment level when `unit: Cores` is specified.
2. Required properties for Container Apps core quota checking:
   - `environment_name`: Name of the environment (must match the service name)
   - `resource_group`: Resource group containing the environment

By default, Azure allocates 100 cores per Container Apps environment. The quota checker uses this value when querying the environment-level quota.

## Development

### Dependencies

Development dependencies are included in the `[dev]` extra:
- pytest
- black
- isort
- mypy
- pytest-cov

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=provisioner
```

## Author

John Lam (jflam@microsoft.com)

## License

MIT