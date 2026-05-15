import {
  Badge,
  Body1,
  Button,
  Caption1,
  Card,
  CardHeader,
  Subtitle1,
  Subtitle2,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { motion } from 'framer-motion';
import { JourneySection } from '../../../components/journey/JourneySection';
import { SectionError, SectionLoading } from '../../../components/journey/SectionStatus';
import { claimsdemo } from '../../../api/apiClient';
import { useSectionData } from '../../../api/useSectionData';
import { useClaimStore } from '../../../store/claimStore';
import type { JourneyMode } from '../../../components/journey/JourneySection';
import type {
  DispositionDecision,
  DispositionRecord,
  AuditEvent,
  MemberPolicySnapshot,
} from '../../../api/types';

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    gridTemplateColumns: '1.4fr 1fr',
    columnGap: '20px',
    '@media (max-width: 960px)': { gridTemplateColumns: '1fr' },
  },
  agentCard: {
    paddingTop: '20px',
    paddingRight: '20px',
    paddingBottom: '20px',
    paddingLeft: '20px',
    borderTopLeftRadius: '12px',
    borderTopRightRadius: '12px',
    borderBottomRightRadius: '12px',
    borderBottomLeftRadius: '12px',
    backgroundImage:
      'linear-gradient(135deg, rgba(43,197,180,0.10), rgba(35,105,186,0.06))',
    minHeight: '200px',
  },
  cursor: {
    display: 'inline-block',
    width: '7px',
    height: '14px',
    backgroundColor: '#00BCBE',
    marginLeft: '2px',
    verticalAlign: 'middle',
  },
  excerpts: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '10px',
  },
  excerptCard: {
    paddingTop: '12px',
    paddingRight: '12px',
    paddingBottom: '12px',
    paddingLeft: '12px',
  },
  verdictCard: {
    paddingTop: '20px',
    paddingRight: '20px',
    paddingBottom: '20px',
    paddingLeft: '20px',
    marginBottom: '20px',
  },
  confidenceBar: {
    height: '8px',
    backgroundColor: tokens.colorNeutralBackground3,
    borderTopLeftRadius: '4px',
    borderTopRightRadius: '4px',
    borderBottomRightRadius: '4px',
    borderBottomLeftRadius: '4px',
    overflow: 'hidden',
    marginTop: '8px',
  },
  confidenceFill: {
    height: '100%',
    backgroundImage: 'linear-gradient(90deg, #00BCBE, #001272)',
  },
  followUps: {
    marginTop: '16px',
    display: 'grid',
    gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
    columnGap: '10px',
    rowGap: '10px',
    '@media (max-width: 900px)': { gridTemplateColumns: '1fr' },
  },
  followUpItem: {
    paddingTop: '10px',
    paddingRight: '12px',
    paddingBottom: '10px',
    paddingLeft: '12px',
    borderTopLeftRadius: '8px',
    borderTopRightRadius: '8px',
    borderBottomRightRadius: '8px',
    borderBottomLeftRadius: '8px',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  followUpLabel: {
    color: '#00BCBE',
    fontWeight: 600,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    display: 'block',
    marginBottom: '4px',
  },
  reasonList: {
    marginTop: '14px',
    marginBottom: 0,
    paddingLeft: '18px',
    color: tokens.colorNeutralForeground2,
  },
  decisionCard: {
    marginTop: '20px',
    paddingTop: '18px',
    paddingRight: '18px',
    paddingBottom: '18px',
    paddingLeft: '18px',
    borderTopLeftRadius: '12px',
    borderTopRightRadius: '12px',
    borderBottomRightRadius: '12px',
    borderBottomLeftRadius: '12px',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  decisionRow: {
    display: 'flex',
    flexWrap: 'wrap',
    columnGap: '10px',
    rowGap: '10px',
    marginTop: '12px',
  },
  decisionMeta: {
    color: tokens.colorNeutralForeground3,
    marginTop: '8px',
    display: 'block',
  },
  activityCard: {
    marginTop: '14px',
    paddingTop: '14px',
    paddingRight: '16px',
    paddingBottom: '14px',
    paddingLeft: '16px',
    borderTopLeftRadius: '10px',
    borderTopRightRadius: '10px',
    borderBottomRightRadius: '10px',
    borderBottomLeftRadius: '10px',
    backgroundColor: tokens.colorNeutralBackground3,
  },
  activityList: {
    listStyleType: 'none',
    margin: 0,
    padding: 0,
    marginTop: '10px',
    display: 'flex',
    flexDirection: 'column',
    rowGap: '8px',
    maxHeight: '220px',
    overflowY: 'auto',
  },
  activityItem: {
    display: 'flex',
    alignItems: 'baseline',
    columnGap: '8px',
    flexWrap: 'wrap',
  },
});

interface Props {
  mode: JourneyMode;
  onNext: () => void;
  onEdit: () => void;
}

function useTypewriter(text: string, charsPerTick = 2, intervalMs = 18): { shown: string; done: boolean } {
  const [shown, setShown] = useState('');
  const [done, setDone] = useState(false);
  useEffect(() => {
    setShown('');
    setDone(false);
    if (!text) return;
    let i = 0;
    const id = window.setInterval(() => {
      i = Math.min(i + charsPerTick, text.length);
      setShown(text.slice(0, i));
      if (i >= text.length) {
        setDone(true);
        window.clearInterval(id);
      }
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [text, charsPerTick, intervalMs]);
  return { shown, done };
}

// The recommendation agent occasionally emits raw retrieval citation
// markers like "【5:0†source】" inline. They look like noise to a business
// reader — strip them and we surface the same evidence via the policy
// excerpts panel on the right.
function stripCitations(text: string): string {
  if (!text) return text;
  return text
    .replace(/\u3010[^\u3011]*?\u2020[^\u3011]*?\u3011/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/ ([.,;:!?])/g, '$1')
    .trim();
}

function rationaleBullets(text: string): string[] {
  // Show the agent's full reasoning. Truncating to 145 chars cuts mid-clause
  // and hides the policy-clause hooks the verdict actually relied on.
  return stripCitations(text)
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
}

export function Step6Recommendation({ mode, onNext, onEdit }: Props) {
  const styles = useStyles();
  const claimId = useClaimStore((s) => s.claimId);
  const { loading, error, data } = useSectionData(
    7,
    (id) => claimsdemo.recommendation(id),
    mode !== 'locked',
  );
  const { shown, done } = useTypewriter(stripCitations(data?.stream_text ?? ''));
  const [disposition, setDisposition] = useState<DispositionRecord | null>(null);
  const [dispositionLoaded, setDispositionLoaded] = useState(false);
  const [pendingDecision, setPendingDecision] = useState<DispositionDecision | null>(null);
  const [selectedDecision, setSelectedDecision] = useState<DispositionDecision | null>(null);
  const [decisionNote, setDecisionNote] = useState('');
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [siuPending, setSiuPending] = useState(false);

  useEffect(() => {
    if (!claimId || mode === 'locked') return;
    let cancelled = false;
    claimsdemo
      .getDisposition(claimId)
      .then((p) => {
        if (cancelled) return;
        setDisposition(p.disposition);
        setDispositionLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setDispositionLoaded(true);
      });
    claimsdemo
      .audit(claimId)
      .then((p) => {
        if (!cancelled) setAuditEvents(p.events);
      })
      .catch(() => {
        /* audit is non-blocking */
      });
    return () => {
      cancelled = true;
    };
  }, [claimId, mode]);

  async function refreshAudit() {
    if (!claimId) return;
    try {
      const p = await claimsdemo.audit(claimId);
      setAuditEvents(p.events);
    } catch {
      /* non-blocking */
    }
  }

  async function submitDecision(decision: DispositionDecision): Promise<boolean> {
    if (!claimId || !data) return false;
    setPendingDecision(decision);
    setDecisionError(null);
    try {
      const snapshot = {
        verdict: data.recommendation.verdict,
        confidence: data.recommendation.confidence,
        rationale: data.recommendation.rationale,
        follow_ups: data.follow_ups,
        member_policy_number: data.member_policy?.policy_number ?? null,
        guidance_section_ids: (data.guidance_excerpts ?? []).map((g) => g.id),
      };
      const res = await claimsdemo.setDisposition(
        claimId,
        decision,
        snapshot,
        decisionNote.trim() || undefined,
      );
      setDisposition(res.disposition);
      setDecisionNote('');
      void refreshAudit();
      return true;
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setPendingDecision(null);
    }
  }

  async function handleDraftLetter() {
    // If a disposition is already saved, just advance.
    if (disposition) {
      onNext?.();
      return;
    }
    if (!selectedDecision) return;
    const ok = await submitDecision(selectedDecision);
    if (ok) onNext?.();
  }

  async function reopenDecision() {
    if (!claimId) return;
    setPendingDecision('approve'); // any value just to disable buttons
    setDecisionError(null);
    try {
      await claimsdemo.clearDisposition(claimId);
      setDisposition(null);
      void refreshAudit();
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : String(err));
    } finally {
      setPendingDecision(null);
    }
  }

  async function handoffToSIU() {
    if (!claimId || !data) return;
    setSiuPending(true);
    setDecisionError(null);
    try {
      const snapshot = {
        verdict: data.recommendation.verdict,
        confidence: data.recommendation.confidence,
        rationale: data.recommendation.rationale,
        follow_ups: data.follow_ups,
        member_policy_number: data.member_policy?.policy_number ?? null,
        guidance_section_ids: (data.guidance_excerpts ?? []).map((g) => g.id),
      };
      const res = await claimsdemo.siuHandoff(
        claimId,
        snapshot,
        decisionNote.trim() || undefined,
      );
      setDisposition(res.disposition);
      setDecisionNote('');
      void refreshAudit();
      // Trigger a JSON download of the export bundle
      const blob = new Blob([JSON.stringify(res.export, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `siu-export-${claimId}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : String(err));
    } finally {
      setSiuPending(false);
    }
  }

  const decisionLabels: Record<DispositionDecision, string> = {
    approve: 'Approve',
    approve_with_conditions: 'Approve with conditions',
    decline: 'Decline',
    refer_to_siu: 'Refer to SIU',
  };
  const doneSummary = data
    ? disposition
      ? `${decisionLabels[disposition.decision]} · ${data.recommendation.verdict} (${Math.round(
          data.recommendation.confidence * 100,
        )}% confidence)`
      : `${data.recommendation.verdict} (${Math.round(
          data.recommendation.confidence * 100,
        )}% confidence)`
    : undefined;
  const bullets = data ? rationaleBullets(data.recommendation.rationale) : [];
  const fromFixture = data?.generation_source === 'fixture';

  return (
    <JourneySection
      step={6}
      techStack={fromFixture ? 'Local fixture data' : 'Foundry Agent Service · Azure AI Search · GPT-5.1'}
      techDetails={
        fromFixture
          ? 'The API is in local fixture mode because Foundry project/model configuration is not set.'
          : 'Foundry Agent Service calls GPT-5.1 with an exact member-policy lookup from member-policies-idx and advisory handling guidance retrieved from claim-policies-idx through Azure AI Search.'
      }
      title="Coverage recommendation"
      blurb="Review the recommended outcome, the member policy on file, and the guidance behind the decision."
      mode={mode}
      doneSummary={doneSummary}
      onNext={handleDraftLetter}
      onEdit={onEdit}
      nextLabel={
        pendingDecision !== null
          ? 'Saving decision…'
          : disposition
            ? 'Draft customer letter'
            : 'Save decision & draft letter'
      }
      nextDisabled={
        loading ||
        !!error ||
        !done ||
        pendingDecision !== null ||
        siuPending ||
        (!disposition && !selectedDecision)
      }
    >
      {loading && <SectionLoading label="Preparing recommendation…" />}
      {error && <SectionError message={error} />}
      {!loading && !error && data && (
        <>
          <Card className={styles.verdictCard}>
            <div style={{ display: 'flex', alignItems: 'center', columnGap: '12px', flexWrap: 'wrap' }}>
              <Subtitle1>{data.recommendation.verdict}</Subtitle1>
              <Badge appearance="tint" color="brand">
                {Math.round(data.recommendation.confidence * 100)}% confidence
              </Badge>
            </div>
            <div className={styles.confidenceBar}>
              <motion.div
                className={styles.confidenceFill}
                initial={{ width: 0 }}
                animate={{ width: `${Math.round(data.recommendation.confidence * 100)}%` }}
                transition={{ duration: 0.6 }}
              />
            </div>
            {bullets.length > 0 && (
              <ul className={styles.reasonList}>
                {bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}
              </ul>
            )}
            {data.follow_ups.length > 0 && (
              <div className={styles.followUps}>
                {data.follow_ups.map((f, i) => (
                  <div key={`${i}-${f}`} className={styles.followUpItem}>
                    <Caption1 className={styles.followUpLabel}>Action {i + 1}</Caption1>
                    <Body1>{f}</Body1>
                  </div>
                ))}
              </div>
            )}
          </Card>
          <div className={styles.grid}>
            <motion.div
              className={styles.agentCard}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <Caption1
                style={{
                  color: '#00BCBE',
                  fontWeight: 600,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                }}
              >
                Detailed rationale
              </Caption1>
              <div style={{ marginTop: '12px', lineHeight: 1.6 }}>
                <ReactMarkdown>{shown}</ReactMarkdown>
                {!done && <span className={styles.cursor} />}
              </div>
            </motion.div>
            <div>
              <Caption1
                style={{
                  color: '#00BCBE',
                  fontWeight: 600,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  marginBottom: '8px',
                  display: 'block',
                }}
              >
                Member policy on file
              </Caption1>
              <MemberPolicyCard policy={data.member_policy} />

              <Caption1
                style={{
                  color: '#00BCBE',
                  fontWeight: 600,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  marginTop: '16px',
                  marginBottom: '8px',
                  display: 'block',
                }}
              >
                Claims-handling guidance
              </Caption1>
              <div className={styles.excerpts}>
                {(data.guidance_excerpts && data.guidance_excerpts.length > 0
                  ? data.guidance_excerpts.map((g) => ({
                      id: g.id,
                      section: g.section,
                      snippet: g.snippet,
                      source_filename: g.source_filename,
                    }))
                  : data.policy_excerpts
                      .filter((px) => px.source !== 'member_policy')
                      .map((px) => ({
                        id: px.id,
                        section: px.section,
                        snippet: px.snippet,
                        source_filename: '',
                      }))
                ).map((g) => (
                  <Card key={g.id} className={styles.excerptCard}>
                    <CardHeader header={<Subtitle2>{g.section}</Subtitle2>} />
                    <div style={{ marginTop: '6px' }}>
                      <MarkdownSnippet text={g.snippet} color={tokens.colorNeutralForeground2} />
                    </div>
                    {g.source_filename && (
                      <Caption1 style={{ color: tokens.colorNeutralForeground3, marginTop: '6px', display: 'block' }}>
                        {g.source_filename}
                      </Caption1>
                    )}
                  </Card>
                ))}
              </div>
            </div>
          </div>
          <div className={styles.decisionCard}>
            <Subtitle2>Adjuster decision</Subtitle2>
            {!dispositionLoaded && (
              <Caption1 className={styles.decisionMeta}>
                Loading saved decision…
              </Caption1>
            )}
            {dispositionLoaded && disposition && (
              <>
                <div style={{ marginTop: '10px' }}>
                  <Badge appearance="filled" color="brand">
                    {decisionLabels[disposition.decision]}
                  </Badge>
                </div>
                <Caption1 className={styles.decisionMeta}>
                  Decided by {disposition.decided_by} ·{' '}
                  {new Date(disposition.decided_at).toLocaleString(undefined, {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                  })}
                </Caption1>
                {disposition.note && (
                  <Body1 style={{ marginTop: '8px' }}>“{disposition.note}”</Body1>
                )}
                <Caption1 className={styles.decisionMeta}>
                  Decision basis saved: {disposition.snapshot.verdict}{' '}
                  ({Math.round(disposition.snapshot.confidence * 100)}%
                  {disposition.snapshot.member_policy_number
                    ? ` · ${disposition.snapshot.member_policy_number}`
                    : ''}
                  )
                </Caption1>
                <div className={styles.decisionRow}>
                  <Button
                    appearance="subtle"
                    size="small"
                    disabled={pendingDecision !== null || siuPending}
                    onClick={reopenDecision}
                  >
                    Reopen decision
                  </Button>
                  <Button
                    appearance="outline"
                    size="small"
                    disabled={siuPending || pendingDecision !== null}
                    onClick={handoffToSIU}
                  >
                    {siuPending ? 'Handing off…' : 'Hand off to SIU & export'}
                  </Button>
                </div>
              </>
            )}
            {dispositionLoaded && !disposition && (
              <>
                <Caption1 className={styles.decisionMeta}>
                  Record the adjuster outcome before drafting the customer letter.
                  The recommendation will be saved with the decision.
                </Caption1>
                <Textarea
                  value={decisionNote}
                  onChange={(_, d) => setDecisionNote(d.value)}
                  placeholder="Optional note for the file (e.g. supporting reasoning, conditions to attach)…"
                  rows={2}
                  style={{ marginTop: '10px', width: '100%' }}
                />
                <Caption1 className={styles.decisionMeta}>
                  Pick a decision, then click <strong>Save decision &amp; draft
                  letter</strong> below to record it and continue.
                </Caption1>
                <div className={styles.decisionRow}>
                  {(['approve', 'approve_with_conditions', 'decline', 'refer_to_siu'] as DispositionDecision[]).map(
                    (d) => (
                      <Button
                        key={d}
                        appearance={selectedDecision === d ? 'primary' : 'secondary'}
                        size="medium"
                        disabled={pendingDecision !== null || siuPending}
                        onClick={() => setSelectedDecision(d)}
                      >
                        {decisionLabels[d]}
                      </Button>
                    ),
                  )}
                </div>
              </>
            )}
            {decisionError && (
              <Caption1 style={{ color: '#C5093B', marginTop: '8px', display: 'block' }}>
                {decisionError}
              </Caption1>
            )}
          </div>
          <div className={styles.activityCard}>
            <Subtitle2>Activity</Subtitle2>
            {auditEvents.length === 0 ? (
              <Caption1 className={styles.decisionMeta}>
                No activity recorded yet.
              </Caption1>
            ) : (
              <ul className={styles.activityList}>
                {[...auditEvents].reverse().map((ev) => (
                  <li key={ev.id} className={styles.activityItem}>
                    <Badge appearance="tint" color={auditBadgeColor(ev.type)} size="small">
                      {auditLabel(ev.type)}
                    </Badge>
                    <Body1 style={{ color: tokens.colorNeutralForeground2 }}>
                      {auditDescribe(ev)}
                    </Body1>
                    <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                      {ev.by} ·{' '}
                      {new Date(ev.at).toLocaleString(undefined, {
                        month: 'short',
                        day: 'numeric',
                        hour: 'numeric',
                        minute: '2-digit',
                      })}
                    </Caption1>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </JourneySection>
  );
}

function statusColor(status: string): 'success' | 'danger' | 'warning' | 'informative' {
  const s = (status || '').toUpperCase();
  if (s === 'ACTIVE') return 'success';
  if (s === 'LAPSED') return 'danger';
  if (s === 'NOT_FOUND' || s === 'UNAVAILABLE') return 'warning';
  return 'informative';
}

const AUDIT_LABELS: Record<string, string> = {
  claim_created: 'Claim opened',
  summary_saved: 'Summary saved',
  attested: 'Summary attested',
  recommendation_saved: 'Recommendation saved',
  letter_drafted: 'Letter drafted',
  fraud_ack: 'Risk acknowledged',
  fraud_unack: 'Risk un-acknowledged',
  disposition_set: 'Decision recorded',
  disposition_cleared: 'Decision reopened',
  marked_for_siu: 'Marked for SIU',
  siu_exported: 'SIU bundle exported',
};

function prettyEventLabel(type: string): string {
  return type
    .split('_')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');
}

function auditLabel(type: string): string {
  return AUDIT_LABELS[type] ?? prettyEventLabel(type);
}

function auditBadgeColor(type: string): 'brand' | 'success' | 'warning' | 'danger' | 'informative' {
  if (type === 'fraud_ack' || type === 'disposition_set' || type === 'attested') return 'success';
  if (type === 'marked_for_siu' || type === 'siu_exported') return 'warning';
  if (type === 'disposition_cleared' || type === 'fraud_unack') return 'informative';
  if (type === 'claim_created' || type === 'summary_saved' || type === 'recommendation_saved' || type === 'letter_drafted') return 'informative';
  return 'brand';
}

function auditDescribe(ev: AuditEvent): string {
  const p = (ev.payload ?? {}) as Record<string, unknown>;
  switch (ev.type) {
    case 'fraud_ack':
    case 'fraud_unack': {
      const fid = typeof p.finding_id === 'string' ? p.finding_id : 'finding';
      return ev.type === 'fraud_ack' ? `Acknowledged ${fid}` : `Cleared ack on ${fid}`;
    }
    case 'disposition_set': {
      const dec = typeof p.decision === 'string' ? p.decision : '';
      const label = AUDIT_DECISION_LABELS[dec] ?? dec;
      return label ? `Set to ${label}` : 'Set decision';
    }
    case 'disposition_cleared':
      return 'Cleared decision';
    case 'marked_for_siu':
      return 'Sent to Special Investigations Unit';
    case 'siu_exported': {
      const n = typeof p.ack_count === 'number' ? p.ack_count : 0;
      return `Export bundle generated (${n} ack${n === 1 ? '' : 's'})`;
    }
    case 'claim_created':
      return 'Claim file opened';
    case 'summary_saved':
      return 'Adjuster saved the claim summary';
    case 'attested':
      return 'Adjuster attested the summary is accurate';
    case 'recommendation_saved':
      return 'AI recommendation persisted to the file';
    case 'letter_drafted':
      return 'Customer outcome letter drafted';
    default:
      return prettyEventLabel(ev.type);
  }
}

const AUDIT_DECISION_LABELS: Record<string, string> = {
  approve: 'Approve',
  approve_with_conditions: 'Approve with conditions',
  decline: 'Decline',
  refer_to_siu: 'Refer to SIU',
};

const useMarkdownSnippetStyles = makeStyles({
  root: {
    fontSize: '14px',
    lineHeight: 1.5,
    '& p': { margin: '4px 0' },
    '& p:first-child': { marginTop: 0 },
    '& p:last-child': { marginBottom: 0 },
    '& ul, & ol': { margin: '4px 0', paddingLeft: '20px' },
    '& li': { margin: '2px 0' },
    '& strong': { fontWeight: 600 },
    '& code': {
      fontFamily: 'monospace',
      fontSize: '13px',
      backgroundColor: tokens.colorNeutralBackground2,
      padding: '1px 4px',
      borderRadius: '3px',
    },
    '& table': {
      borderCollapse: 'collapse',
      margin: '6px 0',
      fontSize: '13px',
      width: '100%',
    },
    '& th, & td': {
      borderTopWidth: '1px',
      borderTopStyle: 'solid',
      borderTopColor: tokens.colorNeutralStroke2,
      borderBottomWidth: '1px',
      borderBottomStyle: 'solid',
      borderBottomColor: tokens.colorNeutralStroke2,
      padding: '4px 8px',
      textAlign: 'left',
    },
    '& th': { fontWeight: 600, backgroundColor: tokens.colorNeutralBackground2 },
    '& h1, & h2, & h3, & h4': {
      fontSize: '14px',
      fontWeight: 600,
      margin: '6px 0 2px',
    },
  },
});

function MarkdownSnippet({ text, color }: { text: string; color?: string }) {
  const styles = useMarkdownSnippetStyles();
  return (
    <div className={styles.root} style={color ? { color } : undefined}>
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
}

function MemberPolicyCard({ policy }: { policy: MemberPolicySnapshot | undefined }) {
  if (!policy || (!policy.policy_number && !policy.status)) {
    return (
      <Card style={{ paddingTop: '12px', paddingRight: '12px', paddingBottom: '12px', paddingLeft: '12px' }}>
        <Body1 style={{ color: tokens.colorNeutralForeground3 }}>
          No member policy found for this claim.
        </Body1>
      </Card>
    );
  }
  const deductible = typeof policy.applicable_deductible === 'number'
    ? `$${policy.applicable_deductible.toLocaleString()}`
    : '—';
  return (
    <Card style={{ paddingTop: '14px', paddingRight: '14px', paddingBottom: '14px', paddingLeft: '14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', columnGap: '8px', flexWrap: 'wrap', marginBottom: '8px' }}>
        <Subtitle2>{policy.policy_number || 'No matching policy'}</Subtitle2>
        <Badge appearance="filled" color={statusColor(policy.status)}>
          {policy.status || 'UNKNOWN'}
        </Badge>
        {policy.in_force_at_loss && (
          <Badge appearance="tint" color="success">In force at DOL</Badge>
        )}
      </div>
      {policy.form_version && (
        <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
          Form {policy.form_version}
        </Caption1>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: '12px', rowGap: '6px', marginTop: '10px' }}>
        <div>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Applicable coverage</Caption1>
          <Body1>{policy.applicable_coverage || '—'}</Body1>
        </div>
        <div>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>Deductible</Caption1>
          <Body1>{deductible}</Body1>
        </div>
      </div>
      {policy.applicable_endorsements && policy.applicable_endorsements.length > 0 && (
        <div style={{ marginTop: '10px' }}>
          <Caption1 style={{ color: tokens.colorNeutralForeground3, display: 'block', marginBottom: '4px' }}>
            Applicable endorsements
          </Caption1>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {policy.applicable_endorsements.map((e) => (
              <Badge key={e} appearance="outline" color="informative">{e}</Badge>
            ))}
          </div>
        </div>
      )}
      {policy.policy_excerpts && policy.policy_excerpts.length > 0 && (
        <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', rowGap: '8px' }}>
          {policy.policy_excerpts.map((px) => (
            <div
              key={px.id}
              style={{
                paddingTop: '8px',
                paddingRight: '10px',
                paddingBottom: '8px',
                paddingLeft: '10px',
                backgroundColor: tokens.colorNeutralBackground2,
                borderRadius: '6px',
              }}
            >
              <Caption1 style={{ color: tokens.colorNeutralForeground2, fontWeight: 600, display: 'block' }}>
                {px.section}
              </Caption1>
              <MarkdownSnippet text={px.snippet} color={tokens.colorNeutralForeground2} />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
