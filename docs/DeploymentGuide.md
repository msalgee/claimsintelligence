# Deployment Guide

## Overview

This guide walks you through deploying the Claims Intelligence project to Azure. A single `azd up` provisions all Azure resources, builds the four service images directly into the per-deploy Azure Container Registry (no Docker Desktop required), registers the sample claim schemas, seeds the AI Search policy indexes, and warms the recommendation grounding path. End-to-end deployment takes approximately 25-40 minutes for the default Development/Testing configuration.

🆘 **Need Help?** If you encounter any issues during deployment, check our [Troubleshooting Guide](./TroubleShootingSteps.md) for solutions to common problems.

> **Note**: Some tenants may have additional security restrictions that run periodically and could impact the application (e.g., blocking public network access). If you experience issues or the application stops working, check if these restrictions are the cause. In such cases, consider deploying the WAF-supported version to ensure compliance. To configure, [Click here](#31-choose-deployment-type-optional).

## Step 1: Prerequisites & Setup

### 1.1 Azure Account Requirements

Ensure you have access to an [Azure subscription](https://azure.microsoft.com/free/) with the following permissions:

| **Required Permission/Role** | **Scope** | **Purpose** |
|------------------------------|-----------|-------------|
| **Contributor** | Subscription or Resource Group | Create and manage Azure resources |
| **User Access Administrator** | Subscription or Resource Group | Manage user access and role assignments |
| **Role Based Access Control Admin** | Subscription/Resource Group level | Configure RBAC permissions |
| **Application Administrator** | Tenant | Create app registrations for authentication |

**🔍 How to Check Your Permissions:**

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to **Subscriptions** (search for "subscriptions" in the top search bar)
3. Click on your target subscription
4. In the left menu, click **Access control (IAM)**
5. Scroll down to see the table with your assigned roles - you should see:
   - **Contributor** 
   - **User Access Administrator**
   - **Role Based Access Control Administrator** (or similar RBAC role)

**For App Registration permissions:**
1. Go to **Microsoft Entra ID** → **Manage** → **App registrations**
2. Try clicking **New registration** 
3. If you can access this page, you have the required permissions
4. Cancel without creating an app registration

📖 **Detailed Setup:** Follow [Azure Account Set Up](./AzureAccountSetup.md) for complete configuration.

### 1.2 Check Service Availability & Quota

⚠️ **CRITICAL:** Before proceeding, ensure your chosen region has all required services available:

**Required Azure Services:**
- [Azure AI Foundry](https://learn.microsoft.com/en-us/azure/ai-foundry/)
- [Azure OpenAI Service](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [Azure AI Content Understanding Service](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/)
- [Azure Blob Storage](https://learn.microsoft.com/en-us/azure/storage/blobs/)
- [Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/) (4 container apps: Processor, API, Web, Workflow)
- [Azure Container Registry](https://learn.microsoft.com/en-us/azure/container-registry/)
- [Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/)
- [Azure Queue Storage](https://learn.microsoft.com/en-us/azure/storage/queues/)
- [Azure App Configuration](https://learn.microsoft.com/en-us/azure/azure-app-configuration/)
- [GPT Model Capacity](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models)

**Recommended Regions:** Australia East, Central US, East Asia, East US 2, Japan East, North Europe, Southeast Asia, UK South.

🔍 **Check Availability:** Use [Azure Products by Region](https://azure.microsoft.com/en-us/explore/global-infrastructure/products-by-region/) to verify service availability.

### 1.3 Quota Check (Optional)

💡 **RECOMMENDED:** Check your Azure OpenAI quota availability before deployment for optimal planning.

**Recommended Configuration:**
- **Default:** 300k tokens
- **Optimal:** 500k tokens (recommended for multi-document claim processing)

> **Note:** When you run `azd up`, the deployment will automatically show you regions with available quota, so this pre-check is optional but helpful for planning purposes. If you need more capacity, request a quota increase from the [Azure portal Quotas blade](https://portal.azure.com/#view/Microsoft_Azure_Quotas/QuotaMenuBlade/~/overview).

## Step 2: Choose Your Deployment Environment

Select one of the following options to deploy the project:

### Environment Comparison

| **Option**                 | **Best For**                              | **Prerequisites**       | **Setup Time** |
| -------------------------- | ----------------------------------------- | ----------------------- | -------------- |
| **GitHub Codespaces**      | Quick deployment, no local setup required | GitHub account          | ~3-5 minutes   |
| **VS Code Dev Containers** | Fast deployment with local tools          | Docker Desktop, VS Code | ~5-10 minutes  |
| **VS Code Web**            | Quick deployment, no local setup required | Azure account           | ~2-4 minutes   |
| **Local Environment**      | Enterprise environments, full control     | All tools individually  | ~15-30 minutes |

**💡 Recommendation:** For fastest deployment, start with **GitHub Codespaces** - no local installation required.

---

<details>
<summary><b>Option A: GitHub Codespaces (Easiest)</b></summary>

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/msalgee/claimsintelligence)

1. Click the badge above (may take several minutes to load)
2. Accept default values on the Codespaces creation page
3. Wait for the environment to initialize (includes all deployment tools)
4. Proceed to [Step 3: Configure Deployment Settings](#step-3-configure-deployment-settings)

</details>

<details>
<summary><b>Option B: VS Code Dev Containers</b></summary>

[![Open in Dev Containers](https://img.shields.io/static/v1?style=for-the-badge&label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/msalgee/claimsintelligence)

**Prerequisites:**
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [VS Code](https://code.visualstudio.com/) with [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

**Steps:**
1. Start Docker Desktop
2. Click the badge above to open in Dev Containers
3. Wait for the container to build and start (includes all deployment tools)
4. Proceed to [Step 3: Configure Deployment Settings](#step-3-configure-deployment-settings)

</details>

<details>
<summary><b>Option C: Visual Studio Code Web</b></summary>

 [![Open in Visual Studio Code Web](https://img.shields.io/static/v1?style=for-the-badge&label=Visual%20Studio%20Code%20(Web)&message=Open&color=blue&logo=visualstudiocode&logoColor=white)](https://vscode.dev/azure/?vscode-azure-exp=foundry&agentPayload=eyJiYXNlVXJsIjogImh0dHBzOi8vcmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbS9taWNyb3NvZnQvY29udGVudC1wcm9jZXNzaW5nLXNvbHV0aW9uLWFjY2VsZXJhdG9yL3JlZnMvaGVhZHMvbWFpbi9pbmZyYS92c2NvZGVfd2ViIiwgImluZGV4VXJsIjogIi9pbmRleC5qc29uIiwgInZhcmlhYmxlcyI6IHsiYWdlbnRJZCI6ICIiLCAiY29ubmVjdGlvblN0cmluZyI6ICIiLCAidGhyZWFkSWQiOiAiIiwgInVzZXJNZXNzYWdlIjogIiIsICJwbGF5Z3JvdW5kTmFtZSI6ICIiLCAibG9jYXRpb24iOiAiIiwgInN1YnNjcmlwdGlvbklkIjogIiIsICJyZXNvdXJjZUlkIjogIiIsICJwcm9qZWN0UmVzb3VyY2VJZCI6ICIiLCAiZW5kcG9pbnQiOiAiIn0sICJjb2RlUm91dGUiOiBbImFpLXByb2plY3RzLXNkayIsICJweXRob24iLCAiZGVmYXVsdC1henVyZS1hdXRoIiwgImVuZHBvaW50Il19)

1. Click the badge above (may take a few minutes to load)
2. Sign in with your Azure account when prompted
3. Select the subscription where you want to deploy the solution
4. Wait for the environment to initialize (includes all deployment tools)
5. Once the solution opens, the **AI Foundry terminal** will automatically start running the following command to install the required dependencies:

    ```shell
    sh install.sh
    ```
    During this process, you’ll be prompted with the message:
    ```
    What would you like to do with these files?
    - Overwrite with versions from template
    - Keep my existing files unchanged
    ```
    Choose “**Overwrite with versions from template**” and provide a unique environment name when prompted.

6. **Authenticate with Azure** (VS Code Web requires device code authentication):
   
    ```shell
    az login --use-device-code
    ```
    > **Note:** In VS Code Web environment, the regular `az login` command may fail. Use the `--use-device-code` flag to authenticate via device code flow. Follow the prompts in the terminal to complete authentication.
    
7. Proceed to [Step 3: Configure Deployment Settings](#step-3-configure-deployment-settings)

</details>

<details>
<summary><b>Option D: Local Environment</b></summary>

**Required Tools:**
- [PowerShell 7.0+](https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell) 
- [Azure Developer CLI (azd) 1.18.0+](https://aka.ms/install-azd)
- [Python 3.9+](https://www.python.org/downloads/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Git](https://git-scm.com/downloads)

**Setup Steps:**
1. Install all required deployment tools listed above
2. Clone the repository:
   ```shell
   git clone https://github.com/msalgee/claimsintelligence.git
   cd claimsintelligence
   ```
3. Open the project folder in your terminal
4. Proceed to [Step 3: Configure Deployment Settings](#step-3-configure-deployment-settings)

**PowerShell Users:** If you encounter script execution issues, run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

</details>

## Step 3: Configure Deployment Settings

Review the configuration options below. You can customize any settings that meet your needs, or leave them as defaults to proceed with a standard deployment.

### 3.0 Choose a Cost Profile (Optional)

The defaults in `infra/main.parameters.json` are tuned for **Demo** (small SKUs, no private networking, no jumpbox, 90-day Application Insights retention). To upgrade to a Pilot or Production posture, edit the boolean toggles in `infra/main.parameters.json` (`enablePrivateNetworking`, `enableScalability`, `enableRedundancy`, `enablePurgeProtection`, `deployJumpbox`) before running `azd up`. See [Cost Profiles](./CostProfiles.md) for the full table and recommended combinations.

### 3.1 Override App Registration Settings

The deployment requires two Microsoft Entra ID app registrations (SPA + API). Follow [App Authentication Configuration](./ConfigureAppAuthentication.md) to create them, then publish their values to the azd environment so they are baked into the container apps:

```shell
azd env set APP_WEB_CLIENT_ID <spa-client-id>
azd env set APP_API_SCOPE api://<api-client-id>/user_impersonation
```

Without these overrides the SPA will fail to acquire tokens (`AADSTS90013`).

During `azd up`, the post-provisioning hook automatically adds the freshly deployed Claims Demo Container App origin to the SPA app registration redirect URI list. This prevents `AADSTS50011` redirect URI mismatches when you deploy to a new resource group and Container Apps generates a new hostname. The signed-in deployment identity must own the SPA app registration or have **Application Administrator** / **Cloud Application Administrator** permissions in Entra ID.

The same hook acquires an Azure CLI bearer token for the API scope so it can register schemas and seed AI Search through the deployed API. If the tenant has not yet consented the Microsoft Azure CLI enterprise application to that API scope, the hook grants the delegated `user_impersonation` consent and retries token acquisition.

### 3.2 Reuse an Existing Foundry Project (Advanced)

The default and recommended path is to let `azd up` create the Foundry account, project, model deployments, capability hosts, project connection to AI Search, and RBAC wiring.

To point at an existing Foundry project instead, set the full project resource ID before deployment:

```shell
azd env set AZURE_EXISTING_AIPROJECT_RESOURCE_ID /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account-name>/projects/<project-name>
```

Reuse is an advanced path. When `AZURE_EXISTING_AIPROJECT_RESOURCE_ID` is set, this project does not recreate the project's Agents capability hosts or Foundry project connection/RBAC to the deployment-created AI Search service. The existing project must already be Agents-ready, and you may need to wire the AI Search connection and project managed identity permissions manually before the recommendation agent can ground against policy content. For clean customer demos, leave this value blank.

## Step 4: Deploy the Solution

💡 **Before You Start:** If you encounter any issues during deployment, check our [Troubleshooting Guide](./TroubleShootingSteps.md) for common solutions.

> ⚠️ **Critical: Redeployment Warning**  
> If you have previously run `azd up` in this folder (i.e., a `.azure` folder exists), you must [create a fresh environment](#creating-a-new-environment) to avoid conflicts and deployment failures.

### 4.1 Authenticate with Azure

```shell
azd auth login
```

**For specific tenants:**
```shell
azd auth login --tenant-id <tenant-id>
```

> **Finding Tenant ID:** 
   > 1. Open the [Azure Portal](https://portal.azure.com/).
   > 2. Navigate to **Microsoft Entra ID** from the left-hand menu.
   > 3. Under the **Overview** section, locate the **Tenant ID** field. Copy the value displayed.

### 4.2 Start Deployment

**NOTE:** If you are running the latest azd version (version 1.23.9), please run the following command. 
```bash 
azd config set provision.preflight off
```

```shell
azd up
```

**During deployment, you'll be prompted for:**
1. **Environment name** - Must be 3-20 characters, lowercase alphanumeric only (e.g., `cpsapp01`).
2. **Azure subscription** selection.
3. **Azure AI Foundry deployment region** - Select a region with available GPT-5.1 model quota for AI operations.
4. **Primary location** - Select the region where your infrastructure resources will be deployed (Australia East, Central US, East Asia, East US 2, Japan East, North Europe, Southeast Asia, UK South).
5. **Resource group** selection (create new or use existing).

**Expected Duration:** 25-40 minutes for default configuration. Phases:
1. **Provision** (~10-15 min) — creates RG, networking, ACR, AI Foundry, Cosmos, Storage, Container Apps Environment, and 5 Container Apps booting on a placeholder image.
2. **Build & deploy images** (~10-20 min) — the post-provisioning hook stages clean build contexts that exclude local dependency folders such as `node_modules`, then `az acr build` builds each service image (`contentprocessor`, `contentprocessorapi`, `contentprocessorworkflow`, `contentprocessorclaimsdemo`) into the per-deploy ACR (`cr<env><suffix>.azurecr.io`) and `az containerapp update` flips each app to its real image. No local Docker required.
3. **App registration redirect update** (~seconds) — updates the SPA app registration with the new Web and Claims Demo URLs for this deployment.
4. **Schema registration** (~1 min) — auto-registers the four sample schemas and the `Auto Claim` schema set against the API.
5. **AI Search seeding and grounding warmup** (~1-10 min) — sends member-policy and handling-guidance markdown to the API, which uses managed identity to create/update both AI Search indexes and upload policy documents. The hook then calls `POST /claimsdemo/warmup-grounding` with retries so the Foundry project's managed identity has time to see the new Search RBAC before the first recommendation click.

**⚠️ Deployment Issues:** If you encounter errors or timeouts, try a different region as there may be capacity constraints. For detailed error solutions, see our [Troubleshooting Guide](./TroubleShootingSteps.md).

⚠️ **Important:** App registrations must be configured before `azd up`. The post-deployment checks below are verification steps, not a replacement for Step 3.1.

## Step 5: Post-Deployment Configuration

### 5.1 Schema Registration (Automatic)

 > The deployment registers the four schemas in the **Auto Claim** schema set (`AutoInsuranceClaimForm`, `PoliceReportDocument`, `RepairEstimateDocument`, `DamagedVehicleImageAssessment`) used by the claims demo.

Schema registration happens **automatically** as part of the `azd up` post-provisioning hook — no manual steps required. After infrastructure is deployed, the hook:

1. Waits for the API container app to be ready
2. Registers the sample schema files (auto claim, damaged car image, police report, repair estimate)
3. Creates an **"Auto Claim"** schema set
4. Adds all registered schemas into the schema set

The same hook then seeds the AI Search policy indexes automatically. It sends member-policy and handling-guidance markdown files to the API, and the API uses its managed identity to create the Search indexes and upload the documents directly. You do not need to create the indexes manually or open the storage account to your workstation. After seeding, the hook runs the recommendation grounding warmup loop so the first demo user usually avoids the Search RBAC propagation window.

After successful deployment, the terminal displays container app details and schema registration output:

```
🧭 Claims Demo App Endpoint: ca-<env>-claims.<region>.azurecontainerapps.io

🧭 API App Details:
  ✅ Name: ca-<env>-api
  🌐 Endpoint: ca-<env>-api.<region>.azurecontainerapps.io
  🔗 Portal URL: https://portal.azure.com/#resource/...

🧭 Workflow App Details:
  ✅ Name: ca-<env>-wkfl
  🔗 Portal URL: https://portal.azure.com/#resource/...

📦 Registering schemas and creating schema set...
  ⏳ Waiting for API to be ready...
  ✅ API is ready.
============================================================
Step 1: Register schemas
============================================================
✓ Successfully registered: Auto Insurance Claim Form's Schema Id - <id>
✓ Successfully registered: Damaged Vehicle Image Assessment's Schema Id - <id>
✓ Successfully registered: Police Report Document's Schema Id - <id>
✓ Successfully registered: Repair Estimate Document's Schema Id - <id>

============================================================
Step 2: Create schema set
============================================================
✓ Created schema set 'Auto Claim' with ID: <id>

============================================================
Step 3: Add schemas to schema set
============================================================
  ✓ Added 'AutoInsuranceClaimForm' (<id>) to schema set
  ✓ Added 'DamagedVehicleImageAssessment' (<id>) to schema set
  ✓ Added 'PoliceReportDocument' (<id>) to schema set
  ✓ Added 'RepairEstimateDocument' (<id>) to schema set

============================================================
Schema registration process completed.
  Schema set ID: <id>
  Schemas added: 4
============================================================
  ✅ Schema registration complete.
```

### 5.2 Verify Authentication

Authentication is configured by Step 3.1 and the `azd up` deployment. No manual Container App Authentication setup is required.

1. Open the Claims Demo endpoint from the deployment output.
2. Sign in with an account allowed by your Entra tenant/app registration policy.
3. If sign-in fails with `AADSTS90013`, set `APP_WEB_CLIENT_ID` and `APP_API_SCOPE`, then rerun `azd up` so the values flow into the container apps. If sign-in fails with `AADSTS50011`, rerun `azd hooks run postprovision` so the deployed Claims Demo URL is added to the SPA redirect URI list.

### 5.3 Verify Deployment

1. Access your application using the **Web App Endpoint** from the deployment output.
2. Confirm the application loads successfully.
3. Verify you can sign in with your authenticated account.

### 5.4 Test the Application

**Quick Test Steps:**
1. **Download Samples**: Get sample files from the [samples directory](../src/ContentProcessorAPI/samples) — use the `claim_demo_persona/` or `claim_theft_vandalism/` folders for auto claim documents.
2. **Upload**: In the Claims Demo, drag the claim documents into the upload area or choose **Use sample claim**, then click **Auto-classify & analyze**.
3. **Review**: Work through the 7-step claims journey. Confirm Step 1 shows all documents classified, Step 2/3 summarize what happened, Step 4/5 show coverage and risk findings, Step 6 produces a grounded recommendation, and Step 7 drafts the customer letter.

📖 **Detailed Instructions:** See the complete [Golden Path Workflows](./GoldenPathWorkflows.md) guide for step-by-step testing procedures.

## Step 6: Clean Up (Optional)

### Remove All Resources
```shell
azd down
```

### Manual Cleanup (if needed)
If deployment fails or you need to clean up manually:
- Follow [Delete Resource Group Guide](./DeleteResourceGroup.md).

## Managing Multiple Environments

### Recover from Failed Deployment

If your deployment failed or encountered errors, here are the steps to recover:

<details>
<summary><b>Recover from Failed Deployment</b></summary>

**If your deployment failed or encountered errors:**

1. **Try a different region:** Create a new environment and select a different Azure region during deployment
2. **Clean up and retry:** Use `azd down` to remove failed resources, then `azd up` to redeploy
3. **Check troubleshooting:** Review [Troubleshooting Guide](./TroubleShootingSteps.md) for specific error solutions
4. **Fresh start:** Create a completely new environment with a different name

**Example Recovery Workflow:**
```shell
# Remove failed deployment (optional)
azd down

# Create new environment (3-20 chars, alphanumeric only)
azd env new conpro2

# Deploy with different settings/region
azd up
```

</details>

### Creating a New Environment

If you need to deploy to a different region, test different configurations, or create additional environments:

<details>
<summary><b>Create a New Environment</b></summary>

**Create Environment Explicitly:**
```shell
# Create a new named environment (3-20 characters, lowercase alphanumeric only)
azd env new <new-environment-name>

# Select the new environment
azd env select <new-environment-name>

# Deploy to the new environment
azd up
```

**Example:**
```shell
# Create a new environment for production (valid: 3-20 chars)
azd env new conproprod

# Switch to the new environment
azd env select conproprod

# Deploy with fresh settings
azd up
```

> **Environment Naming Requirements:**
> - **Length:** 3-20 characters
> - **Characters:** Lowercase alphanumeric only (a-z, 0-9)
> - **No special characters** (-, _, spaces, etc.)
> - **Valid examples:** `conpro`, `test123`, `myappdev`, `prod2024`
> - **Invalid examples:** `co` (too short), `my-very-long-environment-name` (too long), `test_env` (underscore not allowed), `myapp-dev` (hyphen not allowed)

</details>

<details>
<summary><b>Switch Between Environments</b></summary>

**List Available Environments:**
```shell
azd env list
```

**Switch to Different Environment:**
```shell
azd env select <environment-name>
```

**View Current Environment Variables:**
```shell
azd env get-values
```

</details>

### Best Practices for Multiple Environments

- **Use descriptive names:** `conprodev`, `conproprod`, `conprotest` (remember: 3-20 chars, alphanumeric only)
- **Different regions:** Deploy to multiple regions for testing quota availability
- **Separate configurations:** Each environment can have different parameter settings
- **Clean up unused environments:** Use `azd down` to remove environments you no longer need

## Next Steps

Now that your deployment is complete and tested, explore these resources:

- [Technical Architecture](./TechnicalArchitecture.md) - Understand the system design and components
- [Claim Processing Workflow](./ClaimProcessWorkflow.md) - How the multi-document claim pipeline runs end-to-end
- [Gap Analysis Ruleset Guide](./GapAnalysisRulesetGuide.md) - Authoring rules for the YAML-DSL gap analysis stage
- [API Reference](./API.md) - Programmatic document and claim processing
- [Cost Profiles](./CostProfiles.md) - Tune SKUs and features for Demo / Pilot / Production

## Need Help?

- 🐛 **Issues:** Check [Troubleshooting Guide](./TroubleShootingSteps.md)

---

## Deploying Local Changes

`azd deploy` rebuilds whichever services have local changes and redeploys them to the existing Container Apps in your azd environment without re-running provisioning. To redeploy a single service:

```shell
azd deploy contentprocessorapi
azd deploy contentprocessorworkflow
azd deploy contentprocessor
azd deploy contentprocessorclaimsdemo
```

If you've changed Bicep, run `azd provision` first, then `azd deploy`.
