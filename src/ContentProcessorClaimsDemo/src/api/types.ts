//
// Shared types for the /claimsdemo/... API payloads. Live agent responses and
// local fixture payloads intentionally use the same shapes.

export interface DemoDocument {
  id: string;
  name: string;
  category: string;
  pages: number;
  size_kb: number;
  // Workflow-assigned process id used to fetch the original blob and the
  // extracted result via /contentprocessor/processed/{process_id}. Falls
  // back to `id` for older payloads.
  process_id?: string;
  mime_type?: string;
}

export interface DemoClassification {
  file_id: string;
  label: string;
  confidence: number;
  method: string;
}

export interface TimelineEntry {
  date: string;
  label: string;
  source_doc: string;
}

export interface PersonEntry {
  id: string;
  role: string;
  name: string;
  contact: string;
}

export interface VehicleEntry {
  id: string;
  make: string;
  model: string;
  year: number;
  vin: string;
  registration: string;
  owner: string;
}

export interface LocationEntry {
  id: string;
  label: string;
  lat: number;
  lng: number;
}

export interface EntitiesPayload {
  claim_id: string;
  generation_source?: 'fixture';
  narrative?: string;
  watch_outs?: string[];
  timeline: TimelineEntry[];
  people: PersonEntry[];
  vehicles: VehicleEntry[];
  locations: LocationEntry[];
}

export type FraudSeverity = 'info' | 'warning' | 'critical';

export interface FraudFinding {
  id: string;
  severity: FraudSeverity;
  title: string;
  rationale: string;
  contributing_docs: string[];
}

export interface FraudCheckPayload {
  claim_id: string;
  risk_score: number;
  risk_band: string;
  findings: FraudFinding[];
}

export interface FraudAck {
  acknowledged: true;
  by: string;
  at: string;
  note?: string | null;
}

export interface FraudAcksPayload {
  claim_id: string;
  acks: Record<string, FraudAck>;
}

export type DispositionDecision =
  | 'approve'
  | 'approve_with_conditions'
  | 'decline'
  | 'refer_to_siu';

export interface DispositionSnapshot {
  verdict: string;
  confidence: number;
  rationale: string;
  follow_ups: string[];
  member_policy_number?: string | null;
  guidance_section_ids?: string[];
}

export interface DispositionRecord {
  decision: DispositionDecision;
  decided_by: string;
  decided_at: string;
  note?: string | null;
  snapshot: DispositionSnapshot;
}

export interface DispositionPayload {
  claim_id: string;
  disposition: DispositionRecord | null;
}

export type AuditEventType =
  | 'fraud_ack'
  | 'fraud_unack'
  | 'disposition_set'
  | 'disposition_cleared'
  | 'marked_for_siu'
  | 'siu_exported';

export interface AuditEvent {
  id: string;
  type: AuditEventType | string;
  at: string;
  by: string;
  payload?: Record<string, unknown>;
}

export interface AuditPayload {
  claim_id: string;
  events: AuditEvent[];
}

export interface SIUExportBundle {
  claim_id: string;
  exported_at: string;
  exported_by: string;
  disposition: DispositionRecord;
  fraud_acks: Record<string, unknown>;
  audit: AuditEvent[];
}

export interface SIUHandoffResponse {
  claim_id: string;
  disposition: DispositionRecord;
  export: SIUExportBundle;
}

export type BusinessCheckStatus = 'pass' | 'warn' | 'fail';

export interface BusinessCheck {
  id: string;
  rule: string;
  status: BusinessCheckStatus;
  summary: string;
  details: string;
}

export interface SummaryPayload {
  claim_id: string;
  markdown: string;
  key_facts: Record<string, string | number>;
}

export interface PolicyExcerpt {
  id: string;
  section: string;
  snippet: string;
  source?: 'member_policy' | 'guidance';
}

export interface GuidanceExcerpt {
  id: string;
  section: string;
  source_filename: string;
  snippet: string;
}

export interface MemberPolicySnapshot {
  policy_number: string;
  form_version: string;
  status: string;
  in_force_at_loss: boolean;
  applicable_coverage: string;
  applicable_deductible: number | null;
  applicable_endorsements: string[];
  policy_excerpts: PolicyExcerpt[];
}

export interface RecommendationVerdict {
  verdict: string;
  confidence: number;
  rationale: string;
}

export interface RecommendationPayload {
  claim_id: string;
  generation_source?: 'fixture';
  stream_text: string;
  policy_excerpts: PolicyExcerpt[];
  member_policy?: MemberPolicySnapshot;
  guidance_excerpts?: GuidanceExcerpt[];
  recommendation: RecommendationVerdict;
  follow_ups: string[];
}

export interface EmailDraftPayload {
  claim_id: string;
  generation_source?: 'fixture';
  to: string;
  cc?: string;
  subject: string;
  body: string;
}
