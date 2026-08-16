import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, useNavigate, useParams } from "react-router-dom";
import type { JobResponse, PersonaOptions } from "./types";
import { fetchGoldenDemo, fetchJobStatus, fetchWalkthroughAudio, staticUrl } from "./api";
import { PitchForm } from "./components/PitchForm";
import { ProgressView } from "./components/ProgressView";
import { ResultsView } from "./components/ResultsView";
import { ExplainerView } from "./components/ExplainerView";
import { CoverScreen } from "./components/CoverScreen";

const STORAGE_KEY = "studioz_active_job";

// ============================================================
// Cover Screen Route
// ============================================================

function CoverRoute() {
  const navigate = useNavigate();
  return (
    <CoverScreen
      onEnter={() => navigate("/app")}
    />
  );
}

// ============================================================
// Main App Route (pitch form + demo/explainer links)
// ============================================================

function MainRoute() {
  const navigate = useNavigate();
  const [personas, setPersonas] = useState<PersonaOptions | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [resumeJobId, setResumeJobId] = useState<string | null>(null);

  // Check for an in-progress job on mount
  useEffect(() => {
    const storedJobId = localStorage.getItem(STORAGE_KEY);
    if (storedJobId) {
      fetchJobStatus(storedJobId)
        .then((job) => {
          if (job.status === "completed" || job.status === "running" || job.status === "pending") {
            setResumeJobId(storedJobId);
          } else {
            localStorage.removeItem(STORAGE_KEY);
          }
        })
        .catch(() => {
          // Job not found — offer resume in case server restart
          setResumeJobId(storedJobId);
        });
    }
  }, []);

  const handleSubmit = (jobId: string) => {
    localStorage.setItem(STORAGE_KEY, jobId);
    navigate(`/job/${jobId}`);
  };

  const handleViewDemo = async () => {
    setDemoLoading(true);
    setDemoError(null);
    try {
      // Pre-validate that the demo exists before navigating
      await fetchGoldenDemo();
      navigate("/demo");
    } catch (err) {
      setDemoError(err instanceof Error ? err.message : "Failed to load demo");
    } finally {
      setDemoLoading(false);
    }
  };

  const handleResumeJob = (id: string) => {
    navigate(`/job/${id}`);
    setResumeJobId(null);
  };

  return (
    <AppShell>
      {/* Resume banner */}
      {resumeJobId && (
        <div className="max-w-2xl mx-auto mb-6 bg-indigo-900/20 border border-indigo-700/50 rounded-xl p-4 flex items-center justify-between">
          <p className="text-sm text-indigo-300">
            Found an in-progress job: <span className="font-mono">{resumeJobId.slice(0, 8)}...</span>
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => handleResumeJob(resumeJobId)}
              className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg"
            >
              Resume
            </button>
            <button
              onClick={() => { setResumeJobId(null); localStorage.removeItem(STORAGE_KEY); }}
              className="px-3 py-1 text-xs text-gray-400 hover:text-gray-200"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <PitchForm
        onSubmit={handleSubmit}
        personas={personas}
        setPersonas={setPersonas}
      />
      <div className="max-w-2xl mx-auto mt-8 flex items-center justify-center gap-4">
        <button
          onClick={handleViewDemo}
          disabled={demoLoading}
          className="px-4 py-2 text-sm rounded-lg border border-[var(--color-border)] text-gray-400 hover:text-indigo-300 hover:border-indigo-500/50 transition-colors disabled:opacity-50"
        >
          {demoLoading ? "Loading..." : "🎬 View Demo Result"}
        </button>
        <button
          onClick={() => navigate("/explainer")}
          className="px-4 py-2 text-sm rounded-lg border border-[var(--color-border)] text-gray-400 hover:text-purple-300 hover:border-purple-500/50 transition-colors"
        >
          📊 Pipeline Explainer
        </button>
      </div>
      {demoError && (
        <p className="text-center text-sm text-red-400 mt-3">{demoError}</p>
      )}
    </AppShell>
  );
}

// ============================================================
// Explainer Route
// ============================================================

function ExplainerRoute() {
  const navigate = useNavigate();
  return (
    <ExplainerView onExit={() => navigate("/app")} />
  );
}

// ============================================================
// Demo Result Route (golden walkthrough)
// ============================================================

function DemoRoute() {
  const navigate = useNavigate();
  const [jobResult, setJobResult] = useState<JobResponse | null>(null);
  const [walkthroughAudioUrl, setWalkthroughAudioUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchGoldenDemo(), fetchWalkthroughAudio()])
      .then(([demoData, walkthroughData]) => {
        const fakeJob: JobResponse = {
          job_id: "golden-demo",
          status: "completed",
          created_at: new Date().toISOString(),
          result: demoData,
          error: null,
          current_stage: "completed",
          regenerated_from: null,
          video_job_id: null,
          video_url: demoData.video_url || null,
          video_status: demoData.video_url ? "completed" : null,
        };
        setJobResult(fakeJob);
        setWalkthroughAudioUrl(staticUrl(walkthroughData?.audio_url));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load demo"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <AppShell>
        <div className="text-center text-gray-500 py-20">Loading demo result...</div>
      </AppShell>
    );
  }

  if (error || !jobResult) {
    return (
      <AppShell>
        <div className="text-center py-20">
          <p className="text-red-400 mb-4">{error || "Failed to load demo"}</p>
          <button onClick={() => navigate("/app")} className="text-indigo-400 hover:text-indigo-300 underline text-sm">
            ← Back to main
          </button>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <ResultsView
        job={jobResult}
        onReset={() => navigate("/app")}
        sourceJobId="golden-demo"
        personas={null}
        walkthroughAudioUrl={walkthroughAudioUrl}
      />
    </AppShell>
  );
}

// ============================================================
// Job Route (progress or results based on status)
// ============================================================

function JobRoute() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [jobResult, setJobResult] = useState<JobResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "progress" | "results" | "error">("loading");

  useEffect(() => {
    if (!jobId) return;
    fetchJobStatus(jobId)
      .then((job) => {
        if (job.status === "completed") {
          setJobResult(job);
          setStatus("results");
          // Clear from localStorage since it's done
          localStorage.removeItem(STORAGE_KEY);
        } else if (job.status === "running" || job.status === "pending") {
          setStatus("progress");
        } else {
          setStatus("error");
        }
      })
      .catch(() => setStatus("error"));
  }, [jobId]);

  const handleComplete = (job: JobResponse) => {
    setJobResult(job);
    setStatus("results");
    localStorage.removeItem(STORAGE_KEY);
  };

  const handleReset = () => {
    localStorage.removeItem(STORAGE_KEY);
    navigate("/app");
  };

  if (status === "loading") {
    return (
      <AppShell>
        <div className="text-center text-gray-500 py-20">Loading job...</div>
      </AppShell>
    );
  }

  if (status === "error") {
    return (
      <AppShell>
        <div className="text-center py-20">
          <p className="text-red-400 mb-4">Job not found or failed</p>
          <button onClick={() => navigate("/app")} className="text-indigo-400 hover:text-indigo-300 underline text-sm">
            ← Submit another pitch
          </button>
        </div>
      </AppShell>
    );
  }

  if (status === "progress" && jobId) {
    return (
      <AppShell>
        <ProgressView
          jobId={jobId}
          onComplete={handleComplete}
          onError={handleReset}
        />
      </AppShell>
    );
  }

  if (status === "results" && jobResult && jobId) {
    return (
      <AppShell>
        <ResultsView
          job={jobResult}
          onReset={handleReset}
          sourceJobId={jobId}
          personas={null}
          walkthroughAudioUrl={null}
        />
      </AppShell>
    );
  }

  return null;
}

// ============================================================
// Shared layout shell (header)
// ============================================================

function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="max-w-6xl mx-auto px-6 py-10">
      <header className="mb-10 text-center">
        <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
          StudioZ
        </h1>
        <p className="mt-2 text-gray-400 text-lg">
          Multi-Agent Cinema Pre-Production Studio
        </p>
      </header>
      {children}
    </div>
  );
}

// ============================================================
// App (router setup)
// ============================================================

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CoverRoute />} />
        <Route path="/app" element={<MainRoute />} />
        <Route path="/explainer" element={<ExplainerRoute />} />
        <Route path="/demo" element={<DemoRoute />} />
        <Route path="/job/:jobId" element={<JobRoute />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
