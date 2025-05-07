# Azure Provisioner Knowledge

## Project Overview
A Python-based CLI tool that reads `infra.yaml`, performs quota validation, auto‑selects a region, generates Bicep + parameters files, and optionally deploys or destroys Azure infrastructure stacks.

## Key Concepts
- Uses Python 3.12 (see `.python-version`)
- Runs via `uv run` for dependency management
- No development server needed - this is a CLI tool

## Development Setup
1. Python ≥3.12 required
2. Install [uv](https://github.com/astral/uv) package manager
3. Azure CLI ≥2.54 with quota extension
4. Azure CLI identity needs:
   - **Reader** at subscription scope (quota queries)
   - **Contributor** at subscription scope (deployments)

## Commands
```bash
# Check quotas and select region
uv run python provisioner.py quota-check

# Generate Bicep templates
uv run python provisioner.py generate

# Deploy the stack
uv run python provisioner.py provision

# Deploy and remove orphaned resources
uv run python provisioner.py provision --prune

# Tear down the stack
uv run python provisioner.py destroy
```

## Project Structure
- `provisioner.py` - Main CLI implementation
- `infra.yaml` - Infrastructure manifest
- `main.py` - Entry point (currently just a hello world)
- `specs/` - Design specifications and plans
  - `provisioner-spec.md` - Main specification
  - `mvp_plan.md` - Implementation plan
  - `example-deployment.md` - Example deployment configuration

## Important Links
- [uv Documentation](https://github.com/astral/uv)
- [Azure CLI Documentation](https://learn.microsoft.com/en-us/cli/azure/)