interface Props {
  onEnter: () => void;
}

export function CoverScreen({ onEnter }: Props) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6 py-12 select-none">
      {/* Stick figure illustration holding sign */}
      <div className="mb-8">
        <svg
          viewBox="0 0 320 220"
          className="w-[280px] sm:w-[320px] h-auto"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-label="Two stick figures holding a StudioZ sign"
        >
          {/* Sign (held between the two figures) */}
          <rect
            x="80" y="30" width="160" height="50" rx="6"
            stroke="#6366f1" strokeWidth="2.5" fill="#1a1a2e"
          />
          {/* Sign text — rendered as SVG text for crispness */}
          <text
            x="160" y="62"
            textAnchor="middle"
            fontFamily="system-ui, -apple-system, sans-serif"
            fontSize="24"
            fontWeight="700"
            fill="url(#signGradient)"
          >
            StudioZ
          </text>

          {/* Gradient for sign text */}
          <defs>
            <linearGradient id="signGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#818cf8" />
              <stop offset="100%" stopColor="#a78bfa" />
            </linearGradient>
          </defs>

          {/* Left stick figure */}
          {/* Head */}
          <circle cx="100" cy="110" r="14" stroke="#e5e7eb" strokeWidth="2.5" />
          {/* Body */}
          <line x1="100" y1="124" x2="100" y2="170" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
          {/* Left arm (hanging) */}
          <line x1="100" y1="138" x2="78" y2="158" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
          {/* Right arm (raised, holding sign) */}
          <line x1="100" y1="138" x2="110" y2="80" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
          {/* Left leg */}
          <line x1="100" y1="170" x2="82" y2="200" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
          {/* Right leg */}
          <line x1="100" y1="170" x2="118" y2="200" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />

          {/* Right stick figure */}
          {/* Head */}
          <circle cx="220" cy="110" r="14" stroke="#e5e7eb" strokeWidth="2.5" />
          {/* Body */}
          <line x1="220" y1="124" x2="220" y2="170" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
          {/* Right arm (hanging) */}
          <line x1="220" y1="138" x2="242" y2="158" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
          {/* Left arm (raised, holding sign) */}
          <line x1="220" y1="138" x2="210" y2="80" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
          {/* Left leg */}
          <line x1="220" y1="170" x2="202" y2="200" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
          {/* Right leg */}
          <line x1="220" y1="170" x2="238" y2="200" stroke="#e5e7eb" strokeWidth="2.5" strokeLinecap="round" />
        </svg>
      </div>

      {/* Tagline */}
      <p className="text-gray-400 text-sm sm:text-base mb-10 text-center max-w-md">
        Multi-Agent Cinema Pre-Production Studio
      </p>

      {/* Enter button */}
      <button
        onClick={onEnter}
        className="px-8 py-3 text-base font-semibold rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/30 transition-all duration-200 hover:scale-105"
      >
        Enter
      </button>
    </div>
  );
}
