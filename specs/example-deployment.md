# AI‑Starter Azure Stack – Deployment Specification

## 1  Purpose

This document defines the infrastructure required to host the **AI‑Starter** web application.  It is meant for:

\* Cloud engineers – to generate Bicep/ARM templates and deploy the stack
\* Security & compliance reviewers – to understand resource boundaries and secret‑handling practice
\* Developers – to know which Azure services are available and where to inject configuration

The design prioritises **security‑by‑default** (all secrets in Key Vault), maximises **portability** (single YAML schema feeds IaC generation), and supports **quota‑aware** region overrides for PostgreSQL.

---

## 2  High‑Level Architecture

* **Static Web App** – serves React front‑end over global edge
* **Container Apps** – runs Express API in a managed environment
* **Azure Container Registry (ACR)** – optional; created automatically if `existingAcr` is omitted
* **PostgreSQL Flexible Server** – primary relational datastore
* **Azure Key Vault** – centralised secret store; referenced by service‑to‑service identities
* **Log Analytics Workspace** – central log sink for Container Apps and diagnostics

> **Secret handling:** No plaintext secrets exist in source control.  All sensitive material is uploaded to Key Vault (or pipeline secret store) and referenced using `secretRef` tokens inside the schema below.

---

## 3  Declarative Configuration Schema

The YAML schema is version‑controlled and feeds a generator that produces Bicep templates.  **Do not** store real secrets in this file.

```yaml
# deployment-config-schema.yaml (v1.1.0)
# Declarative configuration schema for an Azure stack consisting of:
#   • Static Web App
#   • Container Apps (with optional ACR)
#   • PostgreSQL Flexible Server
#   • Key Vault
#   • Log Analytics Workspace
#
# NOTE — **No raw secrets live in this file.**
# Secret material (passwords, connection strings, certificates, etc.)
# must be injected at deployment time via:
#   • Azure Key Vault references
#   • CI/CD pipeline variable groups or secret files excluded from VCS
#   • `az deployment group create --parameters @secure-params.json`
# The schema below only carries *pointers* (secretRef) to where secrets
# will be found.  This keeps the configuration repo safe for review.

metadata:
  name: ai-starter-stack              # Logical stack name
  description: Static web + API + Postgres + KV + monitoring
  version: 1.1.0
  location: westus2                   # Default Azure region for resources

resourceGroup:
  name: ai-starter-rg
  location: westus2                   # Can differ from metadata.location

staticWebApp:
  name: ai-starter-web
  sku: Free                           # Free | Standard | Standard-2 | etc.
  location: westus2

postgres:
  name: ai-starter-pg
  location: eastus2                   # Override if quota issues arise
  version: 16
  sku:
    tier: Burstable                   # Burstable | GeneralPurpose | MemoryOptimized
    name: Standard_B1ms
  storageGB: 32
  availabilityZone: "1"              # "1" | "2" | "3" or empty for no AZ
  backup:
    retentionDays: 7
    geoRedundant: false
  admin:
    username: pgadmin
    secretRef: pgAdminPassword        # Name of Key Vault secret (value not here)
  database:
    name: ai_app
    charset: UTF8
    collation: en_US.UTF8
  firewallRules:
    - name: AllowAzureServices
      startIp: 0.0.0.0
      endIp: 0.0.0.0

containerApps:
  environment:
    name: ai-starter-env
    location: westus2
  registry:
    existingAcr: ""                  # If blank, generator will create one
    sku: Basic
  apps:
    - name: api
      image: api:latest               # Resolved against ACR login server
      cpu: 0.5
      memory: 1Gi
      ingress:
        external: true
        targetPort: 4000
        cors:
          allowedOrigins: ["*"]
      replicas:
        min: 1
        max: 1
      env:
        - name: DATABASE_URL
          secretRef: database-url     # Key Vault secret; not stored here
        - name: PORT
          value: "4000"

keyVault:
  name: ai-starter-kv
  location: westus2
  sku: standard                       # standard | premium
  softDelete: true
  purgeProtection: true
  accessPolicies:
    - principal: api                  # Friendly name matching container app
      permissions:
        secrets: ["get", "list"]

logAnalytics:
  name: ai-starter-law
  location: westus2
  sku: PerGB2018
  retentionDays: 30
  features:
    enableResourcePermissions: true
```

---

## 4  Deployment Workflow

1. **Parameterisation**
   *Create an* `secure-params.json` *file (excluded from Git) that supplies the actual secret values referenced in the schema.*  Example:

   ```json
   {
     "pgAdminPassword": {"value": "<super‑secret>"},
     "database-url":    {"value": "postgres://..."}
   }
   ```
2. **Generate IaC**
   `iac‑gen --schema deployment-config-schema.yaml --out main.bicep`
3. **Deploy**

   ```bash
   az deployment group create \
     --resource-group ai-starter-rg \
     --template-file main.bicep \
     --parameters @secure-params.json
   ```
4. **Post‑deployment validation**
   *ACR pull works?  API responds?  Log flow visible in Log Analytics?*

---

## 5  Security Notes

* All resources support **managed identities**; no shared connection strings outside Key Vault.
* The YAML schema stores **only non‑secret metadata** and Key Vault secret names.
* Key Vault access is restricted to the Container App’s system‑assigned identity.

---

## 6  Change Log

* **v1.1.0** – Removed inline `secrets:` section; replaced with Key Vault references and secure parameter file pattern.

---

End of specification.
