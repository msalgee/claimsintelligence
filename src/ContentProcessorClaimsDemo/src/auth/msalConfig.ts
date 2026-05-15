import {
  PublicClientApplication,
  type Configuration,
  type RedirectRequest,
} from '@azure/msal-browser';

const tenantId = import.meta.env.VITE_AAD_TENANT_ID;
const clientId = import.meta.env.VITE_AAD_CLIENT_ID;
const configuredRedirectUri = import.meta.env.VITE_REDIRECT_URI;
const redirectUri = configuredRedirectUri
  ? new URL(configuredRedirectUri, window.location.origin).toString()
  : window.location.origin;

export const apiScope = import.meta.env.VITE_AAD_API_SCOPE;

const msalConfig: Configuration = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri,
    postLogoutRedirectUri: redirectUri,
    navigateToLoginRequestUrl: true,
  },
  cache: {
    cacheLocation: 'sessionStorage',
    storeAuthStateInCookie: false,
  },
};

export const msalInstance = new PublicClientApplication(msalConfig);

export const loginRequest: RedirectRequest = {
  scopes: [apiScope, 'openid', 'profile', 'email'],
};

export const apiTokenRequest = {
  scopes: [apiScope],
};
