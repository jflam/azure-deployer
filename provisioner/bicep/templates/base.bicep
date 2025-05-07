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

// Output resource group name for module scoping
output rgName string = rg.name

// Service resources
{% for resource in resources %}
{{ resource }}

{% endfor %}