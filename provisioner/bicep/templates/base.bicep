// Base Bicep template for Azure Provisioner
targetScope = 'subscription'

// Parameters
param location string
param resourceGroupName string
param tags object = {}

// Create resource group
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

// Output resource group name for module scoping
output rgName string = rg.name