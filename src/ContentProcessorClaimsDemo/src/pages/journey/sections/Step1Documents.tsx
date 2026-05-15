import {
  Badge,
  Body1,
  Button,
  Caption1,
  Card,
  CardHeader,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Spinner,
  Subtitle2,
  Tab,
  TabList,
  Tooltip,
  type SelectTabData,
  type SelectTabEvent,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  DocumentPdf24Regular,
  Image24Regular,
  Open16Regular,
} from '@fluentui/react-icons';
import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { JourneySection } from '../../../components/journey/JourneySection';
import { SectionError, SectionLoading } from '../../../components/journey/SectionStatus';
import { claimsdemo, contentprocessor } from '../../../api/apiClient';
import { useSectionData } from '../../../api/useSectionData';
import { useClaimStore } from '../../../store/claimStore';
import type { DemoClassification, DemoDocument } from '../../../api/types';
import type { JourneyMode } from '../../../components/journey/JourneySection';
import { DamagePhotoThumb } from '../../../components/journey/DamagePhotoThumb';
import { PdfPreview } from '../../../components/PdfPreview';

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
    columnGap: '16px',
    rowGap: '16px',
  },
  card: {
    paddingTop: '16px',
    paddingRight: '16px',
    paddingBottom: '16px',
    paddingLeft: '16px',
  },
  meta: {
    color: tokens.colorNeutralForeground3,
    marginTop: '4px',
  },
  viewBtn: {
    marginTop: '12px',
  },
  previewSurface: {
    maxWidth: '900px',
    width: '90vw',
  },
  previewBody: {
    minHeight: '480px',
  },
  previewTabPane: {
    marginTop: '12px',
    minHeight: '440px',
    maxHeight: '60vh',
    overflow: 'auto',
  },
  iframe: {
    width: '100%',
    height: '60vh',
    border: 'none',
    backgroundColor: tokens.colorNeutralBackground3,
  },
  imageWrap: {
    display: 'flex',
    justifyContent: 'center',
    backgroundColor: tokens.colorNeutralBackground3,
    padding: '12px',
  },
  pre: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: '12px',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    margin: 0,
  },
});

function isImage(name: string) {
  return /\.(jpg|jpeg|png|gif|webp)$/i.test(name);
}

type PreviewTab = 'original' | 'fields';

function FieldsTable({ fields }: { fields: Record<string, unknown> }) {
  // Flatten nested objects into dotted keys, render arrays compactly. The
  // backend `result` is the raw schema instance, e.g.
  //   { claim_number, policyholder_information: { name, address: { city }}}
  // so we collapse one level deep so the table stays readable.
  const flat: Array<[string, unknown]> = [];
  const walk = (obj: Record<string, unknown>, prefix: string) => {
    for (const [k, v] of Object.entries(obj)) {
      const key = prefix ? `${prefix}.${k}` : k;
      if (v == null || v === '') continue;
      if (Array.isArray(v)) {
        flat.push([key, v.length === 0 ? '—' : v.map((it) =>
          it && typeof it === 'object' ? JSON.stringify(it) : String(it)
        ).join(', ')]);
      } else if (typeof v === 'object') {
        walk(v as Record<string, unknown>, key);
      } else {
        flat.push([key, v]);
      }
    }
  };
  walk(fields ?? {}, '');
  if (flat.length === 0) {
    return <Caption1>No structured fields available.</Caption1>;
  }
  const prettify = (k: string) =>
    k
      .split('.')
      .map((part) => part.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))
      .join(' › ');
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
      <thead>
        <tr>
          <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: `1px solid ${tokens.colorNeutralStroke2}`, width: '40%' }}>Field</th>
          <th style={{ textAlign: 'left', padding: '6px 8px', borderBottom: `1px solid ${tokens.colorNeutralStroke2}` }}>Value</th>
        </tr>
      </thead>
      <tbody>
        {flat.map(([key, value]) => (
          <tr key={key}>
            <td style={{ padding: '6px 8px', borderBottom: `1px solid ${tokens.colorNeutralStroke3}`, verticalAlign: 'top', color: tokens.colorNeutralForeground2 }}>
              {prettify(key)}
            </td>
            <td style={{ padding: '6px 8px', borderBottom: `1px solid ${tokens.colorNeutralStroke3}`, verticalAlign: 'top' }}>
              {String(value)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface PreviewState {
  loading: boolean;
  error?: string;
  blobUrl?: string;
  fields?: Record<string, unknown>;
  text?: string;
}

function usePreview(
  claimId: string | null,
  fileName: string | undefined,
  processId: string | undefined,
): PreviewState {
  const [state, setState] = useState<PreviewState>({ loading: false });
  useEffect(() => {
    if (!claimId || !fileName) {
      setState({ loading: false });
      return;
    }
    let cancelled = false;
    let createdUrl: string | undefined;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setState({ loading: true });

    // Fetch the raw file ONCE, claim-scoped — this works the moment the
    // upload completes, regardless of whether the workflow has produced
    // a `Content_Process` record yet.
    claimsdemo
      .fileBlobUrl(claimId, fileName)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        createdUrl = url;
        setState((prev) => ({ ...prev, blobUrl: url }));
      })
      .catch((err) => {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          error: err instanceof Error ? err.message : String(err),
        }));
      });

    // Poll the processed-fields endpoint only when we have a real
    // workflow-issued process_id. The structured `result.fields` payload
    // only appears once the Extract→Map→Save pipeline finishes for this
    // doc (~30-90s after enqueue).
    if (!processId) {
      // No process_id yet — surface "extraction in progress" without
      // 404-spamming /contentprocessor/processed/{manifestId}.
      setState((prev) => ({ ...prev, loading: false }));
      return () => {
        cancelled = true;
        if (createdUrl) URL.revokeObjectURL(createdUrl);
      };
    }

    const TERMINAL_STATUSES = new Set(['completed', 'failed', 'error']);
    const POLL_MS = 2500;
    const MAX_ATTEMPTS = 72; // ~3 minutes
    const attempt = async (remaining: number) => {
      if (cancelled) return;
      const processedRes = await contentprocessor
        .processed(processId)
        .then((value) => ({ ok: true as const, value }))
        .catch((reason) => ({ ok: false as const, reason }));
      if (cancelled) return;
      const processed = processedRes.ok
        ? (processedRes.value as {
            result?: Record<string, unknown>;
            status?: string;
          })
        : undefined;
      const result = (processed?.result ?? {}) as Record<string, unknown>;
      const maybeFields = result.fields as Record<string, unknown> | undefined;
      const fields =
        maybeFields && typeof maybeFields === 'object' ? maybeFields : result;
      const fieldsCount =
        fields && typeof fields === 'object' ? Object.keys(fields).length : 0;
      const hasFields = fieldsCount > 0;
      const status = (processed?.status ?? '').toString().toLowerCase();
      const isTerminal = TERMINAL_STATUSES.has(status);
      const stop = hasFields || isTerminal || remaining <= 0;
      setState((prev) => ({
        ...prev,
        loading: !stop,
        fields,
        text: typeof result.text === 'string' ? (result.text as string) : '',
      }));
      if (!stop) {
        timer = setTimeout(() => attempt(remaining - 1), POLL_MS);
      }
    };
    attempt(MAX_ATTEMPTS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [claimId, fileName, processId]);
  return state;
}

interface Props {
  mode: JourneyMode;
  onNext: () => void;
  onEdit: () => void;
}

// Small per-card thumbnail that fetches the real uploaded image (raw blob,
// claim-scoped — works the moment upload completes) and falls back to the
// stylized DamagePhotoThumb SVG while loading or if the fetch fails. Each
// card gets its own URL with cleanup on unmount.
function DocImageThumb({
  claimId,
  fileName,
  height = 120,
}: {
  claimId: string | null;
  fileName: string;
  height?: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!claimId || !fileName) return;
    let cancelled = false;
    let created: string | undefined;
    claimsdemo
      .fileBlobUrl(claimId, fileName)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        created = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [claimId, fileName]);
  if (url && !failed) {
    return (
      <img
        src={url}
        alt={fileName}
        style={{
          width: '100%',
          height,
          objectFit: 'cover',
          display: 'block',
          borderRadius: '6px',
          backgroundColor: '#0b1620',
        }}
      />
    );
  }
  return <DamagePhotoThumb height={height} />;
}

export function Step1Documents({ mode, onNext, onEdit }: Props) {
  const styles = useStyles();
  const [openDocId, setOpenDocId] = useState<string | null>(null);
  const claimId = useClaimStore((s) => s.claimId);
  const { loading, error, data } = useSectionData(
    1,
    (id) => claimsdemo.documents(id),
    mode !== 'locked',
    // Both real uploads AND sample claims assign process_id asynchronously
    // (the workflow worker stamps it after Extract/Map). Keep polling until
    // every document has one, otherwise the per-doc Extracted-fields panel
    // can never reach the /contentprocessor/processed/{id} endpoint.
    (payload) => {
      const docs = (payload?.documents ?? []) as DemoDocument[];
      return docs.length === 0 || docs.some((d) => !d.process_id);
    },
  );
  const documents: DemoDocument[] = data?.documents ?? [];
  // Step 1 also runs classification (we previously had a separate Step 2 for
  // this; merging the two reduces journey noise since cross-referencing is
  // covered properly in Story + Risk later).
  const { loading: classificationLoading, data: classificationData } = useSectionData(
    2,
    (id) => claimsdemo.classification(id),
    mode !== 'locked',
    (payload) => {
      const classification = (payload?.classification ?? []) as DemoClassification[];
      return documents.length > 0 && classification.length < documents.length;
    },
  );
  const classifications: DemoClassification[] =
    classificationData?.classification ?? [];
  const classificationByName: Record<string, DemoClassification> =
    Object.fromEntries(classifications.map((c) => [c.file_id, c]));
  const isGenericCategory = (category: string | undefined) =>
    !category || category.toLowerCase() === 'document';
  const isClassifying = (doc: DemoDocument) =>
    mode !== 'locked' && !classificationByName[doc.name] && isGenericCategory(doc.category);
  const classificationPending =
    mode !== 'locked' &&
    documents.length > 0 &&
    (classificationLoading || documents.some((doc) => isClassifying(doc)));
  const docCount = documents.length;
  const docCountWord =
    docCount === 0
      ? 'several'
      : ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'][docCount] || String(docCount);
  const blurb = `The claim file arrived as ${docCountWord} separate document${docCount === 1 ? '' : 's'}, ready for review in one place.`;
  const doneSummary = documents.length > 0
    ? classificationPending
      ? `${documents.length} documents received · classifying`
      : `${documents.length} documents ingested`
    : undefined;
  const openDoc = documents.find((d) => d.id === openDocId) ?? null;
  const openDocClassification = openDoc ? classificationByName[openDoc.name] : undefined;
  const openDocCategory = openDoc
    ? openDocClassification?.label ?? (isClassifying(openDoc) ? 'Classifying...' : openDoc.category)
    : undefined;
  // Pass the manifest filename for raw-blob fetch (always available
  // post-upload), and the workflow-issued process_id ONLY when present —
  // never fall back to the manifest item id, which would 404-spam the
  // /contentprocessor/processed endpoint.
  const preview = usePreview(claimId, openDoc?.name, openDoc?.process_id);
  const [tab, setTab] = useState<PreviewTab>('original');
  useEffect(() => {
    if (openDocId) setTab('original');
  }, [openDocId]);

  return (
    <JourneySection
      step={1}
      techStack="Azure AI Content Understanding · Blob Storage · Storage Queue"
      techDetails="Original files are stored in Azure Blob Storage, classified and extracted with Azure AI Content Understanding, then queued for the claim workflow with Azure Storage Queue."
      title="Documents received"
      blurb={blurb}
      mode={mode}
      doneSummary={doneSummary}
      onNext={onNext}
      onEdit={onEdit}
      nextLabel="See what happened"
      nextDisabled={loading || !!error || classificationPending}
    >
      {loading && <SectionLoading label="Reading claim pack…" />}
      {error && <SectionError message={error} />}
      {!loading && !error && classificationPending && (
        <SectionLoading label="Classifying documents with Content Understanding..." />
      )}
      {!loading && !error && (
        <div className={styles.grid}>
          {documents.map((doc, idx) => {
            const cls = classificationByName[doc.name];
            const docIsClassifying = isClassifying(doc);
            const categoryLabel = cls?.label ?? (docIsClassifying ? 'Classifying...' : doc.category);
            return (
              <motion.div
                key={doc.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: idx * 0.04 }}
              >
                <Card className={styles.card}>
                  {isImage(doc.name) && (
                    <div style={{ marginBottom: '8px' }}>
                      <DocImageThumb claimId={claimId} fileName={doc.name} height={120} />
                    </div>
                  )}
                  <CardHeader
                    image={isImage(doc.name) ? <Image24Regular /> : <DocumentPdf24Regular />}
                    header={<Subtitle2>{doc.name}</Subtitle2>}
                    description={
                      <Caption1 className={styles.meta}>
                        {doc.pages} {doc.pages === 1 ? 'page' : 'pages'} · {doc.size_kb} KB
                      </Caption1>
                    }
                  />
                  <Body1
                    style={{
                      marginTop: '8px',
                      opacity: docIsClassifying ? 1 : 0.7,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    {docIsClassifying && <Spinner size="tiny" />}
                    <span>{categoryLabel}</span>
                  </Body1>
                  {(() => {
                    if (!cls) {
                      if (!docIsClassifying) return null;
                      return (
                        <div style={{ marginTop: '6px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                          <Badge appearance="outline" color="informative">
                            Content Understanding queued
                          </Badge>
                        </div>
                      );
                    }
                    const method = (cls.method ?? '').toLowerCase();
                    const variant = method.startsWith('filename')
                      ? { color: 'warning' as const, label: 'Filename match' }
                      : method.startsWith('sample')
                        ? { color: 'subtle' as const, label: 'Sample (deterministic)' }
                        : method.startsWith('content understanding')
                          ? { color: 'success' as const, label: 'Content Understanding' }
                          : method.startsWith('ai vision (foundry')
                            ? { color: 'success' as const, label: 'AI vision (Foundry)' }
                            : { color: 'success' as const, label: 'AI vision' };
                    return (
                      <div style={{ marginTop: '6px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        <Tooltip content={cls.method ?? variant.label} relationship="description">
                          <Badge appearance="outline" color={variant.color} tabIndex={0}>
                            {variant.label}
                          </Badge>
                        </Tooltip>
                      </div>
                    );
                  })()}
                  <Button
                    appearance="subtle"
                    size="small"
                    icon={<Open16Regular />}
                    className={styles.viewBtn}
                    onClick={() => setOpenDocId(doc.id)}
                  >
                    View document
                  </Button>
                </Card>
              </motion.div>
            );
          })}
        </div>
      )}

      <Dialog
        open={!!openDocId}
        onOpenChange={(_, d) => {
          if (!d.open) setOpenDocId(null);
        }}
      >
        <DialogSurface className={styles.previewSurface}>
          <DialogBody className={styles.previewBody}>
            <DialogTitle>
              {openDoc?.name ?? 'Document preview'}
              {openDoc && (
                <Caption1 style={{ display: 'block', opacity: 0.7, marginTop: '4px' }}>
                  {openDocCategory} · {openDocClassification ? 'extracted by Azure AI Content Understanding' : 'classification in progress'}
                </Caption1>
              )}
            </DialogTitle>
            <DialogContent>
              <TabList
                selectedValue={tab}
                onTabSelect={(_e: SelectTabEvent, data: SelectTabData) => setTab(data.value as PreviewTab)}
              >
                <Tab value="original">Original</Tab>
                <Tab value="fields">Extracted fields</Tab>
              </TabList>
              <div className={styles.previewTabPane}>
                {tab === 'original' && (
                  preview.blobUrl ? (
                    openDoc && isImage(openDoc.name) ? (
                      <div className={styles.imageWrap}>
                        <img src={preview.blobUrl} alt={openDoc.name} style={{ maxWidth: '100%', maxHeight: '60vh' }} />
                      </div>
                    ) : (
                      <div className={styles.iframe} style={{ overflowY: 'auto' }}>
                        <PdfPreview src={preview.blobUrl} />
                      </div>
                    )
                  ) : preview.loading ? (
                    <Spinner label="Loading original…" />
                  ) : (
                    <Caption1>Original file is not available yet — try again in a few seconds.</Caption1>
                  )
                )}
                {tab === 'fields' && (
                  preview.fields && Object.keys(preview.fields).length > 0
                    ? <FieldsTable fields={preview.fields} />
                    : preview.loading
                      ? <Spinner label="Waiting for the extraction agent to finish…" />
                      : <Caption1>No structured fields were returned for this document.</Caption1>
                )}
              </div>
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" onClick={() => setOpenDocId(null)}>Close</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </JourneySection>
  );
}
