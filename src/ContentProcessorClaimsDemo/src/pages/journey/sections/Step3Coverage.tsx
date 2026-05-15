import {
  Badge,
  Body1,
  Card,
  CardHeader,
  Subtitle2,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  CheckmarkCircle20Filled,
  ErrorCircle20Filled,
  Warning20Filled,
} from '@fluentui/react-icons';
import { motion } from 'framer-motion';
import { useState } from 'react';
import { JourneySection } from '../../../components/journey/JourneySection';
import { SectionError, SectionLoading } from '../../../components/journey/SectionStatus';
import { claimsdemo } from '../../../api/apiClient';
import { useSectionData } from '../../../api/useSectionData';
import type { ReactElement } from 'react';
import type { BusinessCheckStatus } from '../../../api/types';
import type { JourneyMode } from '../../../components/journey/JourneySection';

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    columnGap: '16px',
    rowGap: '16px',
    '@media (max-width: 760px)': { gridTemplateColumns: '1fr' },
  },
  card: {
    paddingTop: '16px',
    paddingRight: '16px',
    paddingBottom: '16px',
    paddingLeft: '16px',
  },
  expand: {
    marginTop: '12px',
    color: '#00BCBE',
    cursor: 'pointer',
    fontWeight: 600,
  },
  details: {
    marginTop: '8px',
    color: tokens.colorNeutralForeground2,
  },
});

const statusIcon: Record<BusinessCheckStatus, ReactElement> = {
  pass: <CheckmarkCircle20Filled style={{ color: '#31C85A' }} />,
  warn: <Warning20Filled style={{ color: '#FFCF03' }} />,
  fail: <ErrorCircle20Filled style={{ color: '#C5093B' }} />,
};

const statusColor: Record<BusinessCheckStatus, 'success' | 'warning' | 'danger'> = {
  pass: 'success',
  warn: 'warning',
  fail: 'danger',
};

interface Props {
  mode: JourneyMode;
  onNext: () => void;
  onEdit: () => void;
}

export function Step3Coverage({ mode, onNext, onEdit }: Props) {
  const styles = useStyles();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const { loading, error, data } = useSectionData(
    5,
    (id) => claimsdemo.businessChecks(id),
    mode !== 'locked',
  );
  const checks = data?.checks ?? [];
  const passCount = checks.filter((c) => c.status === 'pass').length;
  const warnCount = checks.filter((c) => c.status === 'warn').length;
  const failCount = checks.filter((c) => c.status === 'fail').length;
  const doneSummary = checks.length
    ? `${passCount} pass · ${warnCount} warn · ${failCount} fail`
    : undefined;
  const blurb = checks.length
    ? `${checks.length} prerequisite checks are ready for review.`
    : 'Required claim-file evidence is checked before policy recommendation.';

  return (
    <JourneySection
      step={3}
      techStack="Microsoft Agent Framework · Rules engine"
      techDetails="The workflow uses Microsoft Agent Framework outputs plus deterministic claim-file prerequisite and gap rules to produce the pass, warn, and fail checklist."
      title="Coverage prerequisites"
      blurb={blurb}
      mode={mode}
      doneSummary={doneSummary}
      onNext={onNext}
      onEdit={onEdit}
      nextLabel="Continue to risk check"
      nextDisabled={loading || !!error}
    >
      {loading && <SectionLoading label="Checking prerequisites…" />}
      {error && <SectionError message={error} />}
      {!loading && !error && (
        <div className={styles.grid}>
          {checks.map((c, idx) => (
            <motion.div
              key={c.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: idx * 0.04 }}
            >
              <Card className={styles.card}>
                <CardHeader
                  image={statusIcon[c.status]}
                  header={<Subtitle2>{c.rule}</Subtitle2>}
                  description={
                    <Badge appearance="tint" color={statusColor[c.status]}>
                      {c.status.toUpperCase()}
                    </Badge>
                  }
                />
                <Body1 style={{ marginTop: '12px' }}>{c.summary}</Body1>
                <span
                  className={styles.expand}
                  role="button"
                  tabIndex={0}
                  aria-expanded={!!expanded[c.id]}
                  aria-controls={`coverage-check-${c.id}`}
                  aria-label={`${expanded[c.id] ? 'Hide details for' : 'Show details for'} ${c.rule}`}
                  onClick={() => setExpanded((e) => ({ ...e, [c.id]: !e[c.id] }))}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      setExpanded((e) => ({ ...e, [c.id]: !e[c.id] }));
                    }
                  }}
                >
                  {expanded[c.id] ? 'Hide details' : 'Why?'}
                </span>
                {expanded[c.id] && (
                  <Body1 id={`coverage-check-${c.id}`} className={styles.details}>{c.details}</Body1>
                )}
              </Card>
            </motion.div>
          ))}
        </div>
      )}
    </JourneySection>
  );
}
