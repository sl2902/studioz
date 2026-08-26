import type { PersonaOptions, PitchRequest, JobResponse } from "./types";

// API base URL: empty string for same-origin (dev w/ Vite proxy), or set via env var for deployed backend
const BASE = import.meta.env.VITE_API_BASE_URL || "";

// Exported for components that need to prefix static asset URLs
export const API_BASE = BASE;

/** Playback rate for TTS narration audio (explainer + walkthrough). Does NOT affect the final rendered video. */
export const NARRATION_PLAYBACK_RATE = 1.5;

/** Prefix a backend-relative static URL (e.g. /static/...) with the API base. */
export function staticUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path; // already absolute
  return `${BASE}${path}`;
}

export async function fetchExplainerAudio(): Promise<{ steps: any[]; all_cached: boolean }> {
  const res = await fetch(`${BASE}/api/demo/explainer-audio`);
  if (!res.ok) throw new Error(`Failed to fetch explainer audio: ${res.status}`);
  return res.json();
}

export async function fetchPersonas(): Promise<PersonaOptions> {
  const res = await fetch(`${BASE}/api/personas`);
  if (!res.ok) throw new Error(`Failed to fetch personas: ${res.status}`);
  return res.json();
}

export async function submitPitch(request: PitchRequest): Promise<{ job_id: string; cached: boolean }> {
  const res = await fetch(`${BASE}/api/pitch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || JSON.stringify(err));
  }
  return res.json();
}

export async function fetchJobStatus(jobId: string): Promise<JobResponse> {
  const res = await fetch(`${BASE}/api/status/${jobId}`);
  if (!res.ok) throw new Error(`Failed to fetch status: ${res.status}`);
  return res.json();
}

export async function renderVideo(jobId: string): Promise<{ job_id: string }> {
  const res = await fetch(`${BASE}/api/render-video/${jobId}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || JSON.stringify(err));
  }
  return res.json();
}

export async function regenerateStoryboard(
  jobId: string,
  directorPersona: string
): Promise<{ job_id: string }> {
  const res = await fetch(`${BASE}/api/regenerate-storyboard/${jobId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ director_persona: directorPersona }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || JSON.stringify(err));
  }
  return res.json();
}

const GOLDEN_DEMO_CACHE_KEY = "studioz_golden_demo";

export async function fetchGoldenDemo(): Promise<any> {
  // Return cached data if available (session-scoped, clears on tab close)
  const cached = sessionStorage.getItem(GOLDEN_DEMO_CACHE_KEY);
  if (cached) {
    return JSON.parse(cached);
  }

  const res = await fetch(`${BASE}/api/demo/golden`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "No golden demo available");
  }
  const data = await res.json();

  // Cache for the duration of this browser session
  try {
    sessionStorage.setItem(GOLDEN_DEMO_CACHE_KEY, JSON.stringify(data));
  } catch {
    // sessionStorage full or unavailable — proceed without caching
  }

  return data;
}

export async function fetchWalkthroughAudio(): Promise<{ audio_url: string; job_id: string } | null> {
  const res = await fetch(`${BASE}/api/demo/walkthrough-audio`);
  if (!res.ok) return null;
  return res.json();
}

export async function setGoldenDemo(jobId: string): Promise<any> {
  const res = await fetch(`${BASE}/api/demo/set-golden/${jobId}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to set golden demo");
  }
  return res.json();
}
