import {
  Body1,
  Button,
  Card,
  CardHeader,
  Caption1,
  LargeTitle,
  Spinner,
  Subtitle1,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowRight20Regular,
  ArrowUpload20Regular,
  Delete16Regular,
  DocumentMultiple24Regular,
} from '@fluentui/react-icons';
import { InteractionStatus } from '@azure/msal-browser';
import { useMsal } from '@azure/msal-react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useClaimStore, type ClaimState } from '../store/claimStore';
import { autoSubmitClaim, claimsdemo } from '../api/apiClient';
import { loginRequest } from '../auth/msalConfig';

const PENDING_START_KEY = 'claimsDemo.pendingStart';
const MAX_FILES = 10;
const MAX_FILE_BYTES = 20 * 1024 * 1024; // mirror server APP_CPS_MAX_FILESIZE_MB=20

const useStyles = makeStyles({
  root: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: '48px',
    paddingRight: '48px',
    paddingBottom: '48px',
    paddingLeft: '48px',
    backgroundImage:
      'radial-gradient(ellipse at top, rgba(0,188,190,0.10), transparent 60%), radial-gradient(ellipse at bottom right, rgba(255,207,3,0.08), transparent 60%)',
  },
  hero: {
    maxWidth: '760px',
    width: '100%',
    paddingTop: '40px',
    paddingRight: '40px',
    paddingBottom: '40px',
    paddingLeft: '40px',
    borderTopWidth: '1px',
    borderRightWidth: '1px',
    borderBottomWidth: '1px',
    borderLeftWidth: '1px',
    borderTopStyle: 'solid',
    borderRightStyle: 'solid',
    borderBottomStyle: 'solid',
    borderLeftStyle: 'solid',
    borderTopColor: tokens.colorNeutralStroke2,
    borderRightColor: tokens.colorNeutralStroke2,
    borderBottomColor: tokens.colorNeutralStroke2,
    borderLeftColor: tokens.colorNeutralStroke2,
    borderTopLeftRadius: '16px',
    borderTopRightRadius: '16px',
    borderBottomRightRadius: '16px',
    borderBottomLeftRadius: '16px',
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow28,
  },
  eyebrow: {
    color: '#00BCBE',
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    marginBottom: '12px',
  },
  title: {
    color: tokens.colorNeutralForeground1,
    marginBottom: '16px',
  },
  subtitle: {
    color: tokens.colorNeutralForeground2,
    marginBottom: '24px',
    lineHeight: 1.55,
  },
  scenarioCard: {
    marginBottom: '20px',
    paddingTop: '16px',
    paddingRight: '20px',
    paddingBottom: '16px',
    paddingLeft: '20px',
  },
  dropzone: {
    marginBottom: '16px',
    paddingTop: '28px',
    paddingRight: '24px',
    paddingBottom: '28px',
    paddingLeft: '24px',
    borderTopLeftRadius: '12px',
    borderTopRightRadius: '12px',
    borderBottomRightRadius: '12px',
    borderBottomLeftRadius: '12px',
    borderTopWidth: '1px',
    borderRightWidth: '1px',
    borderBottomWidth: '1px',
    borderLeftWidth: '1px',
    borderTopStyle: 'dashed',
    borderRightStyle: 'dashed',
    borderBottomStyle: 'dashed',
    borderLeftStyle: 'dashed',
    borderTopColor: tokens.colorNeutralStroke2,
    borderRightColor: tokens.colorNeutralStroke2,
    borderBottomColor: tokens.colorNeutralStroke2,
    borderLeftColor: tokens.colorNeutralStroke2,
    backgroundColor: tokens.colorNeutralBackground2,
    textAlign: 'center',
    cursor: 'pointer',
    transitionProperty: 'border-color, background-color',
    transitionDuration: '0.15s',
  },
  dropzoneActive: {
    borderTopColor: '#00BCBE',
    borderRightColor: '#00BCBE',
    borderBottomColor: '#00BCBE',
    borderLeftColor: '#00BCBE',
    backgroundColor: 'rgba(0,188,190,0.08)',
  },
  fileList: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: '6px',
    marginBottom: '20px',
  },
  fileRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: '6px',
    paddingRight: '10px',
    paddingBottom: '6px',
    paddingLeft: '10px',
    borderTopLeftRadius: '6px',
    borderTopRightRadius: '6px',
    borderBottomRightRadius: '6px',
    borderBottomLeftRadius: '6px',
    backgroundColor: tokens.colorNeutralBackground3,
  },
  cta: {
    display: 'flex',
    columnGap: '12px',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  ctaPrimary: {
    backgroundColor: '#FFCF03',
    color: '#001272',
    fontWeight: 600,
    borderTopColor: '#FFCF03',
    borderRightColor: '#FFCF03',
    borderBottomColor: '#FFCF03',
    borderLeftColor: '#FFCF03',
    ':hover': {
      backgroundColor: '#FFD933',
      color: '#001272',
      borderTopColor: '#FFD933',
      borderRightColor: '#FFD933',
      borderBottomColor: '#FFD933',
      borderLeftColor: '#FFD933',
    },
  },
});

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function LandingPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { instance, accounts, inProgress } = useMsal();
  const account = accounts[0];
  const setClaimId = useClaimStore((s: ClaimState) => s.setClaimId);
  const setIntake = useClaimStore((s: ClaimState) => s.setIntake);
  const reset = useClaimStore((s: ClaimState) => s.reset);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const dragDepthRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Window-level guard: without this, dropping a file anywhere outside the
  // dropzone causes the browser to navigate to the file (and the SPA is
  // gone). Also seems to make some browsers more reliably fire `drop` on
  // the dropzone itself when the user releases near its edge.
  useEffect(() => {
    const prevent = (e: DragEvent) => {
      e.preventDefault();
    };
    window.addEventListener('dragover', prevent);
    window.addEventListener('drop', prevent);
    return () => {
      window.removeEventListener('dragover', prevent);
      window.removeEventListener('drop', prevent);
    };
  }, []);

  // DataTransfer can carry files via either `files` (most browsers) or
  // `items` (when dragged from some apps / when the OS only exposes
  // entries). Read both, dedup by name+size.
  const filesFromDataTransfer = useCallback(
    (dt: DataTransfer | null): File[] => {
      if (!dt) return [];
      const out: File[] = [];
      if (dt.files && dt.files.length) {
        for (const f of Array.from(dt.files)) out.push(f);
      }
      if (out.length === 0 && dt.items && dt.items.length) {
        for (const item of Array.from(dt.items)) {
          if (item.kind === 'file') {
            const f = item.getAsFile();
            if (f) out.push(f);
          }
        }
      }
      return out;
    },
    [],
  );

  const totalBytes = useMemo(
    () => files.reduce((sum, f) => sum + f.size, 0),
    [files],
  );

  const addFiles = useCallback((incoming: FileList | File[]) => {
    setError(null);
    const list = Array.from(incoming);
    const oversize = list.find((f) => f.size > MAX_FILE_BYTES);
    if (oversize) {
      setError(`"${oversize.name}" exceeds the 20 MB limit.`);
      return;
    }
    setFiles((prev) => {
      const next = [...prev];
      for (const f of list) {
        if (next.length >= MAX_FILES) break;
        if (!next.some((existing) => existing.name === f.name && existing.size === f.size)) {
          next.push(f);
        }
      }
      return next;
    });
  }, []);

  const removeFile = useCallback((idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const submitFiles = useCallback(async () => {
    if (files.length === 0) return;
    setSubmitting(true);
    setError(null);
    setStatusText('Uploading claim files…');
    try {
      reset();
      const res = await autoSubmitClaim(files);
      setClaimId(res.claim_id);
      setIntake(res);
      setStatusText('Opening claim review…');
      navigate('/journey');
    } catch (err) {
      console.error('autoSubmit failed:', err);
      setError(err instanceof Error ? err.message : 'Failed to submit claim');
      setStatusText(null);
    } finally {
      setSubmitting(false);
    }
  }, [files, navigate, reset, setClaimId, setIntake]);

  const handleSubmit = useCallback(async () => {
    if (!account) {
      sessionStorage.setItem(PENDING_START_KEY, 'submit');
      await instance.loginRedirect(loginRequest);
      return;
    }
    await submitFiles();
  }, [account, instance, submitFiles]);

  const startSampleClaim = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    setStatusText('Preparing sample claim…');
    try {
      reset();
      const res = await claimsdemo.start();
      setClaimId(res.claim_id);
      setIntake(null);
      navigate('/journey');
    } catch (err) {
      console.error('claimsdemo.start failed:', err);
      setError(err instanceof Error ? err.message : 'Failed to start sample claim');
      setStatusText(null);
    } finally {
      setSubmitting(false);
    }
  }, [navigate, reset, setClaimId, setIntake]);

  const handleSampleClaim = useCallback(async () => {
    if (!account) {
      sessionStorage.setItem(PENDING_START_KEY, 'sample');
      await instance.loginRedirect(loginRequest);
      return;
    }
    await startSampleClaim();
  }, [account, instance, startSampleClaim]);

  // Resume the last-intent action after a sign-in redirect.
  useEffect(() => {
    if (account && inProgress === InteractionStatus.None) {
      const pending = sessionStorage.getItem(PENDING_START_KEY);
      if (pending === 'sample') {
        sessionStorage.removeItem(PENDING_START_KEY);
        void startSampleClaim();
      } else if (pending === 'submit' && files.length > 0) {
        sessionStorage.removeItem(PENDING_START_KEY);
        void submitFiles();
      }
    }
  }, [account, inProgress, startSampleClaim, submitFiles, files.length]);

  return (
    <div className={styles.root}>
      <motion.div
        className={styles.hero}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
      >
        <Caption1 className={styles.eyebrow} style={{ display: 'block' }}>Microsoft Foundry · Demo</Caption1>
        <LargeTitle as="h1" className={styles.title} style={{ display: 'block' }}>
          Auto Insurance Claims Intelligence
        </LargeTitle>
        <Body1 as="p" className={styles.subtitle} style={{ display: 'block' }}>
          Upload the documents for an auto-insurance claim. Foundry-powered Content
          Understanding will auto-classify each file (claim form, police report, repair
          estimate, damage photo), then run extraction, fraud checks and a recommendation
          end-to-end.
        </Body1>

        <Card className={styles.scenarioCard}>
          <CardHeader
            image={<DocumentMultiple24Regular />}
            header={<Subtitle1 style={{ display: 'block' }}>Drop your claim documents</Subtitle1>}
            description={
              <Caption1 style={{ display: 'block' }}>
                PDF, JPG or PNG · up to {MAX_FILES} files · 20 MB each · auto-classified into the Auto Claim schema set
              </Caption1>
            }
          />
        </Card>

        <div
          className={`${styles.dropzone} ${dragOver ? styles.dropzoneActive : ''}`}
          onClick={() => fileInputRef.current?.click()}
          onDragEnter={(e) => {
            e.preventDefault();
            e.stopPropagation();
            dragDepthRef.current += 1;
            if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
            setDragOver(true);
          }}
          onDragOver={(e) => {
            // MUST preventDefault here or the browser refuses the drop.
            e.preventDefault();
            e.stopPropagation();
            if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
            if (!dragOver) setDragOver(true);
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            e.stopPropagation();
            // Use a depth counter so crossing into a child doesn't reset.
            dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
            if (dragDepthRef.current === 0) setDragOver(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            dragDepthRef.current = 0;
            setDragOver(false);
            // Try React synthetic dataTransfer first, fall back to the native
            // event. Some browsers / drag sources (e.g. dragging from another
            // browser tab) only populate one of the two.
            let dropped = filesFromDataTransfer(e.dataTransfer);
            if (dropped.length === 0) {
              dropped = filesFromDataTransfer(e.nativeEvent?.dataTransfer ?? null);
            }
            if (dropped.length) {
              addFiles(dropped);
              return;
            }
            // Diagnostics for the empty case — helps figure out unusual drag
            // sources without forcing the user to open devtools manually.
            const dt = e.dataTransfer;
            const native = e.nativeEvent?.dataTransfer;
            console.warn('[dropzone] no files extracted', {
              syntheticTypes: dt ? Array.from(dt.types) : null,
              syntheticItems: dt ? Array.from(dt.items).map((i) => ({ kind: i.kind, type: i.type })) : null,
              syntheticFilesLength: dt?.files?.length ?? null,
              nativeTypes: native ? Array.from(native.types) : null,
              nativeItems: native ? Array.from(native.items).map((i) => ({ kind: i.kind, type: i.type })) : null,
              nativeFilesLength: native?.files?.length ?? null,
            });
            setError(
              'No files detected in the drop. Try clicking the dropzone to browse instead, or drag from your file explorer (not a browser tab).',
            );
          }}
          role="button"
          tabIndex={0}
          aria-label="Upload claim documents"
        >
          <ArrowUpload20Regular />
          <Body1 style={{ display: 'block', marginTop: '8px' }}>
            Drag &amp; drop files here, or click to browse
          </Body1>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="application/pdf,image/png,image/jpeg"
            style={{ display: 'none' }}
            onChange={(e) => {
              if (e.target.files?.length) addFiles(e.target.files);
              e.target.value = '';
            }}
          />
        </div>

        {files.length > 0 && (
          <div className={styles.fileList}>
            {files.map((f, idx) => (
              <div className={styles.fileRow} key={`${f.name}:${f.size}:${idx}`}>
                <Caption1>
                  {f.name} · {formatBytes(f.size)}
                </Caption1>
                <Button
                  appearance="subtle"
                  size="small"
                  icon={<Delete16Regular />}
                  aria-label={`Remove ${f.name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(idx);
                  }}
                  disabled={submitting}
                />
              </div>
            ))}
            <Caption1 style={{ opacity: 0.7 }}>
              {files.length} file{files.length === 1 ? '' : 's'} · {formatBytes(totalBytes)}
            </Caption1>
          </div>
        )}

        <div className={styles.cta}>
          <Button
            appearance="primary"
            size="large"
            iconPosition="after"
            icon={submitting ? <Spinner size="tiny" /> : <ArrowRight20Regular />}
            onClick={handleSubmit}
            disabled={submitting || inProgress !== InteractionStatus.None || files.length === 0}
            className={styles.ctaPrimary}
          >
            {submitting
              ? statusText ?? 'Submitting…'
              : account
              ? 'Auto-classify & analyze'
              : 'Sign in to upload'}
          </Button>
          <Button
            appearance="secondary"
            size="large"
            onClick={handleSampleClaim}
            disabled={submitting || inProgress !== InteractionStatus.None}
          >
            Use sample claim
          </Button>
          <Body1 style={{ opacity: 0.6 }}>~3 min walkthrough</Body1>
        </div>
        {error && (
          <Body1
            role="alert"
            style={{ marginTop: '16px', color: tokens.colorPaletteRedForeground1 }}
          >
            {error}
          </Body1>
        )}
      </motion.div>
    </div>
  );
}
