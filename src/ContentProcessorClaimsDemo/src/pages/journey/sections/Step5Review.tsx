import {
  Body1,
  Caption1,
  Checkbox,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useEffect, useState } from 'react';
import { JourneySection } from '../../../components/journey/JourneySection';
import { SectionError, SectionLoading } from '../../../components/journey/SectionStatus';
import { claimsdemo } from '../../../api/apiClient';
import { useSectionData } from '../../../api/useSectionData';
import { useClaimStore } from '../../../store/claimStore';
import type { JourneyMode } from '../../../components/journey/JourneySection';

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    gridTemplateColumns: '1.4fr 1fr',
    columnGap: '20px',
    '@media (max-width: 900px)': { gridTemplateColumns: '1fr' },
  },
  column: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '12px',
  },
  columnTitle: {
    color: '#00BCBE',
    fontWeight: 600,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
  },
  markdown: {
    color: tokens.colorNeutralForeground1,
    lineHeight: 1.55,
  },
  facts: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '10px',
  },
  saved: {
    color: '#31C85A',
    marginTop: '6px',
  },
  focusList: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '10px',
  },
  focusItem: {
    paddingTop: '10px',
    paddingRight: '12px',
    paddingBottom: '10px',
    paddingLeft: '12px',
    borderTopLeftRadius: '8px',
    borderTopRightRadius: '8px',
    borderBottomRightRadius: '8px',
    borderBottomLeftRadius: '8px',
    backgroundColor: tokens.colorNeutralBackground2,
    color: tokens.colorNeutralForeground2,
  },
});

interface Props {
  mode: JourneyMode;
  onNext: () => void;
  onEdit: () => void;
}

function humanLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\busd\b/i, 'USD')
    .replace(/^\w/, (c) => c.toUpperCase());
}

function adjusterFocus(markdown: string): string[] {
  const text = markdown.toLowerCase();
  const focus: string[] = [];
  if (/date of loss|loss date|incident date/.test(text) && /discrep|differ|mismatch/.test(text)) {
    focus.push('Reconcile the reported date of loss before settlement.');
  }
  if (/left|right|photo|damage side|damaged side/.test(text) && /damage|photo/.test(text)) {
    focus.push('Confirm the damage photos match the claimed vehicle and impact area.');
  }
  if (/estimate|deductible|repair/.test(text)) {
    focus.push('Validate the approved repair estimate and deductible impact.');
  }
  if (/injur/.test(text)) {
    focus.push('Confirm whether any injuries or third-party exposures exist.');
  }
  return focus.length > 0 ? focus.slice(0, 4) : ['Review key fields, inconsistencies, and missing evidence before requesting the decision.'];
}

function summaryFingerprint(markdown: string, facts: Record<string, string | number>): string {
  return JSON.stringify({
    markdown,
    facts: Object.entries(facts).sort(([left], [right]) => left.localeCompare(right)),
  });
}

export function Step5Review({ mode, onNext, onEdit }: Props) {
  const styles = useStyles();
  const claimId = useClaimStore((s) => s.claimId);
  const completed = useClaimStore((s) => s.completed);
  const setData = useClaimStore((s) => s.setData);
  const clearData = useClaimStore((s) => s.clearData);
  const reopenFrom = useClaimStore((s) => s.reopenFrom);
  const { loading, error, data } = useSectionData(
    6,
    (id) => claimsdemo.getSummary(id),
    mode !== 'locked',
  );

  const [markdown, setMarkdown] = useState<string>('');
  const [facts, setFacts] = useState<Record<string, string | number>>({});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [attested, setAttested] = useState(false);

  const [fingerprintAtAttest, setFingerprintAtAttest] = useState<string>('');
  const currentFingerprint = summaryFingerprint(markdown, facts);
  const loadedFingerprint = data ? summaryFingerprint(data.markdown, data.key_facts) : '';
  const attestationStillValid = attested && currentFingerprint === fingerprintAtAttest;

  useEffect(() => {
    if (data) {
      setMarkdown(data.markdown);
      setFacts(data.key_facts);
      setAttested(false);
      setFingerprintAtAttest('');
    }
  }, [data]);

  const handleSave = async () => {
    if (!claimId) return;
    setSaving(true);
    setSaveError(null);
    try {
      const summaryChanged = currentFingerprint !== loadedFingerprint;
      await claimsdemo.putSummary(claimId, {
        markdown,
        key_facts: facts,
        attested: attestationStillValid,
      });
      if (summaryChanged && completed.has(6)) {
        await claimsdemo.clearDisposition(claimId);
      }
      setData(6, { claim_id: claimId, markdown, key_facts: facts });
      if (summaryChanged) {
        clearData([7, 8]);
        reopenFrom(6);
      }
      setSavedAt(Date.now());
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save summary');
      throw err;
    } finally {
      setSaving(false);
    }
  };

  const handleNext = async () => {
    await handleSave();
    onNext();
  };

  return (
    <JourneySection
      step={5}
      techStack="Microsoft Agent Framework · GPT-5.1"
      techDetails="The claim summary is produced by the workflow with Microsoft Agent Framework and GPT-5.1, then held here for adjuster review and edits before a decision is requested."
      title="Adjuster review"
      blurb="Review the claim summary and key facts before requesting a recommended decision."
      mode={mode}
      doneSummary={data ? 'Summary reviewed and saved' : undefined}
      onNext={handleNext}
      onEdit={onEdit}
      nextLabel="Save and request decision"
      nextDisabled={loading || !!error || saving || !attestationStillValid}
    >
      {loading && <SectionLoading label="Loading summary…" />}
      {error && <SectionError message={error} />}
      {!loading && !error && data && (
        <div className={styles.grid}>
          <div className={styles.column}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <Caption1 className={styles.columnTitle}>Claim summary (editable)</Caption1>
              <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                Editable
              </Caption1>
            </div>
            <Textarea
              value={markdown}
              onChange={(_, d) => setMarkdown(d.value)}
              rows={20}
              resize="vertical"
            />
          </div>
          <div className={styles.column}>
            <Caption1 className={styles.columnTitle}>
              {Object.keys(facts).length > 0 ? 'Key facts' : 'Adjuster focus'}
            </Caption1>
            {Object.keys(facts).length > 0 ? (
              <div className={styles.facts}>
                {Object.entries(facts).map(([key, value]) => (
                  <Field key={key} label={humanLabel(key)}>
                    <Input
                      value={String(value)}
                      onChange={(_, d) =>
                        setFacts((f) => ({
                          ...f,
                          [key]: typeof value === 'number' ? Number(d.value) || 0 : d.value,
                        }))
                      }
                    />
                  </Field>
                ))}
              </div>
            ) : (
              <div className={styles.focusList}>
                {adjusterFocus(markdown).map((item) => (
                  <Body1 key={item} className={styles.focusItem}>{item}</Body1>
                ))}
              </div>
            )}
            {savedAt && (
              <Body1 className={styles.saved}>
                Saved at {new Date(savedAt).toLocaleTimeString()}
              </Body1>
            )}
            {saveError && (
              <MessageBar intent="error">
                <MessageBarBody>{saveError}</MessageBarBody>
              </MessageBar>
            )}
            <div
              style={{
                marginTop: '12px',
                paddingTop: '12px',
                borderTopWidth: '1px',
                borderTopStyle: 'solid',
                borderTopColor: tokens.colorNeutralStroke3,
              }}
            >
              <Checkbox
                checked={attestationStillValid}
                onChange={(_, d) => {
                  const next = !!d.checked;
                  setAttested(next);
                  setFingerprintAtAttest(next ? currentFingerprint : '');
                }}
                label={
                  <Body1>
                    I've reviewed the drafted summary against the source documents and confirm it is accurate to my knowledge.
                  </Body1>
                }
              />
              {attested && !attestationStillValid && (
                <Caption1 style={{ display: 'block', marginTop: '6px', color: tokens.colorPaletteDarkOrangeForeground1 }}>
                  Summary changed after attestation. Re-confirm before requesting a decision.
                </Caption1>
              )}
            </div>
          </div>
        </div>
      )}
    </JourneySection>
  );
}
