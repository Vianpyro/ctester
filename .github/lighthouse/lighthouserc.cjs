// One file, four profiles, picked by LH_PROFILE. Four near-identical JSON files would
// drift apart the first time a threshold moves.
//
// Only the viewport changes between profiles. The throttling below stays the same for all
// four, or the scores would not be comparable from one to the next.
//
// The CLS budget is per profile because the same displacement is a different fraction of a
// 768px screen and of a 2160px one: one number for all four would be tight on the laptop
// and meaningless on the 4K. Each budget is about twice what a known-good build measures,
// noted beside it. Re-measure and re-base them when the layout changes on purpose --
// scripts/demo_content.py plus the commands in the workflow reproduce the numbers.
const PROFILES = {
  //                 viewport            dSF   measured   budget
  laptop: { width: 1366, height: 768, deviceScaleFactor: 1, cls: 0.035 }, // 0.016
  ipad: { width: 810, height: 1080, deviceScaleFactor: 2, cls: 0.045 }, // 0.029
  "desk-4k-150": { width: 2560, height: 1440, deviceScaleFactor: 1, cls: 0.025 }, // 0.010
  "desk-4k-100": { width: 3840, height: 2160, deviceScaleFactor: 1, cls: 0.02 }, // 0.008
};

const name = process.env.LH_PROFILE || "laptop";
const profile = PROFILES[name];
if (!profile) {
  throw new Error(
    `unknown LH_PROFILE ${JSON.stringify(name)}; expected one of ${Object.keys(PROFILES).join(", ")}`,
  );
}
const { cls, ...screen } = profile;

// scripts/demo_content.py serves these; the quiz id is QUIZ_ID over there.
const base = process.env.LH_BASE_URL || "http://localhost:8000";

module.exports = {
  ci: {
    collect: {
      url: [`${base}/?k=dev`, `${base}/?k=dev&tp=tp1-ex3`],
      numberOfRuns: 3,
      settings: {
        preset: "desktop",
        formFactor: "desktop",
        // None of the four are phones: no touch emulation, no mobile viewport.
        screenEmulation: { ...screen, mobile: false, disabled: false },
        // Real throttling, not the simulated kind. Over loopback the desktop preset scores
        // a flattering 1.0 that says nothing; this is roughly the classroom link the
        // service worker was written for, and it puts the performance score in the range
        // the deployed site actually sees. It does not change CLS -- a shift is a shift
        // whenever it lands -- it only makes the timings mean something.
        throttlingMethod: "devtools",
        throttling: {
          requestLatencyMs: 300,
          downloadThroughputKbps: 1600,
          uploadThroughputKbps: 750,
          cpuSlowdownMultiplier: 4,
        },
      },
    },
    assert: {
      assertions: {
        // The two that hold steady run to run, so the two worth failing on. Measured
        // spread over four consecutive runs of the same build: 0.0%.
        "cumulative-layout-shift": ["error", { maxNumericValue: cls }],
        "categories:accessibility": ["error", { minScore: 1 }],
        // Reported, never fatal: a shared runner moves these enough to fail at random.
        "categories:performance": ["warn", { minScore: 0.75 }],
        "categories:best-practices": ["warn", { minScore: 1 }],
      },
    },
  },
};
