import {
  Avatar,
  Body1,
  Button,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Subtitle2,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { WeatherMoon20Regular, WeatherSunny20Regular } from '@fluentui/react-icons';
import { useMsal } from '@azure/msal-react';
import { useNavigate } from 'react-router-dom';
import { loginRequest } from '../auth/msalConfig';
import { useThemeStore } from '../store/themeStore';

const useStyles = makeStyles({
  root: {
    height: '56px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingLeft: '24px',
    paddingRight: '24px',
    backgroundColor: tokens.colorNeutralBackground1,
    borderBottomWidth: '1px',
    borderBottomStyle: 'solid',
    borderBottomColor: tokens.colorNeutralStroke2,
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    cursor: 'pointer',
  },
  dot: {
    width: '10px',
    height: '10px',
    borderRadius: '50%',
    background: 'linear-gradient(135deg, #00BCBE 0%, #001272 100%)',
  },
  right: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
});

export function TopBar() {
  const styles = useStyles();
  const { instance, accounts } = useMsal();
  const account = accounts[0];
  const themeMode = useThemeStore((s) => s.mode);
  const toggleTheme = useThemeStore((s) => s.toggle);
  const initials = account?.name
    ? account.name
        .split(' ')
        .map((p) => p[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    : '??';
  const navigate = useNavigate();
  const goHome = () => navigate('/');

  return (
    <header className={styles.root}>
      <div
        className={styles.brand}
        onClick={goHome}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            goHome();
          }
        }}
        role="button"
        tabIndex={0}
      >
        <span className={styles.dot} />
        <Subtitle2 style={{ color: tokens.colorBrandForeground1, fontWeight: 700, letterSpacing: '0.02em' }}>
          Claims Intelligence
        </Subtitle2>
        <Body1 style={{ opacity: 0.55 }}>· Powered by Microsoft Foundry</Body1>
      </div>
      <div className={styles.right}>
        <Tooltip content={themeMode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} relationship="label">
          <Button
            appearance="subtle"
            icon={themeMode === 'dark' ? <WeatherSunny20Regular /> : <WeatherMoon20Regular />}
            onClick={toggleTheme}
            aria-label={themeMode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          />
        </Tooltip>
        {account ? (
          <Menu>
            <MenuTrigger disableButtonEnhancement>
              <Button appearance="subtle" icon={<Avatar name={account.name ?? '?'} initials={initials} size={28} />} />
            </MenuTrigger>
            <MenuPopover>
              <MenuList>
                <MenuItem disabled>{account.username}</MenuItem>
                <MenuItem onClick={() => instance.logoutRedirect()}>Sign out</MenuItem>
              </MenuList>
            </MenuPopover>
          </Menu>
        ) : (
          <Button appearance="primary" onClick={() => instance.loginRedirect(loginRequest)}>
            Sign in
          </Button>
        )}
      </div>
    </header>
  );
}
