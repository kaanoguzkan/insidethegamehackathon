// MatchMind on Azure, sized for the free tier. `azd up` runs this at subscription scope.
//
// What it creates: Log Analytics + Application Insights, a user-assigned managed identity, Storage
// (replay packages, tracking chunks, work queue), Cosmos DB (free tier) with the containers the
// pipeline uses, Key Vault, Container Apps (the Brain, scales to zero), SignalR (free), a Static
// Web App for the UI and a cost budget with alerts. Everything authenticates with the managed
// identity: there are no keys in configuration.
//
// Not created here (you do these once in the portal, then pass the endpoint in):
//   - a Microsoft Foundry project and a model deployment (set foundryProjectEndpoint / modelName)
targetScope = 'subscription'

@minLength(1)
@maxLength(16)
@description('Short name used to derive resource names, e.g. "matchmind".')
param environmentName string

@description('Azure region for all resources.')
param location string

@description('Container image for the Brain. azd replaces it on deploy.')
param brainImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Microsoft Foundry project endpoint, e.g. https://<account>.services.ai.azure.com/api/projects/<project>. Empty keeps the offline model.')
param foundryProjectEndpoint string = ''

@description('Region for the Static Web App. It is served from a CDN and only exists in a few regions (West US 2, Central US, East US 2, West Europe, East Asia).')
param webLocation string = 'eastus2'

@description('Region for the Container Apps environment and the Brain. Empty means the same as location. Use it when the main region has no Container Apps capacity.')
param appsLocation string = ''

@description('Model deployment name in the Foundry project.')
param modelName string = ''

@description('Extra browser origins allowed to call the Brain API, comma separated (the GitHub Pages site).')
param corsOrigins string = ''

@description('Monthly budget in USD. Alerts fire at 25%, 50% and 90% of it.')
param budgetUsd int = 20

@description('Email address that receives budget alerts. Leave empty to skip creating the budget.')
param budgetContact string = ''

@description('Create the budget (needs permission at subscription scope).')
param createBudget bool = true

@description('First day of the budget period. utcNow is only allowed as a parameter default.')
param budgetStartDate string = '${utcNow('yyyy-MM')}-01'

var budgetContacts = empty(budgetContact) ? [] : [budgetContact]
var tags = { 'azd-env-name': environmentName, app: 'matchmind' }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    webLocation: webLocation
    appsLocation: appsLocation
    tags: tags
    brainImage: brainImage
    foundryProjectEndpoint: foundryProjectEndpoint
    modelName: modelName
    corsOrigins: corsOrigins
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = if (createBudget && !empty(budgetContacts)) {
  name: 'budget-${environmentName}'
  properties: {
    category: 'Cost'
    amount: budgetUsd
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
    }
    notifications: {
      quarter: { enabled: true, operator: 'GreaterThan', threshold: 25, contactEmails: budgetContacts }
      half: { enabled: true, operator: 'GreaterThan', threshold: 50, contactEmails: budgetContacts }
      ninety: { enabled: true, operator: 'GreaterThan', threshold: 90, contactEmails: budgetContacts }
    }
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryEndpoint
output BRAIN_URI string = resources.outputs.brainUri
output WEB_URI string = resources.outputs.webUri
output COSMOS_ENDPOINT string = resources.outputs.cosmosEndpoint
output STORAGE_ACCOUNT string = resources.outputs.storageAccount
