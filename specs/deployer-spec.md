# Quota‑Aware Bicep Generator & Region‑Selector — Functional Specification (Provisioner)

> **Version 0.3 — 6 May 2025**    <small>(Supersedes v0.2)</small>
>
> **Change‑log**
>
> * Replaced single‑source **Microsoft.Quota** dependency with a *provider‑native‑first* strategy that falls back to Microsoft.Quota only when required.
> * Algorithm and CLI updated accordingly (§4).
> * Added automated SDK‑resolution helper and **Appendix B** cheat‑sheet of usage/quotas endpoints.
> * Tracked open issues renumbered; new Issue 16 covers SDK pinning.

---

## 1 Background & Problem Statement

### 1.1 Why Bicep templates are often handwritten

Bicep is ARM’s first‑class DSL, complete with IntelliSense, modules, loops and rich tooling. Tutorials assume engineers hand‑edit `.bicep` files and commit them to source control.

That works until teams must:

* **Run the *same* stack in many environments** (dev / test / prod / per‑PR).
* **Dynamically shift regions** when a SKU is unavailable or quota‑blocked.
* **Extend stacks rapidly** with new Azure services.

Hand‑editing multiple Bicep files soon becomes error‑prone and painful.

### 1.2 The quota‑failure pain‑point

Azure quotas are enforced **per‑subscription → per‑region → per‑resource‑type**.  If any single resource exceeds its limit the entire ARM deployment fails (`InvalidTemplateDeployment`, `SkuNotAvailable`, etc.). CI minutes and developer attention are wasted.

Microsoft GA’d a generic **Microsoft.Quota** resource provider (RP) in 2024, but several critical RPs — notably **Flexible PostgreSQL/MySQL** — expose richer, *provider‑native* quota APIs that are **absent** from Microsoft.Quota.  Depending on the generic RP alone leaves gaps and false negatives.

We therefore introduce a **two‑tier quota checker**:

1. **Provider‑native `usages`/`quotas` endpoints first** — accessed via Azure SDK for Python.  Coverage today includes Compute, Network, Storage, Web, Batch, Container Apps, Machine Learning, SQL, PostgreSQL, etc.
2. **Fallback to Microsoft.Quota** (`azure‑mgmt‑quota`) where the service RP lacks native support.

This change makes quota discovery reliable for real‑world workloads *today* while remaining forward‑compatible as Microsoft.Quota expands.

---

## 2 Design Goals

| Goal                                                      | Rationale                                                                |
| --------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Provider‑native APIs first; generic Quota as fallback** | Maximises coverage (e.g. Flexible PostgreSQL) and avoids blind‑spots.    |
| **Declarative service list in YAML**                      | Separates *what* from *how*; easier code‑review & diff.                  |
| **Automatic region selection**                            | Removes manual trial‑and‑error when quotas are exhausted.                |
| **Quota pre‑check before any ARM/Bicep call**             | Fails fast in CLI; saves CI time.                                        |
| **One‑shot generation of Bicep + parameter files**        | Pipeline identical to traditional Bicep once region chosen.              |
| **Extensible schema & SDK auto‑resolution**               | Adding a service just adds a YAML stanza; helper installs its SDK wheel. |

---

## 3 YAML Configuration Schema (v0.3)

```yaml
# infra.yaml — schema v0.3

metadata:
  name: ai-stack
  description: Declarative manifest of Azure resources to deploy.
  version: 0.3.0

subscription: 00000000-0000-0000-0000-000000000000   # optional override

resourceGroup:
  name: demo-rg
  region: ""                # inherits .region unless explicitly set

# Region‑selection behaviour
region: ""                     # blank → quota workflow picks one
allowedRegions: []             # optional whitelist

deployment:
  rollback: lastSuccessful     # none | lastSuccessful | named:<deploymentName>

# Global tags applied to every resource
tags:
  environment: dev

# Default Key Vault for secretRef indirection (optional)
keyVault: ai-stack-kv

services:
  # Static Web App (quota‑free example)
  - name: static-web
    type: Microsoft.Web/staticSites
    region: westus2            # OPTIONAL – overrides top‑level region
    sku: Free
    capacity: null               # quota‑free or negligible
    properties:
      tags: { app: ai-starter }

  # Flexible Postgres
  - name: postgres
    type: Microsoft.DBforPostgreSQL/flexibleServers
    sku: Standard_B1ms
    capacity:
      unit: vCores               # must match provider-native unit
      required: 2
    secrets:
      adminPassword: pgAdminPassword
    properties:
      version: 16
      storageGB: 32

  # Container Apps Environment
  - name: api-env
    type: Microsoft.App/managedEnvironments
    region: eastus             # runs in its own region
    sku: Consumption
    capacity:
      unit: Cores
      required: 4
    skipQuotaCheck: false

  # Log Analytics Workspace
  - name: log-analytics
    type: Microsoft.OperationalInsights/workspaces
    sku: PerGB2018
    capacity: null
```

**Region evaluation rules** and **Secret handling** are unchanged from v0.2.

---

## 4 Quota Discovery Workflow (revised)

### 4.1 Prerequisites

* **Python 3.11** (via pipx/poetry) with:

  * `azure-identity`
  * Service‑specific management SDKs matching the manifest (auto‑resolved by `resolve_sdks.py`).
  * `azure-mgmt-quota` as universal fallback.
* Azure CLI ≥ 2.54 (optional; used for login & debugging only).
* Logged‑in identity needs **Reader** on subscription to query quotas and **Contributor** to deploy.

### 4.2 Algorithm

1. **Parse** manifest → tuples `(provider, capacity[], region)`.
2. For each tuple **call `query_quota()`**:

   1. Attempt **provider‑native SDK**:
      `sdk = importlib.import_module(MAPPING[provider])`  →  `client = sdk(...)
      usage = client.<usages‑op>(location)`
   2. **Fallback** to `azure.mgmt.quota.QuotaClient` if native op not present or returns 404.
   3. If still unsupported → error unless service has `skipQuotaCheck: true`.
3. **Evaluate** sufficiency: `(limit – current) ≥ required` for each declared `capacity.unit`.
4. **Intersect regions** across shared‑region services.  If empty → exit **2** and emit `region-analysis.json`.
5. **Persist** selected region to manifest unless `--dry-run`.
6. **Prompt the user** (CLI `read -p`, `Select-String`, or interactive `fzf`) to choose from the remaining regions.  Persist the choice back into `infra.yaml`:

   ```bash
   yq -i '.region = strenv(AZ_REGION)' infra.yaml
   ```

7. **Continue to generation / deployment**.
8. Exit codes: 0 (ok) | 1 (parse error) | 2 (no region satisfies quota).

### 4.3 Edge Cases

| Scenario                                             | Handling                                               |
| ---------------------------------------------------- | ------------------------------------------------------ |
| Service lacks native & generic quota API             | Fail with actionable message; suggest portal/support.  |
| Generic Quota RP lacks the requested `capacity.unit` | Downgrade check to best‑effort; warn operator.         |
| Multi‑unit SKUs (GPU + vCPU)                         | Accept **array** in `capacity`; *all* units must pass. |
| `skipQuotaCheck: true`                               | Service excluded; user accepts risk.                   |

---

## 5  Bicep Generation Strategy

1. **Template directory layout**

```
/templates
   common/
      rg.bicep           # resource group module
   modules/
      containerapps.bicep
      postgres-flex.bicep
      staticwebapp.bicep
generate.ts              # Node script that reads YAML and writes main.bicep
```

2. **Generation script behaviour**

* Reads `infra.yaml`, pulls `region`, `resourceGroup`, and service list.

* Emits a single `main.bicep` that:

  ```bicep
  targetScope = 'subscription'

  param location string = '${region}'
  param resourceGroupName string = '${resourceGroup}'

  module rg 'common/rg.bicep' = {
    name: 'rg'
    params: { name: resourceGroupName location: location }
  }

  // Example ACA inject
  module aca 'modules/containerapps.bicep' = if (!empty(services.aca)) {
    name: 'aca'
    scope: resourceGroup(rg.outputs.rgName)
    params: {
       name: services.aca.name
       envSku: services.aca.sku
    }
  }
  ```

* Writes a companion `main.parameters.json` containing secret values or size overrides, so that downstream deployment sees no difference from a hand-authored Bicep template.

3. **Toolchain**

* Author generator in Python.
* Commit generated files, or add `main.bicep` to `.gitignore` and generate in CI before “bicep build”.
* Use `bicepconfig.json` for module registry aliases ([Microsoft Learn][7]).

---

## 6 Lifecycle Commands (CLI)

| Command          | Behaviour                                                                        |
| ---------------- | -------------------------------------------------------------------------------- |
| `quota-check`    | Runs algorithm; auto‑installs missing SDK wheels; writes `region-analysis.json`. |
| `generate`       | Manifest → `main.bicep` + `main.parameters.json`.                                |
| `deploy`         | Incremental ARM deployment; warns of orphans when run without `--prune`.         |
| `deploy --prune` | Incremental deploy + delete orphans.                                             |
| `destroy`        | Deletes all resources then RG (purge‑protection handling out of scope).          |

*Concurrency* — ARM deployment name derived from `metadata.name`; Azure serialises overlapping runs.

---

## 7 CI/CD Pipeline Sketch (GitHub Actions)

```yaml
name: deploy
on:
  workflow_dispatch:

jobs:
  preflight:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Resolve SDKs & quota check
        run: |
          python scripts/resolve_sdks.py infra.yaml > requirements.txt
          python -m pip install --require-hashes -r requirements.txt
          python scripts/quota_check.py --config infra.yaml --auto-select
          if [ $? -ne 0 ]; then cat region-analysis.json; exit 1; fi

      - name: Generate Bicep
        run: node generate.js infra.yaml

      - name: What‑if
        run: |
          az deployment sub what-if \
            --region $(yq '.region' infra.yaml) \
            --template-file main.bicep \
            --parameters @main.parameters.json

      - name: Deploy
        run: |
          az deployment sub create \
            --region $(yq '.region' infra.yaml) \
            --template-file main.bicep \
            --parameters @main.parameters.json
```

---

## 8 Prior Art & Community Signals

* Provider‑native usage endpoints date back to 2015 (Compute) yet remain under‑used.
* Terraform *azurerm* #14969 (2025‑Q1) reached the same conclusion: prefer native endpoints; generic Quota as fallback.
* Bicep community scripts typically call `az rest` against provider‑native paths for reliability.

---

## 9 Outstanding Issues & Resolutions (snapshot)

|  # | Issue                           | Status                                               |
| -- | ------------------------------- | ---------------------------------------------------- |
| 2  | Authoritative capacity‑unit map | **Resolved** — generated by `resolve_sdks.py`.       |
| 10 | Multi‑subscription support      | **Open** — design TBD.                               |
| 14 | Telemetry & audit logging       | **Open** — decide sink & retention.                  |
| 16 | SDK auto‑resolution & pinning   | **New** — implemented in helper but needs UX polish. |

*All other issues from v0.2 remain resolved.*

---

## 10 Open Questions & Next Steps

* Ship a minimal offline cache of quota metadata for air‑gapped CI?
* UX for prompting operator when multiple viable regions remain.
* Long‑term module strategy for unknown resource types.

---

## Appendix A — Secret Handling (unchanged)

*Manifest stores no plaintext secrets.  `secretRef` indirection to Key Vault or parameter file; KV wins precedence.*

---

## Appendix B — Provider‑Native Quota Endpoints (cheat‑sheet)

| Service area                                   | Resource provider                 | Python SDK class & op                                     | Quota unit examples            |
| ---------------------------------------------- | --------------------------------- | --------------------------------------------------------- | ------------------------------ |
| Compute (VM cores, Dedicated Hosts)            | Microsoft.Compute                 | `ComputeManagementClient.usage.list(location)`            | vCPUs, StandardDSv5Family      |
| Network (PIP, NIC, VNet)                       | Microsoft.Network                 | `NetworkManagementClient.usages.list(location)`           | IPAddresses, NetworkInterfaces |
| Storage accounts & capacity                    | Microsoft.Storage                 | `StorageManagementClient.usages.list_by_location()`       | StorageAccounts                |
| App Service / Functions                        | Microsoft.Web                     | `WebSiteManagementClient.usages.list_by_location()`       | Cores, AppServicePlans         |
| Container Instances                            | Microsoft.ContainerInstance       | `ContainerInstanceManagementClient.location.list_usage()` | Cores                          |
| Container Apps                                 | Microsoft.App                     | `AppManagementClient.usages.list()`                       | Cores, MemoryGB                |
| AKS (partial)                                  | Microsoft.ContainerService        | — (use `QuotaClient.quotas.list()` fallback)              | ***generic***                  |
| Batch                                          | Microsoft.Batch                   | `BatchManagementClient.location.get_quotas()`             | DedicatedCores                 |
| Machine Learning                               | Microsoft.MachineLearningServices | `MachineLearningServicesManagementClient.usages.list()`   | GPUHours, PTU                  |
| SQL DB / MI                                    | Microsoft.Sql                     | `SubscriptionUsagesClient.list_by_location()`             | vCores, Servers                |
| PostgreSQL Flexible                            | Microsoft.DBforPostgreSQL         | `QuotaUsagesClient.list()`                                | vCores, Servers                |
| MySQL Flexible                                 | Microsoft.DBforMySQL              | *preview* — `QuotaUsagesClient.list()`                    | vCores, Servers                |
| Other RPs (Redis, Event Hubs, Cognitive, ACR…) | Various                           | — or `QuotaClient` fallback                               | varies                         |

`resolve_sdks.py` consumes this table at build‑time, locks exact SDK versions, and writes `build/quota_matrix.json` so the CLI and docs remain in sync.

---

**END OF SPEC v0.3**

