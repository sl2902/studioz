import { useState, useEffect, useCallback } from "react";

/**
 * Manual-advance pipeline explainer — same visual flowchart as the real
 * ProgressView but driven by a local script array, not API polling.
 * Advances via Next button, spacebar, or right arrow. Back via button or left arrow.
 */

interface ExplainerStep {
  stage: string;
  caption: string;
  committeeMembers?: string[]; // which members are "done" at this step
}

const SCRIPT: ExplainerStep[] = [
  { stage: "screenwriter", caption: "The Screenwriter Agent drafts a script treatment from the pitch — generating title, logline, synopsis, and a sample scene." },
  { stage: "grounding", caption: "Parallel Search API queries real data: box office comparables, market trends, and IP/legal precedent from sources like Box Office Mojo, Variety, and IMDb." },
  { stage: "committee", caption: "Three specialist agents review concurrently, each grounded by the Parallel Search results...", committeeMembers: [] },
  { stage: "committee:cfo_done", caption: "CFO (Budget) review complete — assessed financial viability against real market comparables.", committeeMembers: ["cfo"] },
  { stage: "committee:creative_exec_done", caption: "Creative Executive review complete — evaluated market fit and originality against current trends.", committeeMembers: ["cfo", "creative_exec"] },
  { stage: "committee:legal_counsel_done", caption: "Legal Counsel review complete — checked IP clearance, rating risk, and regulatory concerns.", committeeMembers: ["cfo", "creative_exec", "legal_counsel"] },
  { stage: "consensus", caption: "Committee Chair synthesizes all three reviews into a final Executive Review — weighing financial risk, creative upside, and legal constraints." },
  { stage: "gate", caption: "Greenlight decision: does the pitch pass the committee? If not greenlit, force-override can still proceed to storyboard generation." },
  { stage: "director", caption: "The Director Agent generates a visual storyboard — framing each narrative beat as a camera shot, respecting the chosen visual style (cinematic or stick-figure explainer)." },
  { stage: "image_generation:generating:1/3", caption: "Generating storyboard frame 1 of 3 via Gemini 3 Pro Image..." },
  { stage: "image_generation:inspecting:1/3", caption: "Frame 1: running automated quality inspection (checking style constraints, text leaks, composition)..." },
  { stage: "image_generation:passed:1/3", caption: "Frame 1: passed inspection ✓" },
  { stage: "image_generation:generating:2/3", caption: "Generating storyboard frame 2 of 3..." },
  { stage: "image_generation:passed:2/3", caption: "Frame 2: passed inspection ✓" },
  { stage: "image_generation:generating:3/3", caption: "Generating storyboard frame 3 of 3..." },
  { stage: "image_generation:passed:3/3", caption: "Frame 3: passed inspection ✓ — all frames complete." },
  // Video render sub-stages
  { stage: "narration", caption: "Narrator Agent writes a table-read narration script with character dialogue and audio tags..." },
  { stage: "tts:3", caption: "Gemini TTS generates per-frame audio — narrator voice (Kore) + character voices (split single-speaker calls for reliable distinct voices)." },
  { stage: "video_assembly", caption: "FFmpeg composites storyboard frames timed to narration audio into the final .mp4 video." },
  { stage: "completed", caption: "Pipeline complete — script treatment, committee review, storyboard frames, and narrated video all generated." },
];

// Reuse the same visual constants as ProgressView
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

function getNodeStates(currentBase: string): Record<string, NodeState> {
  const states: Record<string, NodeState> = {};
  let found = false;
  for (const s of STAGES) {
    if (s.key === currentBase) {
      states[s.key] = "active";
      found = true;
    } else if (!found) {
      states[s.key] = "complete";
    } else {
      states[s.key] = "pending";
    }
  }
  if (!found && currentBase === "completed") {
    for (const s of STAGES) states[s.key] = "complete";
  }
  return states;
}

interface Props {
  onExit: () => void;
}

export function ExplainerView({ onExit }: Props) {
  const [stepIdx, setStepIdx] = useState(0);
  const step = SCRIPT[stepIdx];
  const base = step.stage.split(":")[0];

  const next = useCallback(() => setStepIdx((i) => Math.min(i + 1, SCRIPT.length - 1)), []);
  const prev = useCallback(() => setStepIdx((i) => Math.max(i - 1, 0)), []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); next(); }
      if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [next, prev]);

  const states = getNodeStates(base);
  const committeeDone = new Set(step.committeeMembers || []);
  // If past committee, mark all done
  const AFTER_COMMITTEE = ["consensus", "gate", "director", "image_generation", "narration", "tts", "video_assembly", "completed"];
  if (AFTER_COMMITTEE.includes(base)) {
    COMMITTEE_MEMBERS.forEach((m) => committeeDone.add(m.key));
  }
  const committeeActive = base === "committee";

  return (
    <div className="max-w-5xl mx-auto py-10">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-xl font-semibold text-gray-100">Pipeline Architecture Explainer</h2>
        <button onClick={onExit} className="text-sm text-gray-500 hover:text-gray-300">
          ✕ Exit
        </button>
      </div>

      {/* Flowchart */}
      <div className="flex items-start justify-center flex-wrap gap-y-6 mb-8">
        {STAGES.map((s, i) => (
          <div key={s.key} className="flex items-start">
            <div className="flex flex-col items-center gap-1.5 transition-all duration-500">
              <div className={`w-11 h-11 rounded-full border-2 flex items-center justify-center text-base transition-all duration-500 ${
                states[s.key] === "complete" ? "border-emerald-600 bg-emerald-900/30 text-emerald-400" :
                states[s.key] === "active" ? "border-indigo-400 bg-indigo-900/40 text-indigo-300 shadow-lg shadow-indigo-500/20 scale-110 animate-pulse" :
                "border-gray-700 bg-gray-900/50 text-gray-600"
              }`}>
                {states[s.key] === "complete" ? "✓" : s.icon}
              </div>
              <span className={`text-[10px] ${states[s.key] === "active" ? "text-indigo-300 font-medium" : states[s.key] === "complete" ? "text-emerald-400" : "text-gray-600"}`}>
                {s.label}
              </span>
              {/* Committee sub-nodes */}
              {s.key === "committee" && (
                <div className="relative mt-2 pt-2">
                  <svg className="absolute top-0 left-0 w-full h-2 overflow-visible" aria-hidden="true">
                    <line x1="50%" y1="0" x2="50%" y2="4" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
                    <line x1="15%" y1="4" x2="85%" y2="4" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
                    <line x1="15%" y1="4" x2="15%" y2="8" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
                    <line x1="50%" y1="4" x2="50%" y2="8" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
                    <line x1="85%" y1="4" x2="85%" y2="8" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
                  </svg>
                  <div className="flex gap-2 justify-center pt-1">
                    {COMMITTEE_MEMBERS.map((m) => {
                      const isDone = committeeDone.has(m.key);
                      const isActive = committeeActive && !isDone;
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
        <p className="text-sm text-gray-200 leading-relaxed max-w-2xl">{step.caption}</p>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-center gap-4 mt-6">
        <button
          onClick={prev}
          disabled={stepIdx === 0}
          className="px-4 py-2 text-sm rounded-lg border border-[var(--color-border)] text-gray-400 hover:text-gray-200 hover:border-gray-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          ← Back
        </button>
        <span className="text-xs text-gray-600 font-mono">
          {stepIdx + 1} / {SCRIPT.length}
        </span>
        <button
          onClick={next}
          disabled={stepIdx === SCRIPT.length - 1}
          className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          Next →
        </button>
      </div>
      <p className="text-center text-[10px] text-gray-600 mt-3">
        Use ← → arrow keys or spacebar to advance
      </p>
    </div>
  );
}
