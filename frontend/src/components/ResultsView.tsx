import { useState, useEffect, useRef } from "react";
import type { JobResponse, PersonaOptions, Storyboard } from "../types";
import { renderVideo, fetchJobStatus, regenerateStoryboard, fetchPersonas, setGoldenDemo, staticUrl, NARRATION_PLAYBACK_RATE } from "../api";

interface Props {
  job: JobResponse;
  onReset: () => void;
  sourceJobId: string;
  personas: PersonaOptions | null;
  walkthroughAudioUrl?: string | null;
}

function SetAsDemoButton({ jobId }: { jobId: string }) {
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  const handleClick = async () => {
    setStatus("saving");
    try {
      await setGoldenDemo(jobId);
      setStatus("saved");
      setTimeout(() => setStatus("idle"), 3000);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={status === "saving"}
      className="text-sm text-gray-500 hover:text-emerald-400 transition-colors disabled:opacity-50"
    >
      {status === "idle" && "⭐ Set as Demo"}
      {status === "saving" && "Saving..."}
      {status === "saved" && "✓ Set as demo result"}
      {status === "error" && "✗ Failed"}
    </button>
  );
}

const VIDEO_STAGES = [
  { key: "narration", label: "Narration", icon: "📝" },
  { key: "tts", label: "TTS", icon: "🔊" },
  { key: "video_assembly", label: "Assembly", icon: "🎞️" },
];

function VideoProgressFlow({ stage }: { stage: string | null }) {
  const base = stage?.split(":")[0] || "narration";
  const detail = stage?.includes(":") ? stage.split(":").slice(1).join(":") : "";

  // Determine state for each node
  const getState = (key: string): "pending" | "active" | "complete" => {
    const idx = VIDEO_STAGES.findIndex((s) => s.key === key);
    const currentIdx = VIDEO_STAGES.findIndex((s) => s.key === base);
    if (currentIdx < 0) return idx === 0 ? "active" : "pending";
    if (idx < currentIdx) return "complete";
    if (idx === currentIdx) return "active";
    return "pending";
  };

  // Build caption
  let caption = "Starting video render...";
  if (base === "narration") caption = "Writing narration script...";
  else if (base === "tts") caption = detail ? `Generating audio for ${detail} frames...` : "Generating speech audio...";
  else if (base === "video_assembly") caption = "Compositing frames and audio into final video...";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {VIDEO_STAGES.map((s, i) => {
          const state = getState(s.key);
          return (
            <div key={s.key} className="flex items-center">
              <div className="flex flex-col items-center gap-1">
                <div
                  className={`w-9 h-9 rounded-full border-2 flex items-center justify-center text-sm transition-all duration-500 ${
                    state === "complete"
                      ? "border-emerald-600 bg-emerald-900/30 text-emerald-400"
                      : state === "active"
                      ? "border-purple-400 bg-purple-900/30 text-purple-300 animate-pulse"
                      : "border-gray-700 bg-gray-900/50 text-gray-600"
                  }`}
                >
                  {state === "complete" ? "✓" : s.icon}
                </div>
                <span className={`text-[10px] ${state === "active" ? "text-purple-300" : state === "complete" ? "text-emerald-400" : "text-gray-600"}`}>
                  {s.label}
                </span>
              </div>
              {i < VIDEO_STAGES.length - 1 && (
                <div className={`h-0.5 w-6 mx-1 -mt-4 transition-colors ${getState(VIDEO_STAGES[i + 1].key) !== "pending" ? "bg-emerald-600" : "bg-gray-700"}`} />
              )}
            </div>
          );
        })}
      </div>
      <p className="text-sm text-gray-400">{caption}</p>
    </div>
  );
}

export function ResultsView({ job, onReset, sourceJobId, personas: initialPersonas, walkthroughAudioUrl }: Props) {
  const result = job.result!;
  const review = result.executive_review;
  const storyboard = result.storyboard;
  const citations = result.grounding_citations;
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [videoJobId, setVideoJobId] = useState<string | null>(job.video_job_id || null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [videoLoading, setVideoLoading] = useState(
    job.video_status === "pending" || job.video_status === "running"
  );
  const [videoStage, setVideoStage] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  // Regeneration state
  const [personas, setPersonas] = useState<PersonaOptions | null>(initialPersonas);
  const [regenPersona, setRegenPersona] = useState("");
  const [regenJobId, setRegenJobId] = useState<string | null>(null);
  const [regenLoading, setRegenLoading] = useState(false);
  const [regenStoryboard, setRegenStoryboard] = useState<Storyboard | null>(null);
  const [regenError, setRegenError] = useState<string | null>(null);
  const [regenStage, setRegenStage] = useState<string | null>(null);
  const regenPollRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  // Load personas if not passed
  useEffect(() => {
    if (!personas) {
      fetchPersonas().then(setPersonas);
    }
  }, []);

  // Set default regen persona once loaded
  useEffect(() => {
    if (personas && !regenPersona) {
      setRegenPersona(personas.director[0]?.key || "");
    }
  }, [personas]);

  useEffect(() => {
    if (!videoJobId) return;
    pollRef.current = setInterval(async () => {
      try {
        const vJob = await fetchJobStatus(videoJobId);
        setVideoStage(vJob.current_stage);
        if (vJob.status === "completed" && vJob.result) {
          clearInterval(pollRef.current);
          setVideoUrl((vJob.result as any).video_url);
          setVideoLoading(false);
        } else if (vJob.status === "failed") {
          clearInterval(pollRef.current);
          setVideoError(vJob.error || "Video rendering failed");
          setVideoLoading(false);
        }
      } catch { /* keep polling */ }
    }, 2500);
    return () => clearInterval(pollRef.current);
  }, [videoJobId]);

  const handleRenderVideo = async () => {
    setVideoLoading(true);
    setVideoError(null);
    try {
      const { job_id } = await renderVideo(sourceJobId);
      setVideoJobId(job_id);
    } catch (err) {
      setVideoError(err instanceof Error ? err.message : "Failed to start video render");
      setVideoLoading(false);
    }
  };

  // Regeneration polling
  useEffect(() => {
    if (!regenJobId) return;
    regenPollRef.current = setInterval(async () => {
      try {
        const rJob = await fetchJobStatus(regenJobId);
        setRegenStage(rJob.current_stage);
        if (rJob.status === "completed" && rJob.result) {
          clearInterval(regenPollRef.current);
          setRegenStoryboard((rJob.result as any).storyboard);
          setRegenLoading(false);
        } else if (rJob.status === "failed") {
          clearInterval(regenPollRef.current);
          setRegenError(rJob.error || "Regeneration failed");
          setRegenLoading(false);
        }
      } catch { /* keep polling */ }
    }, 2500);
    return () => clearInterval(regenPollRef.current);
  }, [regenJobId]);

  const handleRegenerate = async () => {
    if (!regenPersona) return;
    setRegenLoading(true);
    setRegenError(null);
    setRegenStoryboard(null);
    setRegenStage(null);
    try {
      const { job_id } = await regenerateStoryboard(sourceJobId, regenPersona);
      setRegenJobId(job_id);
    } catch (err) {
      setRegenError(err instanceof Error ? err.message : "Failed to start regeneration");
      setRegenLoading(false);
    }
  };

  // Walkthrough audio auto-play (for golden demo view)
  const walkthroughAudioRef = useRef<HTMLAudioElement | null>(null);
  const videoPlayerRef = useRef<HTMLVideoElement | null>(null);

  // Preload the walkthrough audio as soon as the URL is available,
  // so it's buffered by the time the play effect fires.
  useEffect(() => {
    if (!walkthroughAudioUrl) return;
    const audio = new Audio(walkthroughAudioUrl);
    audio.preload = "auto";
    audio.load();
    walkthroughAudioRef.current = audio;
    return () => { audio.pause(); audio.src = ""; };
  }, [walkthroughAudioUrl]);
  // Section highlighting: tracks which section of the walkthrough is currently being narrated
  // Sections map to the narration script in generate_demo_audio.py:
  //   0-25%  → "consensus" (exec review summary)
  //   25-50% → "citations" (Parallel Search grounding)
  //   50-75% → "storyboard" (frame inspection)
  //   75-99% → "ledger" (cost/latency)
  //   end    → "video" (auto-play)
  const [walkthroughSection, setWalkthroughSection] = useState<
    "idle" | "consensus" | "citations" | "storyboard" | "ledger" | "video" | null
  >(walkthroughAudioUrl ? "idle" : null);
  const [walkthroughPaused, setWalkthroughPaused] = useState(false);

  const consensusRef = useRef<HTMLDivElement | null>(null);
  const citationsRef = useRef<HTMLDivElement | null>(null);
  const storyboardRef = useRef<HTMLDivElement | null>(null);
  const ledgerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!walkthroughAudioUrl) return;
    // Reuse the preloaded audio object (already buffering from the preload effect)
    const audio = walkthroughAudioRef.current;
    if (!audio) return;
    audio.playbackRate = NARRATION_PLAYBACK_RATE;
    audio.play().catch(() => {});
    setWalkthroughSection("consensus");

    // Scroll to executive consensus when narration starts
    setTimeout(() => {
      consensusRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 300);

    audio.ontimeupdate = () => {
      if (!audio.duration) return;
      const progress = audio.currentTime / audio.duration;
      if (progress < 0.25) {
        setWalkthroughSection("consensus");
      } else if (progress < 0.50) {
        setWalkthroughSection((prev) => {
          if (prev !== "citations") {
            setTimeout(() => {
              citationsRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 100);
          }
          return "citations";
        });
      } else if (progress < 0.75) {
        setWalkthroughSection((prev) => {
          if (prev !== "storyboard") {
            setTimeout(() => {
              storyboardRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 100);
          }
          return "storyboard";
        });
      } else {
        setWalkthroughSection((prev) => {
          if (prev !== "ledger") {
            // Expand the ledger table and scroll to it
            setLedgerOpen(true);
            setTimeout(() => {
              ledgerRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 100);
          }
          return "ledger";
        });
      }
    };

    audio.onended = () => {
      setWalkthroughSection("video");
      // Auto-play the video after walkthrough narration finishes
      setTimeout(() => {
        videoPlayerRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(() => {
          videoPlayerRef.current?.play().catch(() => {});
        }, 400);
      }, 500);
    };
    return () => { audio.pause(); audio.ontimeupdate = null; audio.onended = null; };
  }, [walkthroughAudioUrl]);

  function formatKey(key: string): string {
    return key.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  }

  // Walkthrough highlight ring for the section currently being narrated
  function sectionHighlight(section: "consensus" | "citations" | "storyboard" | "ledger"): string {
    if (walkthroughSection === section) {
      return "ring-2 ring-indigo-400/60 shadow-lg shadow-indigo-500/10 transition-all duration-700";
    }
    return "transition-all duration-700";
  }

  return (
    <div className="space-y-8">
      {/* Title & Greenlight */}
      <div className="text-center">
        <h2 className="text-2xl font-bold text-gray-100">{result.treatment.title}</h2>
        <p className="text-gray-400 mt-1">{result.treatment.genre} • {result.treatment.estimated_runtime_minutes} min</p>
        <div className="mt-4 inline-flex items-center gap-2">
          <span className={`inline-block w-3 h-3 rounded-full ${review.greenlight ? "bg-emerald-400" : "bg-red-400"}`} />
          <span className={`text-lg font-semibold ${review.greenlight ? "text-emerald-300" : "text-red-300"}`}>
            {review.greenlight ? "GREENLIT" : "REJECTED"}
          </span>
        </div>
      </div>

      {/* Walkthrough narration pause/play control */}
      {walkthroughSection && walkthroughSection !== "idle" && walkthroughSection !== "video" && (
        <div className="flex items-center justify-center">
          <button
            onClick={() => {
              const audio = walkthroughAudioRef.current;
              if (!audio) return;
              if (walkthroughPaused) {
                audio.play().catch(() => {});
                setWalkthroughPaused(false);
              } else {
                audio.pause();
                setWalkthroughPaused(true);
              }
            }}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-lg border border-[var(--color-border)] text-gray-300 hover:text-indigo-300 hover:border-indigo-500/50 transition-colors"
          >
            {walkthroughPaused ? (
              <>
                <span className="text-indigo-400">▶</span> Resume Walkthrough
              </>
            ) : (
              <>
                <span className="text-gray-400">⏸</span> Pause Walkthrough
              </>
            )}
          </button>
        </div>
      )}

      {/* Executive Summary */}
      <div ref={consensusRef} className={`bg-[var(--color-surface)] rounded-xl p-6 border border-[var(--color-border)] ${sectionHighlight("consensus")}`}>
        <h3 className="text-lg font-semibold text-gray-100 mb-3">Executive Consensus</h3>
        <p className="text-gray-300 text-sm leading-relaxed">{review.summary}</p>
        <div className="grid grid-cols-2 gap-4 mt-4">
          <div>
            <p className="text-xs text-gray-500 uppercase">Budget</p>
            <p className="text-gray-200 font-semibold">${review.estimated_budget_millions}M</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Target Demographic</p>
            <p className="text-gray-200 text-sm">{review.target_demographic}</p>
          </div>
        </div>
        {review.finacial_risks.length > 0 && (
          <div className="mt-4">
            <p className="text-xs text-gray-500 uppercase mb-1">Financial Risks</p>
            <ul className="text-sm text-gray-400 space-y-1">
              {review.finacial_risks.map((r, i) => <li key={i} className="flex gap-2"><span className="text-red-400">•</span>{r}</li>)}
            </ul>
          </div>
        )}
        {review.required_script_notes.length > 0 && (
          <div className="mt-4">
            <p className="text-xs text-gray-500 uppercase mb-1">Required Script Notes</p>
            <ul className="text-sm text-gray-400 space-y-1">
              {review.required_script_notes.map((n, i) => <li key={i} className="flex gap-2"><span className="text-amber-400">•</span>{n}</li>)}
            </ul>
          </div>
        )}
      </div>

      {/* Research Citations — via Parallel Search */}
      {citations && (
        <div ref={citationsRef} className={`bg-[var(--color-surface)] rounded-xl p-6 border border-[var(--color-border)] ${sectionHighlight("citations")}`}>
          <div className="flex items-center gap-3 mb-4">
            <h3 className="text-lg font-semibold text-gray-100">Research Citations</h3>
            <span className="px-2 py-0.5 text-[10px] font-semibold rounded bg-indigo-900/50 text-indigo-300 border border-indigo-700">
              via Parallel Search API
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              { label: "Budget Comparables", items: citations.budget_comps },
              { label: "Market Trends", items: citations.market_trends },
              { label: "IP Clearance", items: citations.ip_clearance },
            ].map(({ label, items }) => (
              <div key={label}>
                <p className="text-sm font-medium text-gray-300 mb-2">{label}</p>
                {items.length === 0 ? (
                  <p className="text-xs text-gray-500 italic">No results available</p>
                ) : (
                  items.map((c, i) => {
                    // Skip empty/broken citations
                    if (!c.title && !c.snippet && !c.url) return null;
                    const CardTag = c.url ? "a" : "div";
                    const linkProps = c.url ? { href: c.url, target: "_blank", rel: "noopener noreferrer" } : {};
                    return (
                      <CardTag
                        key={i}
                        {...linkProps}
                        className={`block bg-[var(--color-surface-light)] rounded-lg p-3 mb-2 border border-[var(--color-border)] ${c.url ? "hover:border-indigo-500/50 transition-colors" : ""}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm text-indigo-300 font-medium truncate flex-1">
                            {c.title || "Source available"}
                          </p>
                          <span className="shrink-0 px-1.5 py-0.5 text-[9px] font-semibold rounded bg-purple-900/40 text-purple-300 border border-purple-700/50">
                            Parallel
                          </span>
                        </div>
                        {c.snippet ? (
                          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{c.snippet}</p>
                        ) : (
                          <p className="text-xs text-gray-600 mt-1 italic">Source data available</p>
                        )}
                      </CardTag>
                    );
                  })
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Storyboard */}
      {storyboard && (
        <div ref={storyboardRef} className={`bg-[var(--color-surface)] rounded-xl p-6 border border-[var(--color-border)] ${sectionHighlight("storyboard")}`}>
          <h3 className="text-lg font-semibold text-gray-100 mb-4">Storyboard: {storyboard.title}</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {storyboard.frames.map((frame) => (
              <div key={frame.frame_number} className={`bg-[var(--color-surface-light)] rounded-lg overflow-hidden border ${frame.inspection_passed === false ? "border-amber-700/60" : "border-[var(--color-border)]"}`}>
                {frame.image_url && (
                  <div className="relative">
                    <img src={staticUrl(frame.image_url) || undefined} alt={`Frame ${frame.frame_number}`} className="w-full aspect-video object-cover" />
                    {frame.inspection_passed === false && (
                      <div className="absolute top-2 right-2 px-2 py-0.5 text-[10px] font-semibold rounded bg-amber-900/80 text-amber-300 border border-amber-700 backdrop-blur-sm">
                        ⚠ Did not pass inspection
                      </div>
                    )}
                  </div>
                )}
                <div className="p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs bg-indigo-900/50 text-indigo-300 px-2 py-0.5 rounded border border-indigo-700/50">
                      {frame.narrative_beat || `Frame ${frame.frame_number}`}
                    </span>
                    <span className="text-xs text-gray-500">{frame.camera_angle}</span>
                    {frame.inspection_passed === true && (
                      <span className="text-[10px] text-emerald-500/70">✓ Verified</span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 line-clamp-3">{frame.scene_description}</p>
                  {frame.inspection_passed === false && frame.inspection_issues && (
                    <details className="mt-2">
                      <summary className="text-[10px] text-amber-400 cursor-pointer hover:text-amber-300">
                        View inspection issues ({frame.inspection_issues.length})
                      </summary>
                      <ul className="mt-1 text-[10px] text-amber-300/70 space-y-0.5 pl-3">
                        {frame.inspection_issues.map((issue, i) => (
                          <li key={i}>• {issue}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Regenerate Storyboard */}
      {storyboard && personas && (
        <div className="bg-[var(--color-surface)] rounded-xl p-6 border border-[var(--color-border)]">
          <h3 className="text-lg font-semibold text-gray-100 mb-3">Try a Different Visual Style</h3>
          <p className="text-sm text-gray-400 mb-4">
            Re-run storyboard generation with a different director persona — reuses the same approved treatment without re-running the committee.
          </p>
          <div className="flex items-end gap-3 flex-wrap">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Director Persona</label>
              <select
                value={regenPersona}
                onChange={(e) => setRegenPersona(e.target.value)}
                disabled={regenLoading}
                className="bg-[var(--color-surface-light)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
              >
                {personas.director.map((p) => (
                  <option key={p.key} value={p.key}>
                    {formatKey(p.key)} — {p.title}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={handleRegenerate}
              disabled={regenLoading || !regenPersona}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-semibold py-2 px-5 rounded-lg transition-colors text-sm"
            >
              {regenLoading ? "Regenerating..." : "Regenerate Storyboard"}
            </button>
          </div>
          {regenLoading && regenStage && (
            <p className="mt-3 text-sm text-indigo-300">
              {regenStage === "director" && "Director designing storyboard..."}
              {regenStage?.startsWith("image_generation") && `Generating images... (${regenStage})`}
            </p>
          )}
          {regenError && <p className="mt-3 text-sm text-red-400">{regenError}</p>}

          {/* Regenerated storyboard */}
          {regenStoryboard && (
            <div className="mt-6 pt-6 border-t border-[var(--color-border)]">
              <h4 className="text-md font-semibold text-gray-200 mb-3">
                Regenerated Storyboard
                <span className="ml-2 text-xs bg-purple-900/50 text-purple-300 px-2 py-0.5 rounded border border-purple-700/50">
                  {formatKey(regenPersona)} style
                </span>
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {regenStoryboard.frames.map((frame) => (
                  <div key={frame.frame_number} className="bg-[var(--color-surface-light)] rounded-lg overflow-hidden border border-[var(--color-border)]">
                    {frame.image_url && (
                      <img src={staticUrl(frame.image_url) || undefined} alt={`Frame ${frame.frame_number}`} className="w-full aspect-video object-cover" />
                    )}
                    <div className="p-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs bg-purple-900/50 text-purple-300 px-2 py-0.5 rounded border border-purple-700/50">
                          {frame.narrative_beat || `Frame ${frame.frame_number}`}
                        </span>
                        <span className="text-xs text-gray-500">{frame.camera_angle}</span>
                      </div>
                      <p className="text-xs text-gray-400 line-clamp-3">{frame.scene_description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Video Rendering */}
      {storyboard && (
        <div className="bg-[var(--color-surface)] rounded-xl p-6 border border-[var(--color-border)]">
          <h3 className="text-lg font-semibold text-gray-100 mb-4">Narrated Video</h3>

          {/* Video already exists (from parent job or this session) */}
          {(videoUrl || job.video_url) && (
            <div>
              <video ref={videoPlayerRef} src={staticUrl(videoUrl || job.video_url) || undefined} controls className="w-full max-w-2xl rounded-lg border border-[var(--color-border)]" />
              <button
                onClick={handleRenderVideo}
                disabled={videoLoading}
                className="mt-3 px-3 py-1.5 text-xs rounded-lg border border-[var(--color-border)] text-gray-500 hover:text-gray-300 hover:border-gray-500 transition-colors disabled:opacity-50"
              >
                Re-render video
              </button>
            </div>
          )}

          {/* No video yet, not loading */}
          {!videoUrl && !job.video_url && !videoLoading && !videoError && (
            <button onClick={handleRenderVideo} className="bg-purple-600 hover:bg-purple-500 text-white font-semibold py-2 px-5 rounded-lg transition-colors">
              Generate Narrated Video
            </button>
          )}

          {/* Loading */}
          {videoLoading && (
            <VideoProgressFlow stage={videoStage} />
          )}

          {/* Error */}
          {videoError && (
            <div>
              <p className="text-red-400 text-sm mb-2">{videoError}</p>
              <button onClick={handleRenderVideo} className="text-sm text-indigo-400 hover:text-indigo-300 underline">
                Try again
              </button>
            </div>
          )}
        </div>
      )}

      {/* Ledger Table (collapsible) */}
      {result.ledger_entries && result.ledger_entries.length > 0 && (
        <div ref={ledgerRef} className={`bg-[var(--color-surface)] rounded-xl border border-[var(--color-border)] overflow-hidden ${sectionHighlight("ledger")}`}>
          <button
            onClick={() => setLedgerOpen(!ledgerOpen)}
            className="w-full p-4 text-left text-sm text-gray-400 hover:text-gray-300 flex items-center justify-between"
          >
            <span>
              Cost/Latency Ledger
              <span className="ml-2 text-xs text-gray-500">
                ({result.ledger_totals.total_latency_seconds}s • ${result.ledger_totals.total_cost_usd.toFixed(2)})
              </span>
            </span>
            <span>{ledgerOpen ? "▼" : "▶"}</span>
          </button>
          {ledgerOpen && (
            <div className="px-4 pb-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b border-[var(--color-border)]">
                    <th className="text-left py-2 pr-4 font-medium">Step</th>
                    <th className="text-left py-2 pr-4 font-medium">Model</th>
                    <th className="text-right py-2 pr-4 font-medium">Latency</th>
                    <th className="text-right py-2 pr-4 font-medium">Cost</th>
                    <th className="text-center py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {result.ledger_entries.map((entry, i) => {
                    // Detect retries: same step_name appearing multiple times
                    const isRetry = i > 0 && result.ledger_entries.slice(0, i).some(
                      (prev) => prev.step_name === entry.step_name
                    );
                    return (
                      <tr
                        key={i}
                        className={`border-b border-[var(--color-border)]/30 ${isRetry ? "bg-amber-900/10" : ""}`}
                      >
                        <td className="py-1.5 pr-4 text-gray-300">
                          {entry.step_name}
                          {isRetry && (
                            <span className="ml-1 text-[9px] text-amber-400 font-medium">(retry)</span>
                          )}
                        </td>
                        <td className="py-1.5 pr-4 text-gray-500 font-mono truncate max-w-[140px]">
                          {entry.model}
                        </td>
                        <td className="py-1.5 pr-4 text-right text-gray-400 font-mono">
                          {entry.latency_seconds}s
                        </td>
                        <td className="py-1.5 pr-4 text-right text-gray-400 font-mono">
                          ${entry.estimated_cost_usd.toFixed(4)}
                        </td>
                        <td className="py-1.5 text-center">
                          {entry.success ? (
                            <span className="text-emerald-400">✓</span>
                          ) : (
                            <span className="text-red-400">✗</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t border-[var(--color-border)] font-semibold">
                    <td className="py-2 pr-4 text-gray-200">TOTAL</td>
                    <td className="py-2 pr-4"></td>
                    <td className="py-2 pr-4 text-right text-gray-200 font-mono">
                      {result.ledger_totals.total_latency_seconds}s
                    </td>
                    <td className="py-2 pr-4 text-right text-gray-200 font-mono">
                      ${result.ledger_totals.total_cost_usd.toFixed(4)}
                    </td>
                    <td></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="text-center pt-4 flex items-center justify-center gap-6">
        <button onClick={onReset} className="text-indigo-400 hover:text-indigo-300 underline text-sm">
          ← Submit another pitch
        </button>
        {sourceJobId !== "golden-demo" && (
          <SetAsDemoButton jobId={sourceJobId} />
        )}
      </div>
    </div>
  );
}
