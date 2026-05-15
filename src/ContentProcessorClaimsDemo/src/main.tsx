import { StrictMode, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { MsalProvider } from '@azure/msal-react';
import { FluentProvider } from '@fluentui/react-components';
import { App } from './App';
import { msalInstance } from './auth/msalConfig';
import { darkTheme, lightTheme } from './theme';
import { useThemeStore } from './store/themeStore';
import './index.css';

function ThemedApp() {
  const mode = useThemeStore((s) => s.mode);
  const theme = mode === 'dark' ? darkTheme : lightTheme;
  useEffect(() => {
    document.body.dataset.theme = mode;
  }, [mode]);
  return (
    <FluentProvider theme={theme} style={{ height: '100vh' }}>
      <MsalProvider instance={msalInstance}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </MsalProvider>
    </FluentProvider>
  );
}

async function bootstrap() {
  await msalInstance.initialize();
  await msalInstance.handleRedirectPromise();
  const account = msalInstance.getActiveAccount() ?? msalInstance.getAllAccounts()[0];
  if (account) msalInstance.setActiveAccount(account);

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ThemedApp />
    </StrictMode>,
  );
}

bootstrap().catch((err) => {
  console.error('Bootstrap failed:', err);
});
