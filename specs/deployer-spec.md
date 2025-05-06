# Quota-Aware Bicep Generator & Region-Selector – Functional Specification (Provisioner)

## 1 Background & Problem Statement

### 1.1 Why Bicep templates are often handwritten

Bicep is ARM’s first‑class DSL, complete with IntelliSense, modules, loops and rich tooling. Most tutorials therefore assume engineers will edit `.bicep` files directly and commit them to source control.

That approach breaks down when teams must:

* **Run the *************************same************************* stack in many environments** (dev / test / prod / per‑PR).
* **Dynamically shift regions** when a resource SKU is unavailable or quota‑blocked.
* **Extend stacks rapidly** with new Azure services.

Hand‑editing multiple Bicep files soon becomes error‑prone and painful.

### 1.2 The quota‑failure pain‑point

Azure quotas are enforced *per‑subscription → per‑region → per‑resource‑type*.
If any single resource in a deployment exceeds quota, the entire ARM request fails (`InvalidTemplateDeployment`, `SkuNotAvailable`, etc.). CI minutes and developer attention are wasted.

Microsoft recently GA’d the **Microsoft.Quota** REST API, but there is still no turnkey workflow that:

1. Checks **all** requested services ahead of time.
2. Computes the **intersection** of regions that satisfy every quota.
3. Generates IaC templates automatically.

This specification pairs a **YAML service manifest** with a **generator** that emits ready‑to‑deploy Bicep, plus a **quota checker** that selects a safe region *before* ARM validation.

---

## 2 Design Goals

| Goal                                               | Rationale                                                                                            |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Declarative service list in YAML**               | Separate intent (services, SKUs, required capacity) from generated IaC; easier code review and diff. |
| **Automatic region selection**                     | Removes human trial‑and‑error when quotas are exhausted.                                             |
| **Quota pre‑check before any ARM/Bicep call**      | Fails fast in the CLI, saving CI time.                                                               |
| **One‑shot generation of Bicep + parameter files** | After the region is chosen the pipeline is identical to traditional Bicep workflows.                 |
| **Extensible schema**                              | Adding a new Azure service requires only a new YAML stanza—no generator code changes.                |

---

## 3 YAML Configuration Schema (v0.2)

The schema generalises the resource‑specific manifest used in the **AI‑Starter Azure‑Stack** example and can express *any* Azure workload.

```yaml
# infra.yaml  —  schema v0.2

metadata:
  name: ai-stack
  description: Declarative manifest of Azure resources to deploy.
  version: 0.2.0

subscription: 00000000-0000-0000-0000-000000000000   # optional override

resourceGroup:
  name: demo-rg
  region: ""                # inherits .region unless explicitly set

# Region‑selection behaviour
region: ""                     # blank → quota workflow picks one
allowedRegions: []             # optional whitelist

deployment:
  rollback: lastSuccessful   # options: none | lastSuccessful | named:<deploymentName>  

# Global tags applied to every resource
tags:
  environment: dev

# Default Key Vault used for secretRef indirection (optional)
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
    # inherits the manifest .region unless you add `region:` here
    sku: Standard_B1ms
    capacity:
      unit: vCores               # must match Quota API `name.value`
      required: 2
    secrets:
      adminPassword: pgAdminPassword
    properties:
      version: 16
      storageGB: 32

  # Container Apps Environment
  - name: api-env
    type: Microsoft.App/managedEnvironments
    region: eastus             # runs in a separate region
    sku: Consumption
    capacity:
      unit: Cores
      required: 4
    skipQuotaCheck: false

  # Log Analytics Workspace
  - name: log-analytics
    type: Microsoft.OperationalInsights/workspaces
    sku: PerGB2018
    capacity: null
```

**Region evaluation rules**

* Every service **must have an effective region**:
   • If it declares `region:` → use that value.
   • Else inherit the manifest‑level `region`.
* The quota algorithm evaluates each service **in its own effective region**.  For services that share the manifest‑level region, their quotas are intersected to find a common viable region.  Split‑region stacks therefore work while still guaranteeing quota coverage.

**Secret handling**\*\* – Manifest stores **no plaintext secrets**.  Confidential values referenced by `secretRef` are supplied at deploy‑time via Key Vault *or* `main.parameters.json`. If a secret exists in **both** locations, Key Vault wins.

---

## 4 Quota Discovery Workflow

### 4.1 Prerequisites

* Azure CLI ≥ 2.54 with the **quota** extension (auto‑installs on first use).
* Logged‑in identity needs **Reader** at subscription scope to query quotas and **Contributor** to deploy.
* Bash + `jq`/`yq` *or* PowerShell 7.

### 4.2 Algorithm

1. **Parse** manifest; compute each service’s **effectiveRegion** (its `region`if present, otherwise manifest `region`). Collect tuples `(provider, capacity, effectiveRegion)` for all services except those with `skipQuotaCheck: true`.
2. **Enumerate** candidate regions:
     • For services with a dedicated `region`, that single region is used.
     • For shared‑region services, start with GA regions and intersect with `allowedRegions`.
3. **Fetch** quota & usage via CLI or REST for each provider + region. A reference table of common `capacity.unit` strings is available in Appendix A.
4. **Evaluate** `sufficient = (limit - usage) ≥ required` per unit.
5. **Intersect** passing region sets; if none remain → exit **code 2** and emit `region-analysis.json` summary for CI.
6. **Prompt** user (or use `--auto-select`) to choose one region; persist to manifest.
7. **Emit** `region-analysis.json` (machine‑readable) and continue to generation.

**Exit codes**
\* 0 = quota OK & region chosen   |  1 = fatal parsing error   |  2 = no region satisfies quota

### 4.3 Edge Cases

| Scenario                         | Handling                                                   |
| -------------------------------- | ---------------------------------------------------------- |
| Service has `capacity: null`     | Always passes quota check.                                 |
| `skipQuotaCheck: true`           | Service excluded from algorithm; user accepts risk.        |
| YAML already specifies `region:` | Quota workflow bypassed entirely.                          |
| Multi‑unit SKUs (GPU + vCPU)     | Accept **array** under `capacity:`; *all* units must pass. |

---

## 5 Bicep Generation Strategy

### 5.1 Template Layout

```
/templates
  common/rg.bicep
  modules/
    <one‑module‑per‑resource‑type>.bicep
    default.bicep   # generic fallback for unknown types
```

### 5.2 Generator Behaviour

* Reads manifest → variables & services.
* For any resource type without a bespoke module, the **`default.bicep`** template is instantiated, using `existing` keyword and dynamic properties.  A warning is logged for maintainers.
* Generated deployment is **idempotent & incremental** (ARM default).  Existing resources are updated in‑place; removals require an explicit `--destroy` flag (see §6). If `--prune` is **not** supplied, the generator detects resources present in Azure but missing from the manifest and prints a **warning list of orphan resources** so operators can review or rerun with `--prune`.

### 5.3 Key Vault bootstrap

If `keyVault` points to a non‑existent vault, the generator creates one with:
\* Soft‑delete = true, purge‑protection = true.
\* Access‑policy for the deployment’s managed identity (Get/List secrets).
\* Policy entries for each service identity that declares `secrets:`.

### 5.4 Versioning & Schema Migration

The manifest follows **SemVer**.  The generator can read the current major version (`0.x`).  A future **v1.0** release will provide a `manifest upgrade` command that writes a migrated file and a diff report.

---

## 6 Lifecycle Commands

| Command          | Behaviour                                                                                                                                                                                     |                                                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `quota‑check`    | Runs algorithm (§4) and writes `region-analysis.json`.                                                                                                                                        |                                                                                                                   |
| `generate`       | Converts manifest → `main.bicep` + `main.parameters.json`.                                                                                                                                    |                                                                                                                   |
| `deploy`         | Runs ARM deployment (incremental). Passes `--rollback-on-error` when `deployment.rollback` is set (default `lastSuccessful`). Emits warnings for orphan resources when run without `--prune`. |                                                                                                                   |
| `deploy --prune` | Incremental deploy plus deletion of resources no longer present in the manifest (see §Deletion / Prune Workflow).                                                                             | Incremental deploy plus deletion of resources no longer present in the manifest (see §Deletion / Prune Workflow). |
| `destroy`        | Deletes all resources in manifest order, then RG. Purge‑protection handling is out of scope for this proof of concept.                                                                        |                                                                                                                   |

> **Concurrency** – Each command uses a deployment name derived from `metadata.name` to let ARM handle locking; parallel deployments to the **same** stack will serialize automatically.

---

## 7 CI/CD Pipeline Sketch (GitHub Actions)

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

      - name: Quota check / region selection
        run: |
          ./scripts/quota_check.sh --config infra.yaml --auto-select
          if [ $? -ne 0 ]; then cat region-analysis.json; exit 1; fi

      - name: Generate Bicep
        run: |
          npm ci
          node generate.js infra.yaml

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

## 8 Prior Art & Community Signals

* **Microsoft Quota API GA (2024‑Q3)** – Compute, Networking, Storage, AKS, ML, Purview, HPC Cache.
* **`az quota`**\*\* CLI extension\*\* – REST parity yet still under‑used.
* **Microsoft content‑processing‑solution‑accelerator** – Source of the region‑intersection idea.
* **Terraform ************************`azurerm`************************ #14969** – Plan‑time quota validation discussion.

---

## 9 Outstanding Issues & Resolutions

| #  | Issue                                         | Status                                                                                                                                                                                                        |   |
| -- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | - |
| 1  | Clarify inheritance rules for `location`.     | ~~Resolved – resource‑level \~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\\\~\~\~\~`location`\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~ overrides manifest region and is quota‑checked independently (see §3, §4).~~ |   |
| 2  | Provide authoritative capacity‑unit map.      | *Partially resolved* – Appendix A lists common units; exhaustive list pending Microsoft doc link.                                                                                                             |   |
| 3  | Define `skipQuotaCheck` semantics.            | ~~Resolved – field added to schema & algorithm.~~                                                                                                                                                             |   |
| 4  | Error‑handling contract (exit codes, JSON).   | ~~Resolved – see §4 (exit codes & \~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\\\~\~\~\~`region-analysis.json`\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~\~).~~                                                        |   |
| 5  | Idempotent update vs re‑create strategy.      | ~~Resolved – `deploy` now emits warnings for orphan resources when `--prune` is not used.~~                                                                                                                   |   |
| 6  | Deletion workflow (destroy).                  | ~~Resolved – `destroy` command defined; cross‑region handling declared out of scope for this proof of concept.~~                                                                                              |   |
| 7  | Schema‑version migration policy.              | ~~Resolved – SemVer & upgrade command in §5.4.~~                                                                                                                                                              |   |
| 8  | Key Vault bootstrap & policies.               | ~~Resolved – §5.3 defines behaviour.~~                                                                                                                                                                        |   |
| 9  | Secret injection precedence rules.            | ~~Resolved – paragraph in §3 Secret handling.~~                                                                                                                                                               |   |
| 10 | Multi‑subscription support.                   | **Open** – design TBD.                                                                                                                                                                                        |   |
| 11 | Plug‑in mechanism for unknown resource types. | *Partially resolved* – default.bicep fallback; need long‑term module strategy.                                                                                                                                |   |
| 12 | Cost / budget guardrails.                     | **Out of scope** – declared non‑goal.                                                                                                                                                                         |   |
| 13 | Concurrency / locking model.                  | ~~Resolved – ARM deployment names serialize.~~                                                                                                                                                                |   |
| 14 | Telemetry & audit logging.                    | **Open** – decide logging sink & retention.                                                                                                                                                                   |   |
| 15 | Rollback / compensation.                      | ~~Resolved – native ARM \~\~\~\~`--rollback-on-error`\~\~\~\~ enabled; controlled via \~\~\~\~`deployment.rollback`\~\~\~\~ manifest key.~~                                                                   |   |

---

## 10 Open Questions & Next Steps

| Area                   | Decision Needed                                                                             |   |                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------- | - | ------------------------------------------------------------------ |
| **Idempotent updates** | Should generator delete resources removed from manifest automatically?                      |   |                                                                    |
| **Destroy semantics**  | Confirm deletion order (manifest order). Cross‑region handling is out of scope for the PoC. |   | Confirm order & safety checks (KV purge‑protection, cross‑region). |
| **Multi‑subscription** | Allow `subscription:` per service or keep single‑subscription constraint?                   |   |                                                                    |
| **Module plug‑ins**    | Strategy for new resource types (auto‑gen vs curated modules).                              |   |                                                                    |
| **Telemetry / audit**  | Pick logging sink (LA, App Insights) & schema for quota‑check outcomes.                     |   |                                                                    |
| **Rollback model**     | Decide whether to rely on ARM incremental nature or add custom rollback logic.              |   |                                                                    |

---

### Take‑away

Externalising **what** you need (YAML) from **how** Azure materialises it (generated Bicep) and inserting a **quota‑aware region‑selection** step removes the main source of first‑deploy failure in Azure CI/CD. The refined spec now includes clear inheritance rules, secret precedence, exit codes, KV bootstrap, and schema‑versioning—while highlighting the remaining open decisions that need product‑owner input.

---

### Appendix A – Common Quota Capacity Units

| Provider                                   | Common `capacity.unit` strings |
| ------------------------------------------ | ------------------------------ |
| Microsoft.DBforPostgreSQL                  | `vCores`, `Servers`            |
| Microsoft.App (Container Apps)             | `Cores`, `MemoryGB`            |
| Microsoft.Web (App Service / Static Sites) | *None* (quota‑free)            |
| Microsoft.OperationalInsights              | *None* (quota‑free)            |
| Microsoft.Compute (VMs)                    | `StandardDSv5Family`, etc.     |

*See ************[https://learn.microsoft.com/azure/quota/reference](https://learn.microsoft.com/azure/quota/reference)************ for the authoritative, up‑to‑date list.*
