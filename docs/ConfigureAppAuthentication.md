# Configure App Authentication

The Claims Demo uses two Microsoft Entra ID app registrations:

| App registration | Purpose |
|---|---|
| API app | Defines the `user_impersonation` API scope/audience. |
| SPA app | Lets the browser application sign users in and request the API scope. |

Create these app registrations before running `azd up`, then set the two `azd` environment values shown below. The deployment does not require client secrets, API keys, or manual Container App Authentication setup.

## Required Permissions

You need permission in Microsoft Entra ID to create app registrations and grant/admin-consent API permissions. If your tenant blocks app registration creation or consent, ask an Entra administrator to perform these steps.

## 1. Create the API App Registration

1. In the Azure portal, open **Microsoft Entra ID** > **App registrations** > **New registration**.
2. Name it something recognizable, such as `cps-<env>-api`.
3. Use **Accounts in this organizational directory only**.
4. Leave redirect URI blank and create the app.
5. Copy the **Application (client) ID**. You will use it to form the API scope.
6. Open **Expose an API**.
7. Set the **Application ID URI** to `api://<api-client-id>`.
8. Add a scope:
   - Scope name: `user_impersonation`
   - Who can consent: choose the tenant setting that matches your organization, commonly **Admins and users** for demos
   - Admin consent display name: `Access Content Processing API`
   - Admin consent description: `Allows the Claims Demo SPA to call the Content Processing API.`
   - User consent display name: `Access Content Processing API`
   - User consent description: `Allows the Claims Demo SPA to call the Content Processing API.`
   - State: **Enabled**

The API scope value is:

```text
api://<api-client-id>/user_impersonation
```

## 2. Create the SPA App Registration

1. In **App registrations**, choose **New registration**.
2. Name it something recognizable, such as `cps-<env>-web`.
3. Use **Accounts in this organizational directory only**.
4. For platform, choose **Single-page application (SPA)**.
5. Add a temporary local redirect URI, such as `http://localhost:5173/`, if the portal requires one. The deployed Claims Demo redirect URI is added automatically during `azd up` after Container Apps assigns the hostname.
6. Create the app.
7. Copy the **Application (client) ID**. This is the web client ID.
8. Open **API permissions** > **Add a permission** > **My APIs**.
9. Select the API app registration from Step 1 and add the `user_impersonation` delegated permission.
10. Grant admin consent if your tenant requires it.

## 3. Set azd Environment Values

Run these commands before `azd up`:

```shell
azd env set APP_WEB_CLIENT_ID <spa-client-id>
azd env set APP_API_SCOPE api://<api-client-id>/user_impersonation
```

`APP_WEB_SCOPE` and `APP_API_CLIENT_ID` are not used by the current Claims Demo deployment.

## 4. What azd up Does Automatically

During `azd up`, the post-provisioning hook:

- Builds and deploys the four container images.
- Deploys API Container Apps EasyAuth with `Return401`, the API audience from `APP_API_SCOPE`, and the SPA client ID as an allowed application.
- Adds the freshly assigned Claims Demo Container App URL to the SPA app registration redirect URI list.
- Registers the demo schemas and the `Auto Claim` schema set through the deployed API.
- Seeds the Azure AI Search handling-guidance and member-policy indexes through the deployed API using managed identity.
- Calls `POST /claimsdemo/warmup-grounding` with retries to absorb the first-deploy AI Search RBAC propagation window for the recommendation agent.
- If needed, grants the Microsoft Azure CLI enterprise application delegated consent to the API scope so the hook can acquire a bearer token for bootstrap calls.

The signed-in deployment identity must own the SPA app registration or have **Application Administrator** / **Cloud Application Administrator** permissions so the redirect URI patch can succeed.

## Troubleshooting

- `AADSTS90013`: `APP_WEB_CLIENT_ID` or `APP_API_SCOPE` is missing or still set to a placeholder. Re-run the `azd env set` commands above.
- `AADSTS50011`: the SPA redirect URI does not include the deployed Claims Demo URL. Re-run `azd hooks run postprovision` after the Container Apps have hostnames, or re-run `azd up`; the hook patches the redirect list.
- `AADSTS65001`: consent is missing for the Azure CLI bootstrap token. Re-run `azd up` with an identity that can grant consent, or ask an Entra administrator to grant consent for the API scope.
