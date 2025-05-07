// Base Bicep template for Azure Provisioner
targetScope = 'subscription'

// Common parameters
param location string
param resourceGroupName string
param tags object = {}

{% if secrets %}
// Secure parameters
{% for secret in secrets %}
@secure()
param {{ secret }} string
{% endfor %}
{% endif %}

// Create resource group
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

// Deploy a nested template to the resource group
module resources 'resources.bicep' = {
  name: 'resourcesDeployment'
  scope: resourceGroup(resourceGroupName)
  params: {
    location: location
    tags: tags
{% if secrets %}
{% for secret in secrets %}
    {{ secret }}: {{ secret }}
{% endfor %}
{% endif %}
  }
}

// Forward outputs from the nested module
output rgName string = rg.name

// Forward key outputs from resources deployment
output log_analytics_id string = resources.outputs.log_analytics_id
output postgres_fqdn string = resources.outputs.postgres_fqdn
output api_env_id string = resources.outputs.api_env_id
output static_web_url string = resources.outputs.static_web_url