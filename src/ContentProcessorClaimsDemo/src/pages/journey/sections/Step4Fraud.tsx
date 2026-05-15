import {
  Accordion,
  AccordionHeader,
  AccordionItem,
  AccordionPanel,
  Badge,
  Body1,
  Button,
  Caption1,
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
import { useEffect, useState } from 'react';
import { JourneySection } from '../../../components/journey/JourneySection';
import { SectionError, SectionLoading } from '../../../components/journey/SectionStatus';
import { claimsdemo } from '../../../api/apiClient';
import { useSectionData } from '../../../api/useSectionData';
import { useClaimStore } from '../../../store/claimStore';
import type { ReactElement } from 'react';
import type { FraudAck, FraudSeverity } from '../../../api/types';
import type { JourneyMode } from '../../../components/journey/JourneySection';

const useStyles = makeStyles({
  banner: {
    paddingTop: '20px',
    paddingRight: '24px',
    paddingBottom: '20px',
    paddingLeft: '24px',
    borderTopLeftRadius: '12px',
    borderTopRightRadius: '12px',
    borderBottomRightRadius: '12px',
    borderBottomLeftRadius: '12px',
    backgroundImage:
      'linear-gradient(135deg, rgba(43,197,180,0.10), rgba(35,105,186,0.10))',
    display: 'flex',
    flexDirection: 'column',
    rowGap: '14px',
    marginBottom: '20px',
  },
  bandRow: {
    display: 'flex',
    alignItems: 'center',
    columnGap: '16px',
    flexWrap: 'wrap',
  },
  bandScore: {
    fontSize: '32px',
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
    color: tokens.colorNeutralForeground1,
    minWidth: '88px',
  },
  bandScoreSuffix: {
    fontSize: '16px',
    fontWeight: 500,
    color: tokens.colorNeutralForeground3,
    marginLeft: '4px',
  },
  bandSegments: {
    display: 'flex',
    flex: 1,
    minWidth: '240px',
    height: '14px',
    borderTopLeftRadius: '7px',
    borderTopRightRadius: '7px',
    borderBottomRightRadius: '7px',
    borderBottomLeftRadius: '7px',
    overflow: 'hidden',
    columnGap: '2px',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  bandSegment: {
    flex: 1,
    transitionProperty: 'opacity',
    transitionDuration: '0.3s',
  },
  bandLabels: {
    display: 'flex',
    columnGap: '2px',
    fontSize: '11px',
    color: tokens.colorNeutralForeground3,
  },
  bandLabel: {
    flex: 1,
    textAlign: 'center',
  },
  bandLabelActive: {
    color: tokens.colorNeutralForeground1,
    fontWeight: 600,
  },
  bannerRight: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '4px',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '8px',
  },
  findingHeader: {
    display: 'flex',
    alignItems: 'center',
    columnGap: '10px',
    flexWrap: 'wrap',
    rowGap: '4px',
    minWidth: 0,
  },
  findingTitle: {
    whiteSpace: 'normal',
    overflowWrap: 'anywhere',
    minWidth: 0,
    flex: '1 1 auto',
  },
  contributing: {
    color: tokens.colorNeutralForeground3,
    marginTop: '8px',
  },
  ackRow: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    columnGap: '12px',
    rowGap: '6px',
    marginTop: '12px',
    paddingTop: '10px',
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`,
  },
  ackMeta: {
    color: tokens.colorNeutralForeground3,
    fontVariantNumeric: 'tabular-nums',
  },
});

const severityIcon: Record<FraudSeverity, ReactElement> = {
  info: <CheckmarkCircle20Filled style={{ color: '#31C85A' }} />,
  warning: <Warning20Filled style={{ color: '#FFCF03' }} />,
  critical: <ErrorCircle20Filled style={{ color: '#C5093B' }} />,
};

const severityColor: Record<FraudSeverity, 'success' | 'warning' | 'danger'> = {
  info: 'success',
  warning: 'warning',
  critical: 'danger',
};

function gaugeColor(score: number): string {
  if (score < 30) return '#31C85A';
  if (score < 60) return '#FFCF03';
  return '#C5093B';
}

const RISK_BAND_LABELS = ['Low', 'Low-Med', 'Medium', 'High'];
const RISK_BAND_COLORS = ['#31C85A', '#9DC83A', '#FFCF03', '#C5093B'];

function riskBandIndex(score: number): number {
  if (score < 25) return 0;
  if (score < 50) return 1;
  if (score < 75) return 2;
  return 3;
}

// Convert API-emitted snake_case identifiers ("license_plate discrepancy")
// into Title Case. Titles are kept full-length here — the backend already
// returns short, header-friendly observation titles, and we let long titles
// wrap rather than visually clipping them in the accordion header.
function humanizeFindingTitle(raw: string): string {
  if (!raw) return raw;
  const cleaned = raw
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

interface Props {
  mode: JourneyMode;
  onNext: () => void;
  onEdit: () => void;
}

export function Step4Fraud({ mode, onNext, onEdit }: Props) {
  const styles = useStyles();
  const claimId = useClaimStore((s) => s.claimId);
  const { loading, error, data } = useSectionData(
    4,
    (id) => claimsdemo.fraudCheck(id),
    mode !== 'locked',
  );
  const [acks, setAcks] = useState<Record<string, FraudAck>>({});
  const [acksLoaded, setAcksLoaded] = useState(false);
  const [pendingAck, setPendingAck] = useState<string | null>(null);

  useEffect(() => {
    if (!claimId || mode === 'locked') return;
    let cancelled = false;
    claimsdemo
      .fraudAcks(claimId)
      .then((p) => {
        if (!cancelled) {
          setAcks(p.acks ?? {});
          setAcksLoaded(true);
        }
      })
      .catch(() => {
        if (!cancelled) setAcksLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [claimId, mode]);

  const toggleAck = async (findingId: string, currently: boolean) => {
    if (!claimId) return;
    setPendingAck(findingId);
    try {
      const res = await claimsdemo.setFraudAck(claimId, findingId, !currently);
      setAcks(res.acks ?? {});
    } catch {
      // leave UI state unchanged on failure
    } finally {
      setPendingAck(null);
    }
  };

  const totalFindings = data?.findings.length ?? 0;
  const unackedCritical = (data?.findings ?? []).filter(
    (f) => f.severity === 'critical' && !acks[f.id],
  );
  const doneSummary = data
    ? `Risk score ${data.risk_score}/100 (${data.risk_band}) · ${totalFindings} signals reviewed`
    : undefined;

  return (
    <JourneySection
      step={4}
      techStack="Microsoft Agent Framework · GPT-5.1"
      techDetails="Uses claim gap-analysis output produced by Microsoft Agent Framework with GPT-5.1, then applies deterministic scoring to display risk signals and critical acknowledgements."
      title="Risk & integrity check"
      blurb="Potential inconsistencies and integrity concerns are highlighted before settlement."
      mode={mode}
      doneSummary={doneSummary}
      onNext={onNext}
      onEdit={onEdit}
      nextLabel="Continue to adjuster review"
      nextDisabled={loading || !!error || unackedCritical.length > 0}
    >
      {loading && <SectionLoading label="Checking integrity signals…" />}
      {error && <SectionError message={error} />}
      {!loading && !error && data && (
        <>
          <div className={styles.banner}>
            <div className={styles.bandRow}>
              <motion.span
                className={styles.bandScore}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.3 }}
                style={{ color: gaugeColor(data.risk_score) }}
              >
                {data.risk_score}
                <span className={styles.bandScoreSuffix}>/100</span>
              </motion.span>
              <div style={{ flex: 1, minWidth: '240px' }}>
                <div className={styles.bandSegments}>
                  {RISK_BAND_COLORS.map((color, i) => {
                    const active = i === riskBandIndex(data.risk_score);
                    return (
                      <div
                        key={i}
                        className={styles.bandSegment}
                        style={{
                          backgroundColor: color,
                          opacity: active ? 1 : 0.25,
                        }}
                      />
                    );
                  })}
                </div>
                <div className={styles.bandLabels} style={{ marginTop: '4px' }}>
                  {RISK_BAND_LABELS.map((label, i) => (
                    <span
                      key={label}
                      className={[
                        styles.bandLabel,
                        i === riskBandIndex(data.risk_score) ? styles.bandLabelActive : '',
                      ].filter(Boolean).join(' ')}
                    >
                      {label}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            <div className={styles.bannerRight}>
              <Subtitle2>Overall risk band: {data.risk_band}</Subtitle2>
              <Body1 style={{ color: tokens.colorNeutralForeground2 }}>
                {data.findings.length} signals reviewed across {data.findings.length} document
                cross-references.
              </Body1>
              {unackedCritical.length > 0 && (
                <Caption1 style={{ color: '#C5093B', marginTop: '4px' }}>
                  {unackedCritical.length} critical finding{unackedCritical.length === 1 ? '' : 's'} must be acknowledged before continuing.
                </Caption1>
              )}
            </div>
          </div>
          <div className={styles.list}>
            <Accordion collapsible multiple>
              {data.findings.map((f) => {
                const ack = acks[f.id];
                const isAcked = !!ack;
                const acked = isAcked
                  ? new Date(ack.at).toLocaleString(undefined, {
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                      hour: 'numeric',
                      minute: '2-digit',
                    })
                  : null;
                return (
                  <AccordionItem key={f.id} value={f.id}>
                    <AccordionHeader>
                      <span className={styles.findingHeader}>
                        {severityIcon[f.severity]}
                        <Subtitle2 className={styles.findingTitle}>
                          {humanizeFindingTitle(f.title)}
                        </Subtitle2>
                        <Badge appearance="tint" color={severityColor[f.severity]}>
                          {f.severity}
                        </Badge>
                        {isAcked && (
                          <Badge appearance="tint" color="brand">
                            Acknowledged
                          </Badge>
                        )}
                      </span>
                    </AccordionHeader>
                    <AccordionPanel>
                      <Body1>{f.rationale}</Body1>
                      <Caption1 className={styles.contributing}>
                        Contributing documents: {f.contributing_docs.join(', ')}
                      </Caption1>
                      <div className={styles.ackRow}>
                        <Button
                          appearance={isAcked ? 'subtle' : 'primary'}
                          size="small"
                          disabled={!acksLoaded || pendingAck === f.id}
                          onClick={() => toggleAck(f.id, isAcked)}
                        >
                          {isAcked ? 'Undo acknowledgement' : 'Acknowledge finding'}
                        </Button>
                        {isAcked && (
                          <Caption1 className={styles.ackMeta}>
                            Acknowledged by {ack.by} · {acked}
                          </Caption1>
                        )}
                      </div>
                    </AccordionPanel>
                  </AccordionItem>
                );
              })}
            </Accordion>
          </div>
        </>
      )}
    </JourneySection>
  );
}
