
### 1. Azure Database for PostgreSQL – Flexible Server

**Why `quota_usages` isn’t there**
The RDBMS management SDKs ( `azure-mgmt-rdbms.*` ) still expose only “classical” server, DB, firewall, etc. operations. Quota/usage for Flexible Server never made it into that client – the platform team surfaced it only through a small, resource-specific REST slice.

* REST path (preview today, but the only door that exists):

````
GET /subscriptions/{subId}/providers/Microsoft.DBforPostgreSQL
     /locations/{location}/resourceType/flexibleServers/usages
     ?api-version=2024-11-01-preview
``` :contentReference[oaicite:0]{index=0}  

The response gives you an array of `{name: {value}, currentValue, limit}` objects for vCores, storage, servers-per-sub, etc.  

**What to call instead**  
```python
from azure.identity import DefaultAzureCredential
import requests

cred = DefaultAzureCredential()
token = cred.get_token("https://management.azure.com/.default").token

url = (f"https://management.azure.com/subscriptions/{sub_id}"
       f"/providers/Microsoft.DBforPostgreSQL/locations/{location}"
       f"/resourceType/flexibleServers/usages"
       f"?api-version=2024-11-01-preview")

r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
r.raise_for_status()
for item in r.json()["value"]:
    print(item["name"]["value"], item["currentValue"], "/", item["limit"])
````

There is no convenience wrapper yet; a raw REST call (or `azure.core.rest`) is the only path.

---

### 2. Azure Container Apps ( `Microsoft.App/managedEnvironments` )

**Two different quota surfaces**

| Scope                       | API that exists                                                                                                                                                                                 | What it tells you                                                                                                |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **Subscription / Region**   | `GET /subscriptions/{subId}/providers/Microsoft.App/locations/{location}/usages?api-version=2025-01-01` ([Microsoft Learn][1])                                                                  | Total CPUs, memory, environments count, jobs, etc. across the subscription in that region.                       |
| **Per managed environment** | `GET /subscriptions/{subId}/resourceGroups/{rg}/providers/Microsoft.App/managedEnvironments/{env}/usages?api-version=2025-01-01` ( surfaced in the SDK as `managed_environment_usages.list()` ) | Quota & usage **inside** one Container Apps environment (cores, active apps, revisions, concurrent requests, …). |

**Correct Python client**

```python
from azure.identity import DefaultAzureCredential
from azure.mgmt.appcontainers import ContainerAppsAPIClient   # NOTE the *API* is all-caps

cred = DefaultAzureCredential()
client = ContainerAppsAPIClient(credential=cred, subscription_id=sub_id)

# 2a – regional subscription-wide usage
for u in client.usages.list(location):
    print(u.name.value, u.current_value, "/", u.limit)

# 2b – per-environment usage
for u in client.managed_environment_usages.list(rg, env_name):
    print(u.name.value, u.current_value, "/", u.limit)
```

*Make sure you’re on `azure-mgmt-appcontainers >= 3.2.0` (2025-04-20 release) – older builds didn’t have the `ContainerAppsAPIClient` class, which is why the import failed.* ([PyPI][2], [GitHub][3])

---

### Why the Quota Service ( `Microsoft.Quota/*` ) doesn’t help here

The general Quota API only covers a subset of providers (Compute, ML, Storage, Networking, Purview, etc.) ([Microsoft Learn][4]). Postgres Flexible Server and Container Apps quotas are still managed by their own resource providers.

---

#### Quick fixes for your script

* Replace the hallucinated `client.quota_usages…` call with the REST snippet shown above for Postgres.
* Pin `azure-mgmt-appcontainers` ≥ 3.2.0 and import **`ContainerAppsAPIClient`** (exact case).
* Call `.usages.list(location)` or `.managed_environment_usages.list(rg, env)` instead of trying to import a non-existent `ContainerAppsApiClient`.

With those two adjustments the quota checks will stop erroring out.

[1]: https://learn.microsoft.com/en-us/dotnet/api/azure.resourcemanager.resources.subscriptionresource?view=azure-dotnet&utm_source=chatgpt.com "SubscriptionResource Class (Azure.ResourceManager.Resources)"
[2]: https://pypi.org/project/azure-mgmt-appcontainers/?utm_source=chatgpt.com "azure-mgmt-appcontainers - PyPI"
[3]: https://github.com/MicrosoftDocs/azure-docs-sdk-python/blob/main/docs-ref-autogen/azure-mgmt-appcontainers/azure.mgmt.appcontainers.operations.UsagesOperations.yml?utm_source=chatgpt.com "azure.mgmt.appcontainers.operations.UsagesOperations.yml - GitHub"
[4]: https://learn.microsoft.com/en-us/rest/api/quota/?utm_source=chatgpt.com "Azure Quota Service REST API | Microsoft Learn"
