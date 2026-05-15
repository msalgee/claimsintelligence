//
// Loading + error states shared across journey sections.

import { Body1, Spinner, makeStyles, tokens } from '@fluentui/react-components';
import { ErrorCircle20Filled } from '@fluentui/react-icons';

const useStyles = makeStyles({
  loading: {
    display: 'flex',
    alignItems: 'center',
    columnGap: '12px',
    paddingTop: '12px',
    paddingBottom: '12px',
    color: tokens.colorNeutralForeground2,
  },
  error: {
    display: 'flex',
    alignItems: 'center',
    columnGap: '8px',
    paddingTop: '8px',
    paddingBottom: '8px',
    color: tokens.colorPaletteRedForeground1,
  },
});

export function SectionLoading({ label = 'Working…' }: { label?: string }) {
  const styles = useStyles();
  return (
    <div className={styles.loading}>
      <Spinner size="tiny" />
      <Body1>{label}</Body1>
    </div>
  );
}

export function SectionError({ message }: { message: string }) {
  const styles = useStyles();
  return (
    <div className={styles.error} role="alert">
      <ErrorCircle20Filled />
      <Body1>{message}</Body1>
    </div>
  );
}
