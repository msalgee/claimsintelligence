import {
  Button,
  Caption1,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Send20Filled } from '@fluentui/react-icons';
import { useEffect, useState } from 'react';
import { JourneySection } from '../../../components/journey/JourneySection';
import { SectionError, SectionLoading } from '../../../components/journey/SectionStatus';
import { claimsdemo } from '../../../api/apiClient';
import { useSectionData } from '../../../api/useSectionData';
import { useClaimStore } from '../../../store/claimStore';
import type { JourneyMode } from '../../../components/journey/JourneySection';

const useStyles = makeStyles({
  card: {
    paddingTop: '20px',
    paddingRight: '20px',
    paddingBottom: '20px',
    paddingLeft: '20px',
    borderTopLeftRadius: '12px',
    borderTopRightRadius: '12px',
    borderBottomRightRadius: '12px',
    borderBottomLeftRadius: '12px',
    backgroundColor: tokens.colorNeutralBackground2,
    display: 'flex',
    flexDirection: 'column',
    rowGap: '12px',
  },
  sendRow: {
    display: 'flex',
    justifyContent: 'flex-end',
    columnGap: '8px',
    marginTop: '8px',
  },
});

interface Props {
  mode: JourneyMode;
  onNext: () => void;
  onEdit: () => void;
}

function formatCustomerActions(markdown: string): string {
  return markdown.replace(
    /(:\s*)(?:\(?1\)|1\.)\s*([^;\n]+);\s*(?:\(?2\)|2\.)\s*([^;\n]+);\s*(?:and\s*)?(?:\(?3\)|3\.)\s*([^\n.]+)(\.?)/i,
    (_match, prefix, first, second, third, ending) => (
      `${prefix.trimEnd()}\n- ${first.trim()}\n- ${second.trim()}\n- ${third.trim()}${ending || ''}`
    ),
  );
}

export function Step7Email({ mode, onNext, onEdit }: Props) {
  const styles = useStyles();
  const claimId = useClaimStore((s) => s.claimId);
  const { loading, error, data } = useSectionData(
    8,
    (id) => claimsdemo.emailDraft(id),
    mode !== 'locked',
  );

  const [to, setTo] = useState('');
  const [cc, setCc] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [sending, setSending] = useState(false);
  const [sentMessage, setSentMessage] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);

  useEffect(() => {
    if (data) {
      setTo(data.to);
      setCc(data.cc ?? '');
      setSubject(data.subject);
      setBody(formatCustomerActions(data.body));
    }
  }, [data]);

  // Re-hydrate "Email queued" from server-side sidecar so the badge survives
  // reload and the "Mark complete" button stays enabled.
  useEffect(() => {
    if (!claimId || mode === 'locked' || sentMessage) return;
    let cancelled = false;
    claimsdemo
      .emailStatus(claimId)
      .then((res) => {
        if (cancelled || !res.queued) return;
        setSentMessage(
          `Email queued for delivery (id ${res.queued.delivery_id.slice(0, 8)}…)`,
        );
      })
      .catch(() => {
        /* sidecar missing is fine */
      });
    return () => {
      cancelled = true;
    };
  }, [claimId, mode, sentMessage]);

  const handleSend = async () => {
    if (!claimId) return;
    setSending(true);
    setSendError(null);
    try {
      const res = await claimsdemo.emailSend(claimId, { to, cc, subject, body });
      setSentMessage(`Email queued for delivery (id ${res.delivery_id.slice(0, 8)}…)`);
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Failed to send');
    } finally {
      setSending(false);
    }
  };
  const fromFixture = data?.generation_source === 'fixture';

  return (
    <JourneySection
      step={7}
      techStack={fromFixture ? 'Local fixture data' : 'Foundry Agent Service · GPT-5.1'}
      techDetails={
        fromFixture
          ? 'The API is in local fixture mode because Foundry project/model configuration is not set.'
          : 'Foundry Agent Service drafts the claimant letter with GPT-5.1 using the saved adjuster decision, decision note, and customer-facing conditions.'
      }
      title="Customer letter"
      blurb="Prepare the customer update for adjuster review and sending."
      mode={mode}
      doneSummary={sentMessage ?? (data ? 'Draft ready' : undefined)}
      onNext={onNext}
      onEdit={onEdit}
      nextLabel="Mark complete"
      nextDisabled={loading || !!error || sending || !sentMessage}
    >
      {loading && <SectionLoading label="Drafting customer letter…" />}
      {error && <SectionError message={error} />}
      {!loading && !error && data && (
        <div className={styles.card}>
          <Field label="To">
            <Input value={to} onChange={(_, d) => setTo(d.value)} />
          </Field>
          <Field label="CC">
            <Input value={cc} onChange={(_, d) => setCc(d.value)} />
          </Field>
          <Field label="Subject">
            <Input value={subject} onChange={(_, d) => setSubject(d.value)} />
          </Field>
          <Field label="Body">
            <Textarea value={body} onChange={(_, d) => setBody(d.value)} rows={14} resize="vertical" />
          </Field>
          {sentMessage && (
            <MessageBar intent="success">
              <MessageBarBody>{sentMessage}</MessageBarBody>
            </MessageBar>
          )}
          {sendError && (
            <MessageBar intent="error">
              <MessageBarBody>{sendError}</MessageBarBody>
            </MessageBar>
          )}
          <div className={styles.sendRow}>
            <Caption1 style={{ alignSelf: 'center', opacity: 0.65, marginRight: 'auto' }}>
              Demo mode: queued only.
            </Caption1>
            <Button
              appearance="primary"
              icon={<Send20Filled />}
              onClick={handleSend}
              disabled={sending || !!sentMessage}
            >
              {sending ? 'Sending…' : sentMessage ? 'Sent' : 'Send'}
            </Button>
          </div>
        </div>
      )}
    </JourneySection>
  );
}
