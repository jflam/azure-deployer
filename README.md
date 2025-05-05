# Azure Deployer - Quota‑Aware Bicep Generator & Region‑Selector

A Python-based CLI tool that reads `infra.yaml`, performs quota validation, auto‑selects a region, generates Bicep + parameters files, and optionally deploys or destroys the stack.

## Prerequisites

1. Python ≥3.11
2. [uv](https://github.com/astral/uv) package manager
3. Azure CLI ≥2.54 with the quota extension
4. Logged-in Azure CLI identity with:
   - **Reader** at subscription scope (for quota queries)
   - **Contributor** at subscription scope (for deployments)

## Quick Start

```bash
# Check quotas and select region
uv run python deployer.py quota-check

# Generate Bicep templates
uv run python deployer.py generate

# Deploy the stack (with rollback on error)
uv run python deployer.py deploy

# Optional: Deploy and remove orphaned resources
uv run python deployer.py deploy --prune

# Tear down the stack
uv run python deployer.py destroy
```

## Configuration (`infra.yaml`)

The infrastructure is defined in `infra.yaml`. Key sections:

```yaml
metadata:
  name: my-stack
  description: Stack description
  version: 1.0.0

resourceGroup:
  name: my-rg
  region: ""  # Inherits from top-level region

region: ""  # Leave blank for quota-based selection
allowedRegions: []  # Optional whitelist

deployment:
  rollback: lastSuccessful  # none | lastSuccessful | named:<name>

services:
  - name: service-name
    type: Microsoft.ServiceType/resourceType
    sku: Standard_X
    capacity:
      unit: vCores  # Must match Quota API name.value
      required: 2
    properties:
      # Service-specific properties
```

## Commands

| Command | Description |
|---------|-------------|
| `quota-check` | Validate quotas & optionally auto‑select region |
| `generate` | Produce Bicep & parameter files |
| `deploy` | Run quota check + generate + ARM deploy |
| `deploy --prune` | As above, but delete orphaned resources |
| `destroy` | Tear down all resources |

### Global Options

- `-c, --config <path>` - Path to infra.yaml (default: ./infra.yaml)
- `--auto-select` - Pick first viable region without prompt
- `-v, --verbose` - Debug logging

## Exit Codes

- 0: Success
- 1: Fatal error (parsing, validation, etc.)
- 2: No viable regions satisfy quota requirements

## Generated Files

- `main.bicep` - Main deployment template
- `modules/*.bicep` - Resource-specific modules
- `main.parameters.json` - Parameter file
- `region-analysis.json` - Quota check results

## Secret Handling

The manifest stores **no plaintext secrets**. Confidential values referenced by `secretRef` are supplied at deploy-time via:

1. Key Vault (preferred)
2. `main.parameters.json`

If a secret exists in both locations, Key Vault takes precedence.