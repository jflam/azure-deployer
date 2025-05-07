// Base Bicep template for Azure Provisioner
targetScope = 'subscription'

// Common parameters
param location string
param resourceGroupName string
param tags object = {}

// Secure parameters
@secure()
param postgresAdminPassword string

// Create resource group
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

// Output resource group name for module scoping
output rgName string = rg.name

// Service resources
resource log-analytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'log-analytics'
  location: ''
  sku: {
    name: 'PerGB2018'
  }
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
  tags: {
    environment: 'dev'
  }
}

output log-analyticsId string = log-analytics.id
output log-analyticsCustomerId string = log-analytics.properties.customerId
output log-analyticsPrimarySharedKey string = listKeys(log-analytics.id).primarySharedKey

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01' = {
  name: 'postgres'
  location: ''
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: False
    }
    administratorLogin: 'pgadmin'
    administratorLoginPassword: postgresAdminPassword
  }
  tags: {
    environment: 'dev'
  }
}

output postgresFqdn string = postgres.properties.fullyQualifiedDomainName
output postgresConnectionString string = 'postgresql://${postgres.properties.administratorLogin}:${passwordToEscape}@${postgres.properties.fullyQualifiedDomainName}:5432/postgres?sslmode=require'

resource api-env 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: 'api-env'
  location: ''
  sku: {
    name: 'Consumption'
  }
  properties: {
    zoneRedundant: false
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: log-analytics.properties.customerId
        sharedKey: listKeys(log-analytics.id).primarySharedKey
      }
    }
  }
  tags: {
    environment: 'dev'
  }
  dependsOn: [
    log-analytics
  ]
}

output api-envId string = api-env.id
output api-envDefaultDomain string = api-env.properties.defaultDomain

resource static-web 'Microsoft.Web/staticSites@2023-01-01' = {
  name: 'static-web'
  location: ''
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  tags: {
    environment: 'dev'
    app: 'ai-starter'
  }
}

output static-webUrl string = static-web.properties.defaultHostname

