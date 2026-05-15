targetScope = 'resourceGroup'

@description('Required. Name of the Azure AI Foundry account.')
param accountName string

@description('Required. Name of the Azure AI Foundry project.')
param projectName string

@description('Required. Principal ID for the API managed identity.')
param apiPrincipalId string

@description('Required. Principal ID for the workflow managed identity.')
param workflowPrincipalId string

@description('Required. Name of the Azure AI Search service.')
param searchName string

@description('Required. Resource ID of the Azure AI Search service.')
param searchResourceId string

@description('Required. Location of the Azure AI Search service.')
param searchLocation string

@description('Required. Foundry project connection name for Azure AI Search.')
param searchConnectionName string

var azureAiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: accountName
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundryAccount
  name: projectName
}

resource searchService 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}

resource accountCapabilityHost 'Microsoft.CognitiveServices/accounts/capabilityHosts@2025-04-01-preview' = {
  parent: foundryAccount
  name: 'default'
  properties: {
    capabilityHostKind: 'Agents'
  }
}

resource projectCapabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-04-01-preview' = {
  parent: foundryProject
  name: 'default'
  properties: {
    // Public spec requires `capabilityHostKind`; today the API infers it
    // from the parent account capability host, but adding it explicitly
    // future-proofs the deploy against an api-version bump that starts
    // enforcing the field. Zero behavioural change today.
    capabilityHostKind: 'Agents'
  }
  dependsOn: [
    accountCapabilityHost
  ]
}

resource projectAiUserApi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundryProject
  name: guid(foundryProject.id, 'api-mi-azureAiUser', azureAiUserRoleId)
  properties: {
    principalId: apiPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalType: 'ServicePrincipal'
  }
  dependsOn: [
    projectCapabilityHost
  ]
}

resource projectAiUserWorkflow 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundryProject
  name: guid(foundryProject.id, 'workflow-mi-azureAiUser', azureAiUserRoleId)
  properties: {
    principalId: workflowPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalType: 'ServicePrincipal'
  }
  dependsOn: [
    projectCapabilityHost
  ]
}

resource foundrySearchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundryProject
  name: searchConnectionName
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${searchName}.search.windows.net/'
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: searchResourceId
      location: searchLocation
    }
  }
  dependsOn: [
    projectCapabilityHost
  ]
}

resource foundryProjectMiToSearchDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: searchService
  name: guid(searchService.id, 'foundryProjectMi-searchIndexDataContributor', searchIndexDataContributorRoleId)
  properties: {
    principalId: foundryProject.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
    principalType: 'ServicePrincipal'
  }
  dependsOn: [
    foundrySearchConnection
  ]
}

resource foundryProjectMiToSearchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: searchService
  name: guid(searchService.id, 'foundryProjectMi-searchServiceContributor', searchServiceContributorRoleId)
  properties: {
    principalId: foundryProject.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalType: 'ServicePrincipal'
  }
  dependsOn: [
    foundrySearchConnection
  ]
}