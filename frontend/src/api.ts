const API_BASE = "/api";

export interface Partner {
  ats: string;
  payload_type: string;
  version: number | null;
  status: string;
  pending_drafts: number;
}
export interface ExceptionRecord {
  id: string;
  ats: string;
  payload_type: string;
  payload: Record<string, unknown>;
  issues: { field: string; message: string; group?: string; rule_id?: string }[];
  mapping_version: number | null;
  status: "open" | "closed";
  owner: string | null;
  created_at: string;
  closed_at: string | null;
}
export interface ActivityRecord {
  id: string;
  ats: string;
  payload_type: string;
  status: string;
  mapping_version: number | null;
  issue_count: number;
  processed_at: string;
}
export interface FieldMapping {
  source: string;
  destination: string;
  required: boolean;
  transform: string | null;
  equivalents: Record<string, string>;
  source_is_list: boolean;
  reason: string | null;
}
export interface Abstention {
  destination: string;
  reason: string;
}
export interface MappingVersion {
  ats: string;
  payload_type: string;
  version: number;
  mappings: FieldMapping[];
  abstentions: Abstention[];
  status: string;
  proposed_by: string;
  edited_by: string[];
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
}
export interface ReplayResult {
  safe: boolean;
  checked: number;
  results: { payload: string; status: string; issues: string[] }[];
}
export interface AiUsage {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  partners_onboarded: number;
  orders_processed: number;
  recent: { model: string; input_tokens: number; output_tokens: number }[];
}
export interface DriftAlert {
  field: string;
  message: string;
  kind?: "renamed" | "removed" | "added";
  became?: string;
}
export interface ProcessResult {
  status: string;
  mapped_payload: Record<string, unknown>;
  issues: { field: string; message: string; group?: string; rule_id?: string }[];
  mapping_version: number | null;
  drift_alerts: DriftAlert[];
  processed_at: string;
}
export interface DraftResult {
  version: number;
  mappings: FieldMapping[];
  abstentions: Abstention[];
}
export interface FixturePayload {
  name: string;
  ats: string;
  payload_type: string;
  data: Record<string, unknown>;
}
export interface Sample {
  ats: string;
  label: string;
  data: Record<string, unknown>;
}
export interface ValidationRule {
  id: string;
  field: string;
  group: "Format" | "Business" | "Completeness";
  description: string;
  required: boolean;
  pattern: string | null;
  allowed_values: string[];
  check: string | null;
  enabled: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function getExceptions(): Promise<ExceptionRecord[]> {
  return request<ExceptionRecord[]>("/exceptions");
}

export async function assignException(
  recordId: string,
  owner: string,
): Promise<ExceptionRecord> {
  return request<ExceptionRecord>(`/exceptions/${recordId}/assign`, {
    method: "POST",
    body: JSON.stringify({ owner }),
  });
}

export async function closeException(
  recordId: string,
): Promise<ExceptionRecord> {
  return request<ExceptionRecord>(`/exceptions/${recordId}/close`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function runProcess(
  payload: Record<string, unknown>,
): Promise<ProcessResult> {
  return request<ProcessResult>("/process", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getPartners(): Promise<Partner[]> {
  return request<Partner[]>("/partners");
}

export function getFixtures(): Promise<FixturePayload[]> {
  return request<FixturePayload[]>("/fixtures");
}
export function parsePayload(
  text: string,
): Promise<{ payload: Record<string, unknown> }> {
  return request<{ payload: Record<string, unknown> }>("/parse", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}
export function getDestinationFields(): Promise<string[]> {
  return request<string[]>("/destination-fields");
}
export function getAiUsage(): Promise<AiUsage> {
  return request<AiUsage>("/ai-usage");
}
export function getValidationRules(ats?: string): Promise<ValidationRule[]> {
  return request<ValidationRule[]>(
    `/validation-rules${ats ? `?ats=${encodeURIComponent(ats)}` : ""}`,
  );
}
export interface PartnerSample {
  label: string;
  data: Record<string, unknown>;
}
export function remapSource(
  ats: string,
  payloadType: string,
  fromSource: string,
  toSource: string,
): Promise<{ version: number; retired_samples: number }> {
  return request(`/mappings/${ats}/${payloadType}/remap`, {
    method: "POST",
    body: JSON.stringify({ from_source: fromSource, to_source: toSource }),
  });
}
export function getPartnerSamples(ats: string): Promise<PartnerSample[]> {
  return request(`/partners/${ats}/samples`);
}
export interface SourceField {
  path: string;
  example: string | null;
}
export function getPartnerSourceFields(ats: string): Promise<SourceField[]> {
  return request(`/partners/${ats}/source-fields`);
}
export function editDraftMapping(
  ats: string,
  payloadType: string,
  version: number,
  change: {
    destination: string;
    source?: string;
    required?: boolean;
    transform?: string;
    remove?: boolean;
    edited_by?: string;
  },
): Promise<MappingVersion> {
  return request(`/mappings/${ats}/${payloadType}/${version}/mapping`, {
    method: "PATCH",
    body: JSON.stringify(change),
  });
}
export function bindValidationRule(
  ats: string,
  ruleId: string,
  changes: { enabled?: boolean; required?: boolean },
): Promise<ValidationRule> {
  return request(`/partners/${ats}/validation-rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}
export function updateValidationRule(
  id: string,
  changes: { enabled?: boolean; required?: boolean },
): Promise<ValidationRule> {
  return request<ValidationRule>(
    `/validation-rules/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(changes) },
  );
}
export function getMapping(
  ats: string,
  payloadType: string,
): Promise<MappingVersion> {
  return request<MappingVersion>(
    `/mappings/${encodeURIComponent(ats)}/${encodeURIComponent(payloadType)}`,
  );
}

export function getActivity(): Promise<ActivityRecord[]> {
  return request<ActivityRecord[]>("/activity");
}
export function draftMapping(
  ats: string,
  payloadType: string,
  payload: Record<string, unknown> | string,
  destinationFields: string[],
): Promise<DraftResult> {
  return request<DraftResult>(
    `/mappings/${encodeURIComponent(ats)}/${encodeURIComponent(payloadType)}/draft`,
    {
      method: "POST",
      body: JSON.stringify({ payload, destination_fields: destinationFields }),
    },
  );
}
export function getVersions(
  ats: string,
  payloadType: string,
): Promise<MappingVersion[]> {
  return request<MappingVersion[]>(`/mappings/${ats}/${payloadType}/versions`);
}
export function getReplay(
  ats: string,
  payloadType: string,
  version: number,
): Promise<ReplayResult> {
  return request<ReplayResult>(
    `/mappings/${ats}/${payloadType}/${version}/replay`,
  );
}
export function approveMapping(
  ats: string,
  payloadType: string,
  version: number,
  reviewer: string,
): Promise<MappingVersion> {
  return request<MappingVersion>(
    `/mappings/${ats}/${payloadType}/${version}/approve`,
    { method: "POST", body: JSON.stringify({ reviewer }) },
  );
}
