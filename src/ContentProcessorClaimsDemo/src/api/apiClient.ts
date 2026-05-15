import { InteractionRequiredAuthError } from '@azure/msal-browser';
import { apiTokenRequest, loginRequest, msalInstance } from '../auth/msalConfig';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

async function getToken(): Promise<string> {
  const account = msalInstance.getActiveAccount() ?? msalInstance.getAllAccounts()[0];
  if (!account) {
    await msalInstance.loginRedirect(loginRequest);
    throw new Error('Sign-in required');
  }
  try {
    const result = await msalInstance.acquireTokenSilent({ ...apiTokenRequest, account });
    return result.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      await msalInstance.acquireTokenRedirect(apiTokenRequest);
    }
    throw err;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${method} ${path} failed: ${res.status} ${text}`);
  }
  // Some endpoints return empty
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

// ---- Real claim processor passthrough (used by Step 1 only) ----
export const claimprocessor = {
  submit: (payload: unknown) => request<{ claim_id: string }>('POST', '/claimprocessor/submit', payload),
  status: (claimId: string) => request('GET', `/claimprocessor/status/${claimId}`),
};

// ---- Real async intake ----------------------------------------------------
// Uploads N files and returns the real claim id once raw blobs and the
// manifest exist. Classification/extraction continue server-side and are
// shown by the journey as they arrive.
export interface AutoSubmitFile {
  file_name: string;
  mime_type: string;
  size: number;
  category: string;
  confidence: number;
  schema_id: string;
}

export interface AutoSubmitResponse {
  claim_id: string;
  schema_set_id: string;
  status?: string;
  files: AutoSubmitFile[];
}

export async function autoSubmitClaim(files: File[]): Promise<AutoSubmitResponse> {
  const token = await getToken();
  const form = new FormData();
  for (const f of files) {
    form.append('files', f, f.name);
  }
  const res = await fetch(`${API_BASE}/claimsdemo/claims/auto-submit`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`auto-submit failed: ${res.status} ${text}`);
  }
  return (await res.json()) as AutoSubmitResponse;
}

// ---- Claims-demo router (FastAPI: src/ContentProcessorAPI/app/routers/claimsdemo.py) ----
import type {
  AuditPayload,
  BusinessCheck,
  DemoClassification,
  DemoDocument,
  DispositionDecision,
  DispositionPayload,
  DispositionSnapshot,
  EmailDraftPayload,
  EntitiesPayload,
  FraudAcksPayload,
  FraudCheckPayload,
  RecommendationPayload,
  SIUHandoffResponse,
  SummaryPayload,
} from './types';

export const claimsdemo = {
  start: () =>
    request<{ claim_id: string; schema_set_id?: string; status?: string; files?: AutoSubmitFile[] }>(
      'POST',
      '/claimsdemo/claims/start',
    ),
  documents: (claimId: string) =>
    request<{ claim_id: string; documents: DemoDocument[] }>(
      'GET',
      `/claimsdemo/claims/${claimId}/documents`,
    ),
  classification: (claimId: string) =>
    request<{ claim_id: string; classification: DemoClassification[] }>(
      'GET',
      `/claimsdemo/claims/${claimId}/classification`,
    ),
  entities: (claimId: string) =>
    request<EntitiesPayload>('GET', `/claimsdemo/claims/${claimId}/entities`),
  fraudCheck: (claimId: string) =>
    request<FraudCheckPayload>('GET', `/claimsdemo/claims/${claimId}/fraud-check`),
  fraudAcks: (claimId: string) =>
    request<FraudAcksPayload>('GET', `/claimsdemo/claims/${claimId}/fraud-acks`),
  setFraudAck: (claimId: string, finding_id: string, acknowledged: boolean, note?: string) =>
    request<FraudAcksPayload>(
      'POST',
      `/claimsdemo/claims/${claimId}/fraud-acks`,
      { finding_id, acknowledged, note },
    ),
  businessChecks: (claimId: string) =>
    request<{ claim_id: string; checks: BusinessCheck[] }>(
      'GET',
      `/claimsdemo/claims/${claimId}/business-checks`,
    ),
  getSummary: (claimId: string) =>
    request<SummaryPayload>('GET', `/claimsdemo/claims/${claimId}/summary`),
  putSummary: (claimId: string, payload: Record<string, unknown>) =>
    request<{ claim_id: string; saved: boolean; summary: Record<string, unknown> }>(
      'PUT',
      `/claimsdemo/claims/${claimId}/summary`,
      payload,
    ),
  recommendation: (claimId: string) =>
    request<RecommendationPayload>('POST', `/claimsdemo/claims/${claimId}/recommendation`),
  getDisposition: (claimId: string) =>
    request<DispositionPayload>('GET', `/claimsdemo/claims/${claimId}/disposition`),
  setDisposition: (
    claimId: string,
    decision: DispositionDecision,
    snapshot: DispositionSnapshot,
    note?: string,
  ) =>
    request<DispositionPayload>(
      'POST',
      `/claimsdemo/claims/${claimId}/disposition`,
      { decision, snapshot, note },
    ),
  clearDisposition: (claimId: string) =>
    request<DispositionPayload>('DELETE', `/claimsdemo/claims/${claimId}/disposition`),
  audit: (claimId: string) =>
    request<AuditPayload>('GET', `/claimsdemo/claims/${claimId}/audit`),
  siuHandoff: (
    claimId: string,
    snapshot: DispositionSnapshot,
    note?: string,
  ) =>
    request<SIUHandoffResponse>(
      'POST',
      `/claimsdemo/claims/${claimId}/siu`,
      { snapshot, note },
    ),
  emailDraft: (claimId: string) =>
    request<EmailDraftPayload>('GET', `/claimsdemo/claims/${claimId}/email-draft`),
  emailSend: (claimId: string, payload: Record<string, unknown>) =>
    request<{ claim_id: string; queued: boolean; delivery_id: string }>(
      'POST',
      `/claimsdemo/claims/${claimId}/email-send`,
      payload,
    ),
  emailStatus: (claimId: string) =>
    request<{ claim_id: string; queued: { delivery_id: string; queued_at: string; to: string; subject: string } | null }>(
      'GET',
      `/claimsdemo/claims/${claimId}/email-status`,
    ),
  /** Fetch the originally uploaded file (by manifest filename) as a Blob
   * and return an object URL. Works as soon as the upload finishes — does
   * not require the workflow to have produced a process_id yet. */
  fileBlobUrl: async (claimId: string, fileName: string): Promise<string> => {
    const token = await getToken();
    const res = await fetch(
      `${API_BASE}/claimsdemo/claims/${encodeURIComponent(claimId)}/files/${encodeURIComponent(fileName)}/raw`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!res.ok) {
      throw new Error(`raw fetch failed: ${res.status}`);
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
};

// ---- Real content-processor passthrough (used by Step 1 doc preview) ----
// Reuses the existing /contentprocessor/* endpoints — no new server routes
// needed. The raw original blob is fetched as a Blob (so it can be shown
// in an <iframe>/<img>), the processed result returns the structured
// fields and the layout text the workflow extracted.
export const contentprocessor = {
  /** Fetch the original uploaded file as a Blob and return an object URL.
   * Caller is responsible for revoking it via URL.revokeObjectURL. */
  rawBlobUrl: async (processId: string): Promise<string> => {
    const token = await getToken();
    const res = await fetch(
      `${API_BASE}/contentprocessor/processed/files/${encodeURIComponent(processId)}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!res.ok) {
      throw new Error(`raw fetch failed: ${res.status}`);
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
  /** Full processed result document for a single file (includes
   * `result.fields`, `result.text`, etc.) */
  processed: (processId: string) =>
    request<Record<string, unknown>>(
      'GET',
      `/contentprocessor/processed/${encodeURIComponent(processId)}`,
    ),
};
