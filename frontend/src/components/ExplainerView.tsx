import { useState, useEffect, useCallback, useRef } from "react";
import { fetchExplainerAudio, staticUrl, NARRATION_PLAYBACK_RATE } from "../api";

/**
 * Self-narrating pipeline explainer — auto-advances as each step's
 * cached audio clip finishes playing. Manual controls still available.
 */

interface ExplainerStep {
  id: string;
  text: string;
  audio_url: string | null;
  stage: string;
  committeeMembers?: string[];
}

// Map step IDs to flowchart stage keys and committee sub-state
const STEP_STAGE_MAP: Record<string, { stage: string; committeeMembers?: string[] }> = {
  screenwriter: { stage: "screenwriter" },
  grounding: { stage: "grounding" },
  committee_cfo: { stage: "committee", committeeMembers: ["cfo"] },
  committee_creative: { stage: "committee", committeeMembers: ["cfo", "creative_exec"] },
  committee_legal: { stage: "committee", committeeMembers: ["cfo", "creative_exec", "legal_counsel"] },
  consensus: { stage: "consensus" },
  gate: { stage: "gate" },
  director: { stage: "director" },
  image_generation: { stage: "image_generation" },
  narration: { stage: "narration" },
  tts: { stage: "tts" },
  video_assembly: { stage: "video_assembly" },
};

const STAGES = [
  { key: "screenwriter", label: "Screenwriter", icon: "✍️" },
  { key: "grounding", label: "Research", icon: "🔍" },
  { key: "committee", label: "Committee", icon: "👥" },
  { key: "consensus", label: "Consensus", icon: "⚖️" },
  { key: "gate", label: "Greenlight", icon: "🚦" },
  { key: "director", label: "Director", icon: "🎬" },
  { key: "image_generation", label: "Images", icon: "🖼️" },
  { key: "narration", label: "Narration", icon: "📝" },
  { key: "tts", label: "TTS", icon: "🔊" },
  { key: "video_assembly", label: "Assembly", icon: "🎞️" },
];

const COMMITTEE_MEMBERS = [
  { key: "cfo", label: "CFO", icon: "💰" },
  { key: "creative_exec", label: "Creative", icon: "💡" },
  { key: "legal_counsel", label: "Legal", icon: "⚖️" },
];

type NodeState = "pending" | "active" | "complete";

function getNodeStates(currentStage: string): Record<string, NodeState> {
  const states: Record<string, NodeState> = {};
  let found = false;
  for (const s of STAGES) {
    if (s.key === currentStage) { states[s.key] = "active"; found = true; }
    else if (!found) { states[s.key] = "complete"; }
    else { states[s.key] = "pending"; }
  }
  // If stage not in flowchart (e.g. "intro"), all nodes are pending
  if (!found) for (const s of STAGES) states[s.key] = "pending";
  return states;
}

interface Props { onExit: () => void; }

export function ExplainerView({ onExit }: Props) {
  const [steps, setSteps] = useState<ExplainerStep[]>([]);
  const [stepIdx, setStepIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Fetch explainer audio URLs on mount
  useEffect(() => {
    fetchExplainerAudio()
      .then((data) => {
        const mapped: ExplainerStep[] = data.steps.map((s: any) => ({
          ...s,
          // Prefix audio URLs with API base so they resolve to the backend, not the frontend host
          audio_url: staticUrl(s.audio_url),
          stage: STEP_STAGE_MAP[s.id]?.stage || s.id,
          committeeMembers: STEP_STAGE_MAP[s.id]?.committeeMembers,
        }));
        setSteps(mapped);
        setLoading(false);
      })
      .catch((err) => {
        console.error("ExplainerView: failed to fetch audio", err);
        setLoading(false);
      });
  }, []);

  const currentStep = steps[stepIdx];
  const currentStage = currentStep?.stage || "screenwriter";
  const stageMapping = currentStep ? STEP_STAGE_MAP[currentStep.id] : undefined;
  const committeeDone = new Set(stageMapping?.committeeMembers || []);
  const AFTER_COMMITTEE = ["consensus", "gate", "director", "image_generation", "narration", "tts", "video_assembly"];
  if (AFTER_COMMITTEE.includes(currentStage)) {
    COMMITTEE_MEMBERS.forEach((m) => committeeDone.add(m.key));
  }

  const next = useCallback(() => {
    setStepIdx((i) => Math.min(i + 1, steps.length - 1));
  }, [steps.length]);

  const prev = useCallback(() => {
    if (audioRef.current) { audioRef.current.pause(); }
    setStepIdx((i) => Math.max(i - 1, 0));
  }, []);

  // Preload the next step's audio clip while the current one is playing/active.
  // Stores a pre-buffered Audio object keyed by step index so it's ready instantly
  // when auto-advance or manual Next triggers.
  const preloadedRef = useRef<Map<number, HTMLAudioElement>>(new Map());

  useEffect(() => {
    const nextIdx = stepIdx + 1;
    if (nextIdx >= steps.length) return;
    const nextStep = steps[nextIdx];
    if (!nextStep?.audio_url) return;
    // Don't re-preload if already cached
    if (preloadedRef.current.has(nextIdx)) return;

    const preloadAudio = new Audio(nextStep.audio_url);
    preloadAudio.preload = "auto";
    // Trigger buffering without playing
    preloadAudio.load();
    preloadedRef.current.set(nextIdx, preloadAudio);

    // Cleanup: keep at most 3 preloaded entries to avoid memory growth
    const keys = Array.from(preloadedRef.current.keys());
    for (const k of keys) {
      if (k < stepIdx - 1) {
        preloadedRef.current.delete(k);
      }
    }
  }, [stepIdx, steps]);

  // Play audio for current step
  useEffect(() => {
    if (!playing || !currentStep?.audio_url) return;

    // Use preloaded audio if available, otherwise create fresh
    let audio: HTMLAudioElement;
    if (preloadedRef.current.has(stepIdx)) {
      audio = preloadedRef.current.get(stepIdx)!;
      preloadedRef.current.delete(stepIdx);
    } else {
      audio = new Audio(currentStep.audio_url);
    }

    audioRef.current = audio;
    audio.playbackRate = NARRATION_PLAYBACK_RATE;
    audio.play().catch(() => {});
    audio.onended = () => {
      if (stepIdx < steps.length - 1) {
        setStepIdx((i) => i + 1);
      } else {
        setPlaying(false);
      }
    };
    return () => { audio.pause(); audio.onended = null; };
  }, [stepIdx, playing, currentStep?.audio_url]);

  // Keyboard controls
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); next(); }
      if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [next, prev]);

  const states = getNodeStates(currentStage);
  const isIntro = currentStep?.id === "intro";

  if (loading) return <div className="text-center text-gray-500 py-20">Loading explainer...</div>;
  if (!steps.length) return <div className="text-center text-gray-500 py-20">No explainer audio available. Run: python -m studioz.generate_demo_audio</div>;

  return (
    <div className="max-w-5xl mx-auto py-10">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-xl font-semibold text-gray-100">Pipeline Architecture Explainer</h2>
        <button onClick={onExit} className="text-sm text-gray-500 hover:text-gray-300">✕ Exit</button>
      </div>

      {isIntro ? (
        /* Pre-flowchart title card for intro */
        <div className="flex flex-col items-center justify-center py-12 mb-8">
          <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent mb-4">
            StudioZ
          </h1>
          <p className="text-gray-400 text-sm mb-8">Multi-Agent Cinema Pre-Production Studio</p>
          <div className="bg-[var(--color-surface)] rounded-xl px-8 py-6 border border-[var(--color-border)] max-w-2xl text-center">
            <p className="text-sm text-gray-200 leading-relaxed italic">
              "{currentStep?.text}"
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* Flowchart */}
          <div className="flex items-start justify-center flex-wrap gap-y-6 mb-8">
            {STAGES.map((s, i) => (
              <div key={s.key} className="flex items-start">
                <div className="flex flex-col items-center gap-1.5 transition-all duration-500">
                  <div className={`w-11 h-11 rounded-full border-2 flex items-center justify-center text-base transition-all duration-500 ${
                    states[s.key] === "complete" ? "border-emerald-600 bg-emerald-900/30 text-emerald-400" :
                    states[s.key] === "active" ? "border-indigo-400 bg-indigo-900/40 text-indigo-300 shadow-lg shadow-indigo-500/20 scale-110" :
                    "border-gray-700 bg-gray-900/50 text-gray-600"
                  }`}>
                    {states[s.key] === "complete" ? "✓" : s.icon}
                  </div>
                  <span className={`text-[10px] ${states[s.key] === "active" ? "text-indigo-300 font-medium" : states[s.key] === "complete" ? "text-emerald-400" : "text-gray-600"}`}>
                    {s.label}
                  </span>
                  {s.key === "committee" && (
                    <div className="flex gap-2 mt-2">
                      {COMMITTEE_MEMBERS.map((m) => {
                        const isDone = committeeDone.has(m.key);
                        const isActive = currentStage === "committee" && !isDone;
                        return (
                          <div key={m.key} className="flex flex-col items-center gap-0.5">
                            <div className={`w-6 h-6 rounded-full border flex items-center justify-center text-[10px] transition-all duration-500 ${
                              isDone ? "border-emerald-600 bg-emerald-900/30 text-emerald-400" :
                              isActive ? "border-indigo-400 bg-indigo-900/30 text-indigo-300 animate-pulse" :
                              "border-gray-700 bg-gray-900/50 text-gray-600"
                            }`}>
                              {isDone ? "✓" : m.icon}
                            </div>
                            <span className={`text-[9px] ${isDone ? "text-emerald-400" : isActive ? "text-indigo-300" : "text-gray-600"}`}>
                              {m.label}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
                {i < STAGES.length - 1 && (
                  <div className="flex items-center px-0.5 mt-3">
                    <div className={`h-0.5 w-4 md:w-6 transition-colors duration-500 ${states[STAGES[i + 1].key] !== "pending" ? "bg-emerald-600" : "bg-gray-700"}`} />
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Caption */}
          <div className="bg-[var(--color-surface)] rounded-xl px-8 py-5 border border-[var(--color-border)] text-center min-h-[80px] flex items-center justify-center">
            <p className="text-sm text-gray-200 leading-relaxed max-w-2xl italic">
              "{currentStep?.text}"
            </p>
          </div>
        </>
      )}

      {/* Controls */}
      <div className="flex items-center justify-center gap-4 mt-6">
        <button onClick={prev} disabled={stepIdx === 0} className="px-4 py-2 text-sm rounded-lg border border-[var(--color-border)] text-gray-400 hover:text-gray-200 disabled:opacity-30 transition-colors">
          ← Back
        </button>
        {!playing ? (
          <button onClick={() => setPlaying(true)} className="px-5 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-colors">
            ▶ Play
          </button>
        ) : (
          <button onClick={() => { setPlaying(false); audioRef.current?.pause(); }} className="px-5 py-2 text-sm rounded-lg bg-gray-700 hover:bg-gray-600 text-white font-medium transition-colors">
            ⏸ Pause
          </button>
        )}
        <button onClick={next} disabled={stepIdx === steps.length - 1} className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium disabled:opacity-30 transition-colors">
          Next →
        </button>
      </div>
      <p className="text-center text-[10px] text-gray-600 mt-3">
        {stepIdx + 1} / {steps.length} • Arrow keys to step • Space to advance
      </p>
    </div>
  );
}
