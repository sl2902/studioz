import { useState, useEffect } from "react";
import type { JobResponse, PersonaOptions } from "./types";
import { fetchGoldenDemo, fetchJobStatus, fetchWalkthroughAudio } from "./api";
import { PitchForm } from "./components/PitchForm";
import { ProgressView } from "./components/ProgressView";
import { ResultsView } from "./components/ResultsView";
import { ExplainerView } from "./components/ExplainerView";

type AppView = "form" | "progress" | "results" | "explainer" | "loading";

const STORAGE_KEY = "studioz_active_job";

function getJobIdFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search);
  return params.get("job");
}

function setJobIdInUrl(jobId: string | null) {
  const url = new URL(window.location.href);
  if (jobId) {
    url.searchParams.set("job", jobId);
  } else {
    url.searchParams.delete("job");
  }
  window.history.replaceState({}, "", url.toString());
}

function App() {
  const [view, setView] = useState<AppView>("loading");
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobResult, setJobResult] = useState<JobResponse | null>(null);
  const [personas, setPersonas] = useState<PersonaOptions | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [resumeJobId, setResumeJobId] = useState<string | null>(null);

  // On mount: check URL and localStorage for an existing job
  useEffect(() => {
    const urlJobId = getJobIdFromUrl();
    const storedJobId = localStorage.getItem(STORAGE_KEY);
    const recoveredId = urlJobId || storedJobId;

    if (recoveredId && recoveredId !== "golden-demo") {
      // Try to resume this job
      fetchJobStatus(recoveredId)
        .then((job) => {
          if (job.status === "completed") {
            setJobId(recoveredId);
            setJobResult(job);
            setView("results");
            setJobIdInUrl(recoveredId);
          } else if (job.status === "running" || job.status === "pending") {
            setJobId(recoveredId);
            setView("progress");
            setJobIdInUrl(recoveredId);
          } else {
            // Failed job — show form but offer resume
            clearPersistedJob();
            setView("form");
          }
        })
        .catch(() => {
          // Job not found (server restarted?) — show form
          // If there's a stored ID, offer to clear it
          if (storedJobId && !urlJobId) {
            setResumeJobId(storedJobId);
          }
          clearPersistedJob();
          setView("form");
        });
    } else {
      setView("form");
    }
  }, []);

  function persistJob(id: string) {
    localStorage.setItem(STORAGE_KEY, id);
    setJobIdInUrl(id);
  }

  function clearPersistedJob() {
    localStorage.removeItem(STORAGE_KEY);
    setJobIdInUrl(null);
  }

  const handleSubmit = (id: string) => {
    setJobId(id);
    setView("progress");
    persistJob(id);
  };

  const handleComplete = (job: JobResponse) => {
    setJobResult(job);
    setView("results");
    // Keep in URL for shareability but clear localStorage (no longer "active")
    localStorage.removeItem(STORAGE_KEY);
  };

  const handleReset = () => {
    setView("form");
    setJobId(null);
    setJobResult(null);
    setDemoError(null);
    setResumeJobId(null);
    clearPersistedJob();
  };

  const [walkthroughAudioUrl, setWalkthroughAudioUrl] = useState<string | null>(null);

  const handleViewDemo = async () => {
    setDemoLoading(true);
    setDemoError(null);
    try {
      const [demoData, walkthroughData] = await Promise.all([
        fetchGoldenDemo(),
        fetchWalkthroughAudio(),
      ]);
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
      setWalkthroughAudioUrl(walkthroughData?.audio_url || null);
      setJobResult(fakeJob);
      setJobId("golden-demo");
      setView("results");
    } catch (err) {
      setDemoError(err instanceof Error ? err.message : "Failed to load demo");
    } finally {
      setDemoLoading(false);
    }
  };

  const handleResumeJob = (id: string) => {
    setJobId(id);
    setView("progress");
    persistJob(id);
    setResumeJobId(null);
  };

  // Loading state while checking for recoverable job
  if (view === "loading") {
    return (
      <div className="max-w-6xl mx-auto px-6 py-10 text-center text-gray-500">
        Loading...
      </div>
    );
  }

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

      {view === "form" && (
        <>
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
                  onClick={() => setResumeJobId(null)}
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
              onClick={() => setView("explainer")}
              className="px-4 py-2 text-sm rounded-lg border border-[var(--color-border)] text-gray-400 hover:text-purple-300 hover:border-purple-500/50 transition-colors"
            >
              📊 Pipeline Explainer
            </button>
          </div>
          {demoError && (
            <p className="text-center text-sm text-red-400 mt-3">{demoError}</p>
          )}
        </>
      )}

      {view === "progress" && jobId && (
        <ProgressView
          jobId={jobId}
          onComplete={handleComplete}
          onError={handleReset}
        />
      )}

      {view === "results" && jobResult && (
        <ResultsView job={jobResult} onReset={handleReset} sourceJobId={jobId!} personas={personas} walkthroughAudioUrl={walkthroughAudioUrl} />
      )}

      {view === "explainer" && (
        <ExplainerView onExit={handleReset} />
      )}
    </div>
  );
}

export default App;
