import type { PersonaOptions, PitchRequest, JobResponse } from "./types";

const BASE = "";

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

export async function fetchGoldenDemo(): Promise<any> {
  const res = await fetch(`${BASE}/api/demo/golden`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "No golden demo available");
  }
  return res.json();
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
