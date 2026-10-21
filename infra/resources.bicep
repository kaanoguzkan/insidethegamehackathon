targetScope = 'resourceGroup'

param environmentName string
param location string
param webLocation string
param appsLocation string
param tags object
param brainImage string
param foundryProjectEndpoint string
param modelName string
param corsOrigins string
param agentsMode string
param appInsightsConnectionString string
@secure()
param adminKey string
@secure()
param liveKey string

// Container Apps capacity differs by region and by subscription; the apps can sit in another region from the data.
var appsRegion = empty(appsLocation) ? location : appsLocation
var token = toLower(uniqueString(subscription().id, environmentName))
var prefix = take(replace(environmentName, '-', ''), 10)

// ---------------------------------------------------------------- identity and observability

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${environmentName}'
  location: location
  tags: tags
}

// The image registry the Brain's image is built into (azd builds remotely and pushes here). Basic is the cheapest SKU.
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'cr${prefix}${take(token, 8)}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${environmentName}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    // A cap, so that verbose logs can never turn into a bill: ingestion stops for the day at 0.5 GB (normal use is a few MB).
    workspaceCapping: { dailyQuotaGb: json('0.5') }
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

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in ['replays', 'frames', 'checkpoints', 'packs', 'deployments']: {
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
  { name: 'beats', pk: '/matchId' } // the Brain's shared cache of verified model text (documents expire by their own ttl)
  { name: 'profiles', pk: '/profileId' }
  { name: 'players', pk: '/clubId' }
  { name: 'leases', pk: '/id' }
  { name: 'season', pk: '/seasonId' } // the season's fixtures and results (live/season.py)
]

resource cosmosContainerResources 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [for c in cosmosContainers: {
  parent: db
  name: c.name
  properties: {
    resource: {
      id: c.name
      partitionKey: { paths: [ c.pk ], kind: 'Hash' }
      defaultTtl: c.name == 'events' ? 604800 : -1 // demo events expire after a week
      indexingPolicy: { indexingMode: 'consistent' }
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
  signalr: '7e4f1700-ea5a-4f59-8f37-079cfe29dce3' // SignalR Service Owner (the data-plane role: generate client tokens, send messages). 8cf5e20a-... is the management-plane Contributor, which is not enough
  storageBlobOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b' // Storage Blob Data Owner (the Functions host keeps its leases in blobs)
  storageTable: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3' // Storage Table Data Contributor
  contributor: 'b24988ac-6180-42a0-ab88-20f7382dd24c' // Contributor, scoped to the simulator job only
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

resource roleBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, roles.storageBlobOwner)
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobOwner)
  }
}

resource roleTable 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, roles.storageTable)
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageTable)
  }
}

// The vault is provisioned for secrets the app will need (a model key, if one is ever used instead of identity),
// but nothing reads it yet. Add the "Key Vault Secrets User" role (4633458b-17de-408a-b874-0f2e9d3e7d4e) for the
// identity when something does: ARM refused that role in a brand-new subscription on the first deployments.

resource rolePull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'acrpull')
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') // AcrPull
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
  location: appsRegion
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

// The Brain's public name is its app name plus the environment's default domain, known before the app exists.
var brainName = 'ca-${environmentName}-brain'
var brainHost = '${brainName}.${env.properties.defaultDomain}'

resource brain 'Microsoft.App/containerApps@2024-03-01' = {
  dependsOn: [ rolePull ] // the identity must be allowed to pull before the app is created
  name: brainName
  location: appsRegion
  tags: union(tags, { 'azd-service-name': 'brain' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 8000, transport: 'auto', allowInsecure: false }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
      secrets: concat(empty(adminKey) ? [] : [ { name: 'admin-key', value: adminKey } ], empty(liveKey) ? [] : [ { name: 'live-key', value: liveKey } ])
    }
    template: {
      containers: [
        {
          name: 'brain'
          image: brainImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: concat([
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'MATCHMIND_LLM', value: empty(foundryProjectEndpoint) ? 'offline' : 'foundry' }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'MATCHMIND_LLM_MODEL', value: modelName }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'MATCHMIND_PRELOAD', value: '1' } // load the matches the MCP tools use in the background after start-up
            { name: 'MATCHMIND_SHARED_CACHE', value: '1' } // verified model text is also kept in Cosmos DB: it survives restarts and is shared
            { name: 'STORAGE_ACCOUNT', value: storage.name }
            { name: 'SIGNALR_ENDPOINT', value: 'https://${signalr.properties.hostName}' }
            // Traces go to the Foundry project's own Application Insights when given, so they appear in the Foundry portal's tracing view.
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: empty(appInsightsConnectionString) ? insights.properties.ConnectionString : appInsightsConnectionString }
            { name: 'MATCHMIND_DATA', value: '/app/data' }
            { name: 'MATCHMIND_ALLOWED_HOSTS', value: brainHost } // MCP's DNS-rebinding guard answers to this name
            { name: 'MATCHMIND_ALLOWED_ORIGINS', value: 'https://${web.properties.defaultHostname}' }
            { name: 'MATCHMIND_AGENTS', value: agentsMode } // 'foundry': call the agents registered in the Foundry project
            { name: 'MATCHMIND_CORS_ORIGINS', value: corsOrigins } // other sites that call the API from the browser (GitHub Pages)
            { name: 'MATCHMIND_AGENT_TIMEOUT_S', value: '30' } // a model call may use up to this long, never more than the request has left
            { name: 'MATCHMIND_BEAT_BUDGET_S', value: '90' } // the five-agent workflow (mode "full") needs far more than the 15 s default
            { name: 'SEASON_JOB_ID', value: seasonJob.id } // the job that simulates a season, several replicas at once
            { name: 'LIVE_JOB_ID', value: simJob.id } // the simulator job the "start a live match" endpoint runs
            { name: 'LIVE_PUSH_URL', value: 'https://${funcApp.properties.defaultHostName}/api' } // where browsers connect for SignalR pushes (the negotiate Function)
            { name: 'LIVE_SPEED', value: '5' } // match seconds per real second: a 15 s model call is then a 75 s delay in match time, so keep it low
          ], concat(empty(adminKey) ? [] : [ { name: 'MATCHMIND_ADMIN_KEY', secretRef: 'admin-key' } ], empty(liveKey) ? [] : [ { name: 'MATCHMIND_LIVE_KEY', secretRef: 'live-key' } ]))
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

// ---------------------------------------------------------------- the live pipeline: simulator job and Functions

// The simulator plays a demo match as a live feed into Cosmos DB. It runs the Brain's image with another command; the image is updated after each
// `azd deploy` by the postdeploy hook in azure.yaml (this template only knows the placeholder).
resource simJob 'Microsoft.App/jobs@2024-03-01' = {
  dependsOn: [ rolePull ]
  name: 'caj-${environmentName}-sim'
  location: appsRegion
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 7200
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
    }
    template: {
      containers: [
        {
          name: 'simulator'
          image: brainImage
          command: [ 'python', '-m', 'matchmind.live.simulator' ]
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'STORAGE_ACCOUNT', value: storage.name }
            { name: 'MATCHMIND_DATA', value: '/app/data' }
          ]
        }
      ]
    }
  }
}

// The season job: several replicas at once, each claiming fixtures (simulate, store the match pack, record the result) until none is left.
resource seasonJob 'Microsoft.App/jobs@2024-03-01' = {
  dependsOn: [ rolePull ]
  name: 'caj-${environmentName}-season'
  location: appsRegion
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 5, replicaCompletionCount: 5 }
      registries: [ { server: registry.properties.loginServer, identity: identity.id } ]
    }
    template: {
      containers: [
        {
          name: 'season'
          image: brainImage
          command: [ 'python', '-m', 'matchmind.live.season_job' ]
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'STORAGE_ACCOUNT', value: storage.name }
            { name: 'MATCHMIND_DATA', value: '/app/data' }
          ]
        }
      ]
    }
  }
}

resource roleStartSeasonJob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(seasonJob.id, identity.id, roles.contributor)
  scope: seasonJob
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
  }
}

// The Brain starts the job with its own identity: Contributor on this one resource and nothing else.
resource roleStartJob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(simJob.id, identity.id, roles.contributor)
  scope: simJob
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
  }
}

// Two Cosmos DB change-feed triggers on the Flex Consumption plan (scales to zero, a free monthly grant): interpret the feed, dispatch moments to the Brain.
resource funcPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-${environmentName}-func'
  location: appsRegion
  tags: tags
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource funcApp 'Microsoft.Web/sites@2023-12-01' = {
  dependsOn: [ roleBlob, roleBlobOwner, roleQueue, roleTable ]
  name: 'func-${environmentName}-${take(token, 6)}'
  location: appsRegion
  tags: union(tags, { 'azd-service-name': 'functions' })
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    serverFarmId: funcPlan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}deployments'
          authentication: { type: 'UserAssignedIdentity', userAssignedIdentityResourceId: identity.id }
        }
      }
      scaleAndConcurrency: { maximumInstanceCount: 4, instanceMemoryMB: 2048 }
      runtime: { name: 'python', version: '3.12' }
    }
    siteConfig: {
      cors: { allowedOrigins: concat([ 'https://${web.properties.defaultHostname}', 'http://localhost:5173', 'http://localhost:4173' ], empty(corsOrigins) ? [] : split(corsOrigins, ',')) }
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'AzureWebJobsStorage__clientId', value: identity.properties.clientId }
        { name: 'AzureSignalRConnectionString__serviceUri', value: 'https://${signalr.properties.hostName}' }
        { name: 'AzureSignalRConnectionString__credential', value: 'managedidentity' }
        { name: 'AzureSignalRConnectionString__clientId', value: identity.properties.clientId }
        { name: 'COSMOS__accountEndpoint', value: cosmos.properties.documentEndpoint }
        { name: 'COSMOS__credential', value: 'managedidentity' }
        { name: 'COSMOS__clientId', value: identity.properties.clientId }
        { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
        { name: 'STORAGE_ACCOUNT', value: storage.name }
        { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
        { name: 'BRAIN_URL', value: 'https://${brainHost}' }
        { name: 'MATCHMIND_LIVE_KEY', value: liveKey }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
      ]
    }
  }
}

// Every blob created in the storage account raises an Event Grid event; the subscription that routes the tracking chunks to the `analyze` Function is created
// after the Function is deployed (the postdeploy hook in azure.yaml: a Function endpoint has to exist before it can be subscribed to).
resource storageEvents 'Microsoft.EventGrid/systemTopics@2022-06-15' = {
  name: 'evgt-${environmentName}-storage'
  location: location
  tags: tags
  properties: {
    source: storage.id
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

// ---------------------------------------------------------------- the web app

resource web 'Microsoft.Web/staticSites@2023-12-01' = {
  name: 'swa-${environmentName}'
  location: webLocation
  tags: union(tags, { 'azd-service-name': 'web' })
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}

output registryEndpoint string = registry.properties.loginServer
output brainUri string = 'https://${brain.properties.configuration.ingress.fqdn}'
output webUri string = 'https://${web.properties.defaultHostname}'
output simulatorJob string = simJob.name
output seasonJob string = seasonJob.name
output functionApp string = funcApp.name
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output storageAccount string = storage.name
output keyVault string = vault.name
