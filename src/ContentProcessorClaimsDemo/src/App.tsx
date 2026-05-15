import { Navigate, Route, Routes } from 'react-router-dom';
import { makeStyles } from '@fluentui/react-components';
import { TopBar } from './components/TopBar';
import { LandingPage } from './pages/LandingPage';
import { JourneyPage } from './pages/JourneyPage';
import { useClaimStore } from './store/claimStore';

const useStyles = makeStyles({
  shell: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    overflow: 'hidden',
  },
  body: {
    flex: 1,
    overflowY: 'auto',
  },
});

function JourneyGuard({ children }: { children: React.ReactNode }) {
  const claimId = useClaimStore((s) => s.claimId);
  if (!claimId) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export function App() {
  const styles = useStyles();
  return (
    <div className={styles.shell}>
      <TopBar />
      <main className={styles.body}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route
            path="/journey"
            element={
              <JourneyGuard>
                <JourneyPage />
              </JourneyGuard>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
