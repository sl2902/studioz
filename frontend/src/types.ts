export interface PersonaOption {
  key: string;
  name: string;
  title: string;
}

export interface PersonaOptions {
  screenwriter: PersonaOption[];
  director: PersonaOption[];
}

export interface PitchRequest {
  pitch: string;
  film_type: "feature" | "short";
  target_runtime_minutes: number | null;
  screenwriter_persona: string;
  director_persona: string;
  force: boolean;
  bypass_cache: boolean;
}

export interface SearchResultCitation {
  title: string;
  url: string;
  snippet: string;
}

export interface GroundingCitations {
  budget_comps: SearchResultCitation[];
  market_trends: SearchResultCitation[];
  ip_clearance: SearchResultCitation[];
}

export interface StoryboardFrame {
  frame_number: number;
  narrative_beat: string | null;
  scene_description: string;
  camera_angle: string;
  imagen_prompt: string;
  image_path: string | null;
  image_url: string | null;
  inspection_passed: boolean;
  inspection_issues: string[] | null;
}

export interface Storyboard {
  title: string;
  frames: StoryboardFrame[];
}

export interface ExecutiveReview {
  greenlight: boolean;
  summary: string;
  estimated_budget_millions: number;
  target_demographic: string;
  finacial_risks: string[];
  required_script_notes: string[];
}

export interface Treatment {
  title: string;
  genre: string;
  logline: string;
  full_synopsis: string;
  scene_one_script: string;
  estimated_runtime_minutes: number;
}

export interface LedgerEntry {
  step_name: string;
  model: string;
  latency_seconds: number;
  estimated_cost_usd: number;
  success: boolean;
}

export interface LedgerTotals {
  total_latency_seconds: number;
  total_cost_usd: number;
}

export interface JobResult {
  treatment: Treatment;
  executive_review: ExecutiveReview;
  storyboard: Storyboard | null;
  grounding_citations: GroundingCitations | null;
  ledger_summary: string;
  ledger_entries: LedgerEntry[];
  ledger_totals: LedgerTotals;
}

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  created_at: string;
  result: JobResult | null;
  error: string | null;
  current_stage: string | null;
  regenerated_from: string | null;
  video_job_id: string | null;
  video_url: string | null;
  video_status: JobStatus | null;
}

export interface VideoJobResult {
  video_url: string;
}
