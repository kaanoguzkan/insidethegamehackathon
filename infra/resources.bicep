targetScope = 'resourceGroup'

param environmentName string
param location string
param tags object
param brainImage string
param foundryProjectEndpoint string
param modelName string

var token = toLower(uniqueString(subscription().id, environmentName))
var prefix = take(replace(environmentName, '-', ''), 10)

// ---------------------------------------------------------------- identity and observability

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${environmentName}'
  location: location
  tags: tags
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${environmentName}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    features: { disableLocalAuth: false }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${environmentName}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

// ---------------------------------------------------------------- storage

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take('st${prefix}${token}', 24)
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in ['replays', 'frames']: {
  parent: blobs
  name: c
  properties: { publicAccess: 'None' }
}]

resource queues 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource momentQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queues
  name: 'moments'
}

// ---------------------------------------------------------------- cosmos db (free tier)

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: 'cosmos-${environmentName}-${take(token, 6)}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: true // one per subscription; the account must be created with it
    disableLocalAuth: true // identity only, no keys
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0, isZoneRedundant: false } ]
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'matchmind'
  properties: {
    resource: { id: 'matchmind' }
    options: { throughput: 1000 } // shared across containers: the free tier's allowance
  }
}

var cosmosContainers = [
  { name: 'matches', pk: '/matchId' }
  { name: 'events', pk: '/matchId' }
  { name: 'state', pk: '/matchId' }
  { name: 'moments', pk: '/matchId' }
  { name: 'overlays', pk: '/matchId' }
  { name: 'profiles', pk: '/profileId' }
  { name: 'players', pk: '/clubId' }
  { name: 'leases', pk: '/id' }
]

resource cosmosContainerResources 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [for c in cosmosContainers: {
  parent: db
  name: c.name
  properties: {
    resource: {
      id: c.name
      partitionKey: { paths: [ c.pk ], kind: 'Hash' }
      defaultTtl: c.name == 'events' ? 604800 : -1 // demo matches expire after a week
      indexingPolicy: c.name == 'state' ? { indexingMode: 'none', automatic: false } : { indexingMode: 'consistent' }
    }
  }
}]

// Cosmos DB data-plane role: built-in "Cosmos DB Built-in Data Contributor".
resource cosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, 'data-contributor')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: identity.properties.principalId
    scope: cosmos.id
  }
}

// ---------------------------------------------------------------- key vault

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('kv-${prefix}-${token}', 24)
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

// ---------------------------------------------------------------- signalr (free)

resource signalr 'Microsoft.SignalRService/signalR@2023-02-01' = {
  name: 'sigr-${environmentName}-${take(token, 6)}'
  location: location
  tags: tags
  sku: { name: 'Free_F1', capacity: 1 }
  properties: {
    features: [ { flag: 'ServiceMode', value: 'Serverless' } ]
    disableLocalAuth: true
  }
}

// ---------------------------------------------------------------- role assignments for the identity

var roles = {
  storageBlob: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' // Storage Blob Data Contributor
  storageQueue: '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // Storage Queue Data Contributor
  keyVaultSecrets: '4633458b-17de-408a-b874-0f2e9d3e7d4e' // Key Vault Secrets User
  signalr: '8cf5e20a-e4b2-4e9d-b3a1-5ceb692c2761' // SignalR Service Owner
}

resource roleBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, roles.storageBlob)
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlob)
  }
}

resource roleQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, roles.storageQueue)
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageQueue)
  }
}

resource roleVault 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, roles.keyVaultSecrets)
  scope: vault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecrets)
  }
}

resource roleSignalr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(signalr.id, identity.id, roles.signalr)
  scope: signalr
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.signalr)
  }
}

// ---------------------------------------------------------------- the Brain (Container Apps)

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${environmentName}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource brain 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${environmentName}-brain'
  location: location
  tags: union(tags, { 'azd-service-name': 'brain' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto', allowInsecure: false }
    }
    template: {
      containers: [
        {
          name: 'brain'
          image: brainImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'MATCHMIND_LLM', value: empty(foundryProjectEndpoint) ? 'offline' : 'foundry' }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'MATCHMIND_LLM_MODEL', value: modelName }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'STORAGE_ACCOUNT', value: storage.name }
            { name: 'SIGNALR_ENDPOINT', value: 'https://${signalr.properties.hostName}' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
            { name: 'MATCHMIND_DATA', value: '/app/data' }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/health', port: 8000 }, initialDelaySeconds: 10, periodSeconds: 30 }
          ]
        }
      ]
      // Scales to zero when idle; at most 2 replicas as a cost guard.
      scale: {
        minReplicas: 0
        maxReplicas: 2
        rules: [ { name: 'http', http: { metadata: { concurrentRequests: '20' } } } ]
      }
    }
  }
}

// ---------------------------------------------------------------- the web app

resource web 'Microsoft.Web/staticSites@2023-12-01' = {
  name: 'swa-${environmentName}'
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}

output brainUri string = 'https://${brain.properties.configuration.ingress.fqdn}'
output webUri string = 'https://${web.properties.defaultHostname}'
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output storageAccount string = storage.name
output keyVault string = vault.name
