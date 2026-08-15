import { useEffect, useState } from "react";
import type { PersonaOptions, PitchRequest } from "../types";
import { fetchPersonas, submitPitch } from "../api";

function formatKey(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

interface Props {
  onSubmit: (jobId: string) => void;
  personas: PersonaOptions | null;
  setPersonas: (p: PersonaOptions) => void;
}

export function PitchForm({ onSubmit, personas, setPersonas }: Props) {
  const [pitch, setPitch] = useState("");
  const [filmType, setFilmType] = useState<"feature" | "short">("short");
  const [runtime, setRuntime] = useState("");
  const [screenwriter, setScreenwriter] = useState("");
  const [director, setDirector] = useState("");
  const [force, setForce] = useState(true);
  const [bypassCache, setBypassCache] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!personas) {
      fetchPersonas().then((p) => {
        setPersonas(p);
        if (p.screenwriter.length) setScreenwriter(p.screenwriter[0].key);
        if (p.director.length) setDirector(p.director[0].key);
      });
    } else {
      if (!screenwriter && personas.screenwriter.length)
        setScreenwriter(personas.screenwriter[0].key);
      if (!director && personas.director.length)
        setDirector(personas.director[0].key);
    }
  }, [personas]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const request: PitchRequest = {
      pitch,
      film_type: filmType,
      target_runtime_minutes: runtime ? parseInt(runtime) : null,
      screenwriter_persona: screenwriter,
      director_persona: director,
      force,
      bypass_cache: bypassCache,
    };

    try {
      const { job_id } = await submitPitch(request);
      onSubmit(job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setLoading(false);
    }
  };

  if (!personas) {
    return (
      <div className="text-center text-gray-400 py-20">
        Loading personas...
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-2xl mx-auto space-y-6">
      <div className="bg-[var(--color-surface)] rounded-xl p-6 border border-[var(--color-border)]">
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Film Pitch
        </label>
        <textarea
          value={pitch}
          onChange={(e) => setPitch(e.target.value)}
          placeholder="Describe your film concept in detail..."
          rows={5}
          className="w-full bg-[var(--color-surface-light)] border border-[var(--color-border)] rounded-lg px-4 py-3 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 resize-none"
          required
          minLength={10}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-[var(--color-surface)] rounded-xl p-4 border border-[var(--color-border)]">
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Film Type
          </label>
          <select
            value={filmType}
            onChange={(e) => setFilmType(e.target.value as "feature" | "short")}
            className="w-full bg-[var(--color-surface-light)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          >
            <option value="short">Short Film</option>
            <option value="feature">Feature Film</option>
          </select>
        </div>

        <div className="bg-[var(--color-surface)] rounded-xl p-4 border border-[var(--color-border)]">
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Target Runtime (minutes)
          </label>
          <input
            type="number"
            value={runtime}
            onChange={(e) => setRuntime(e.target.value)}
            placeholder="Optional"
            min={1}
            className="w-full bg-[var(--color-surface-light)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-[var(--color-surface)] rounded-xl p-4 border border-[var(--color-border)]">
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Screenwriter
          </label>
          <select
            value={screenwriter}
            onChange={(e) => setScreenwriter(e.target.value)}
            className="w-full bg-[var(--color-surface-light)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          >
            {personas.screenwriter.map((p) => (
              <option key={p.key} value={p.key}>
                {formatKey(p.key)} — {p.title}
              </option>
            ))}
          </select>
        </div>

        <div className="bg-[var(--color-surface)] rounded-xl p-4 border border-[var(--color-border)]">
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Director
          </label>
          <select
            value={director}
            onChange={(e) => setDirector(e.target.value)}
            className="w-full bg-[var(--color-surface-light)] border border-[var(--color-border)] rounded-lg px-3 py-2 text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          >
            {personas.director.map((p) => (
              <option key={p.key} value={p.key}>
                {formatKey(p.key)} — {p.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex items-center gap-3 bg-[var(--color-surface)] rounded-xl p-4 border border-[var(--color-border)]">
        <input
          type="checkbox"
          id="force"
          checked={force}
          onChange={(e) => setForce(e.target.checked)}
          className="w-4 h-4 rounded border-gray-600 text-indigo-500 focus:ring-indigo-500/50"
        />
        <label htmlFor="force" className="text-sm text-gray-300">
          Override committee rejection and generate storyboard anyway
        </label>
      </div>

      <div className="flex items-center gap-3 bg-[var(--color-surface)] rounded-xl p-4 border border-[var(--color-border)]">
        <input
          type="checkbox"
          id="bypass_cache"
          checked={bypassCache}
          onChange={(e) => setBypassCache(e.target.checked)}
          className="w-4 h-4 rounded border-gray-600 text-purple-500 focus:ring-purple-500/50"
        />
        <label htmlFor="bypass_cache" className="text-sm text-gray-300">
          Bypass cache (force a fresh run even if identical pitch was submitted before)
        </label>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 text-red-300 text-sm">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={loading || pitch.length < 10}
        className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-semibold py-3 px-6 rounded-xl transition-colors"
      >
        {loading ? "Submitting..." : "Submit Pitch to Committee"}
      </button>
    </form>
  );
}
