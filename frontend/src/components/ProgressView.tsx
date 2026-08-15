import { useEffect, useRef, useState } from "react";
import type { JobResponse } from "../types";
import { fetchJobStatus } from "../api";

interface Props {
  jobId: string;
  onComplete: (job: JobResponse) => void;
  onError: () => void;
}

const STAGES = [
  { key: "screenwriter", label: "Screenwriter", icon: "✍️" },
  { key: "grounding", label: "Research", icon: "🔍" },
  { key: "committee", label: "Committee", icon: "👥" },
  { key: "consensus", label: "Consensus", icon: "⚖️" },
  { key: "gate", label: "Greenlight", icon: "🚦" },
  { key: "director", label: "Director", icon: "🎬" },
  { key: "image_generation", label: "Images", icon: "🖼️" },
] as const;

type StageState = "pending" | "active" | "complete";

// Parse compound stage strings like "committee:cfo_done" or "image_generation:inspecting:2/3"
function parseStage(raw: string | null): { base: string; detail: string } {
  if (!raw) return { base: "starting", detail: "" };
  const parts = raw.split(":");
  return { base: parts[0], detail: parts.slice(1).join(":") };
}

function getStageStates(currentBase: string): Record<string, StageState> {
  const states: Record<string, StageState> = {};
  let found = false;
  for (const stage of STAGES) {
    if (stage.key === currentBase) {
      states[stage.key] = "active";
      found = true;
    } else if (!found) {
      states[stage.key] = "complete";
    } else {
      states[stage.key] = "pending";
    }
  }
  if (!found && currentBase !== "starting") {
    for (const stage of STAGES) states[stage.key] = "complete";
  }
  return states;
}

// Track which committee members are done
function getCommitteeDone(stageHistory: string[]): Set<string> {
  const done = new Set<string>();
  for (const s of stageHistory) {
    if (s.startsWith("committee:") && s.endsWith("_done")) {
      const member = s.replace("committee:", "").replace("_done", "");
      done.add(member);
    }
  }
  return done;
}

const COMMITTEE_MEMBERS = [
  { key: "cfo", label: "CFO", icon: "💰" },
  { key: "creative_exec", label: "Creative", icon: "💡" },
  { key: "legal_counsel", label: "Legal", icon: "⚖️" },
];

function CommitteeSubNodes({ done, active }: { done: Set<string>; active: boolean }) {
  return (
    <div className="relative mt-3 pt-3">
      {/* Dashed connector lines from parent to children */}
      <svg className="absolute top-0 left-0 w-full h-3 overflow-visible" aria-hidden="true">
        {/* Vertical stem from parent center */}
        <line x1="50%" y1="0" x2="50%" y2="6" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
        {/* Horizontal bar */}
        <line x1="15%" y1="6" x2="85%" y2="6" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
        {/* Three vertical drops */}
        <line x1="15%" y1="6" x2="15%" y2="12" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
        <line x1="50%" y1="6" x2="50%" y2="12" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
        <line x1="85%" y1="6" x2="85%" y2="12" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" className="text-gray-600" />
      </svg>
      <div className="flex gap-2 justify-center">
        {COMMITTEE_MEMBERS.map((m) => {
          const isDone = done.has(m.key);
          const isActive = active && !isDone;
          return (
            <div
              key={m.key}
              className={`flex flex-col items-center gap-0.5 transition-all duration-300 ${isActive ? "scale-105" : ""}`}
            >
              <div
                className={`w-7 h-7 rounded-full border flex items-center justify-center text-xs transition-all duration-500 ${
                  isDone
                    ? "border-emerald-600 bg-emerald-900/30 text-emerald-400"
                    : isActive
                    ? "border-indigo-400 bg-indigo-900/30 text-indigo-300 animate-pulse"
                    : "border-gray-700 bg-gray-900/50 text-gray-600"
                }`}
              >
                {isDone ? "✓" : m.icon}
              </div>
              <span className={`text-[10px] ${isDone ? "text-emerald-400" : isActive ? "text-indigo-300" : "text-gray-600"}`}>
                {m.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StageNode({
  label,
  icon,
  state,
  children,
}: {
  label: string;
  icon: string;
  state: StageState;
  children?: React.ReactNode;
}) {
  const ringClasses = {
    pending: "border-gray-700 bg-gray-900/50 text-gray-600",
    active: "border-indigo-400 bg-indigo-900/40 text-indigo-300 shadow-lg shadow-indigo-500/20 scale-110",
    complete: "border-emerald-600 bg-emerald-900/30 text-emerald-400",
  };
  const labelClasses = {
    pending: "text-gray-600",
    active: "text-indigo-300 font-medium",
    complete: "text-emerald-400",
  };

  return (
    <div className="flex flex-col items-center gap-1.5 transition-all duration-500">
      <div
        className={`w-12 h-12 rounded-full border-2 flex items-center justify-center text-lg ${ringClasses[state]} ${state === "active" ? "animate-pulse" : ""}`}
      >
        {state === "complete" ? "✓" : icon}
      </div>
      <span className={`text-xs ${labelClasses[state]}`}>{label}</span>
      {children}
    </div>
  );
}

function Connector({ state }: { state: "pending" | "complete" }) {
  return (
    <div className="flex items-center px-1 -mt-5">
      <div
        className={`h-0.5 w-6 md:w-8 transition-colors duration-500 ${
          state === "complete" ? "bg-emerald-600" : "bg-gray-700"
        }`}
      />
    </div>
  );
}

function buildCaption(raw: string | null): string {
  if (!raw) return "Waiting...";
  const { base, detail } = parseStage(raw);

  switch (base) {
    case "starting":
      return "Initializing pipeline...";
    case "screenwriter":
      return "Drafting script treatment...";
    case "grounding":
      return "Searching box office comps, market trends, and IP precedent via Parallel...";
    case "committee": {
      if (detail.endsWith("_done")) {
        const member = detail.replace("_done", "").replace("_", " ");
        return `${capitalize(member)} review complete`;
      }
      return "Committee members reviewing concurrently...";
    }
    case "consensus":
      return "Committee Chair synthesizing final decision...";
    case "gate":
      return "Evaluating greenlight decision...";
    case "director":
      return "Designing visual storyboard...";
    case "image_generation": {
      // detail format: "phase:frame/total" or "phase:frame/total:attempt/max"
      const parts = detail.split(":");
      const phase = parts[0];
      const frameInfo = parts[1] || "";
      const [frame, total] = frameInfo.split("/");

      switch (phase) {
        case "generating":
          return `Generating frame ${frame} of ${total}...`;
        case "inspecting":
          return `Frame ${frame}: inspecting for quality...`;
        case "passed":
          return `Frame ${frame}: passed inspection ✓`;
        case "failed":
          return `Frame ${frame}: failed inspection (keeping last version)`;
        case "retry": {
          const attemptInfo = parts[2] || "";
          const [attempt, max] = attemptInfo.split("/");
          return `Frame ${frame}: inspection failed — regenerating (attempt ${attempt}/${max})...`;
        }
        default:
          return "Generating storyboard frames...";
      }
    }
    default:
      return raw;
  }
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function ProgressView({ jobId, onComplete, onError }: Props) {
  const [stage, setStage] = useState<string | null>("starting");
  const [stageHistory, setStageHistory] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  useEffect(() => {
    const startTime = Date.now();
    timerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);

    intervalRef.current = setInterval(async () => {
      try {
        const job = await fetchJobStatus(jobId);
        const newStage = job.current_stage;
        setStage(newStage);
        if (newStage && !stageHistory.includes(newStage)) {
          setStageHistory((prev) => [...prev, newStage]);
        }

        if (job.status === "completed") {
          clearInterval(intervalRef.current);
          clearInterval(timerRef.current);
          onComplete(job);
        } else if (job.status === "failed") {
          clearInterval(intervalRef.current);
          clearInterval(timerRef.current);
          setError(job.error || "Pipeline failed");
        }
      } catch {
        // Network error, keep polling
      }
    }, 2000);

    return () => {
      clearInterval(intervalRef.current);
      clearInterval(timerRef.current);
    };
  }, [jobId]);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  if (error) {
    return (
      <div className="max-w-lg mx-auto text-center py-20">
        <div className="bg-red-900/30 border border-red-700 rounded-xl p-6 mb-6">
          <h3 className="text-lg font-semibold text-red-300 mb-2">Pipeline Failed</h3>
          <p className="text-red-400 text-sm">{error}</p>
        </div>
        <button onClick={onError} className="text-indigo-400 hover:text-indigo-300 underline">
          ← Back to form
        </button>
      </div>
    );
  }

  const { base } = parseStage(stage);
  const states = getStageStates(base);

  // Fix: if pipeline has advanced past committee, all members must be done
  // (consensus requires all 3 to complete before it can start)
  const STAGES_AFTER_COMMITTEE = ["consensus", "gate", "director", "image_generation"];
  const pastCommittee = STAGES_AFTER_COMMITTEE.includes(base) || states["committee"] === "complete";
  const committeeDone = pastCommittee
    ? new Set(COMMITTEE_MEMBERS.map((m) => m.key))
    : getCommitteeDone(stageHistory);
  const committeeActive = base === "committee";

  return (
    <div className="max-w-4xl mx-auto py-12">
      <h2 className="text-xl font-semibold text-gray-100 text-center mb-2">Pipeline Running</h2>
      <p className="text-center text-gray-500 text-sm mb-10 font-mono">{formatTime(elapsed)} elapsed</p>

      {/* Flowchart */}
      <div className="flex items-start justify-center flex-wrap gap-y-6">
        {STAGES.map((s, i) => (
          <div key={s.key} className="flex items-start">
            <StageNode label={s.label} icon={s.icon} state={states[s.key]}>
              {s.key === "committee" && (
                <CommitteeSubNodes done={committeeDone} active={committeeActive} />
              )}
            </StageNode>
            {i < STAGES.length - 1 && (
              <Connector
                state={states[STAGES[i + 1].key] === "pending" ? "pending" : "complete"}
              />
            )}
          </div>
        ))}
      </div>

      {/* Live caption */}
      <div className="mt-10 text-center">
        <div className="inline-block bg-[var(--color-surface)] rounded-xl px-6 py-3 border border-[var(--color-border)] min-w-[300px]">
          <p className="text-sm text-gray-300">{buildCaption(stage)}</p>
        </div>
      </div>

      <p className="text-center text-xs text-gray-600 mt-6 font-mono">Job {jobId.slice(0, 8)}</p>
    </div>
  );
}
