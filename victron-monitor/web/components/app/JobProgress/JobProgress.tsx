'use client';

// Polls a `vrm_api` job through our own proxy (`/api/pipeline/jobs/[id]` —
// never `vrm_api` directly: there is no browser Supabase client and no
// reason for the browser to ever hold `PIPELINE_API_KEY` either) and turns
// queued/running/done/failed into UI a customer can actually act on
// (PLAN_PHASE14.md §2 Step 6: "shows a real status, and fails with a human
// sentence" — the opposite of a spinner that never resolves).
//
// This component owns exactly one thing: the polling loop and what to show
// while it's in flight. It does not know what an "ingest" or a "report" job
// is — `onDone`/`onFailed` hand that back to whichever page mounted it
// (`UploadManager.tsx`, `ReportManager.tsx`), which is what makes this the
// one `components/app/` piece both flows share instead of two near-identical
// polling loops.
import { useEffect, useRef, useState } from 'react';
import { Eyebrow } from '@/components/ui';
import styles from './JobProgress.module.css';

export type JobProgressJob = {
  id: string;
  kind: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  result: Record<string, unknown> | null;
  error: string | null;
};

export type JobProgressProps = {
  jobId: string;
  /** Shown while status is queued/running, e.g. "Processing the CSV…". */
  runningLabel: string;
  /** Shown on a `failed` job with no `error` text of its own. */
  genericFailedLabel: string;
  /** Shown when the proxy itself can't be reached for long enough that
   * waiting longer stops being reasonable — see `MAX_CONSECUTIVE_ERRORS`. */
  unreachableLabel: string;
  onDone: (job: JobProgressJob) => void;
  onFailed?: (message: string) => void;
  pollIntervalMs?: number;
  /** Which Next.js proxy to poll — defaults to the customer-facing
   * `/api/pipeline/jobs` proxy (`getJobScoped()`, customer_id-checked).
   * `/admin/*` flows (PLAN_PHASE14.md §2 Step 7) pass
   * `/api/admin/pipeline/jobs` instead, whose route handler checks
   * `requireAdminForRoute()` rather than a customer_id match — admin
   * sessions have no `customerId` to scope by, and are allowed to see any
   * job by design. Same component either way: this prop is the only thing
   * that differs between the two call sites. */
  endpoint?: string;
};

// ~15 polls * 2s = 30s of an unreachable proxy/pipeline before this
// component gives up and reports a local failure (PLAN_PHASE14.md §2 Step
// 6's "kill the API mid-job" case). The *real* backstop for a genuinely
// interrupted job is vrm_api's 15-minute stale-job sweep
// (`vrm_api/jobs.py:sweep_stale_jobs()`); this is only what keeps the
// screen itself from spinning forever while that plays out — if vrm_api
// comes back before this fires, the very next successful poll clears it.
const MAX_CONSECUTIVE_ERRORS = 15;

export function JobProgress({
  jobId,
  runningLabel,
  genericFailedLabel,
  unreachableLabel,
  onDone,
  onFailed,
  pollIntervalMs = 2000,
  endpoint = '/api/pipeline/jobs',
}: JobProgressProps) {
  const [error, setError] = useState<string | null>(null);

  // "Adjusting state when a prop changes" (React's own name for this
  // pattern, not a workaround) — resets `error` during render, the instant
  // `jobId` changes, rather than in an effect. A `setState` call unconditionally
  // at the top of an effect body is exactly what `react-hooks/set-state-in-effect`
  // flags: it means the reset can be derived from render inputs instead of
  // needing to run as a side effect at all. Only the actual side effect
  // (polling) still lives in `useEffect` below.
  const [trackedJobId, setTrackedJobId] = useState(jobId);
  if (jobId !== trackedJobId) {
    setTrackedJobId(jobId);
    setError(null);
  }

  // `onDone`/`onFailed` are read via a ref rather than listed as effect
  // deps — parents typically pass a fresh closure every render, and this
  // effect must not re-subscribe (and restart the 30s unreachable counter)
  // just because the parent re-rendered for an unrelated reason. Re-polling
  // on purpose (a genuinely new job) works because `jobId` itself is a dep.
  // The ref itself is kept current from an effect, not during render —
  // mutating a ref's `.current` synchronously in the render body is its own
  // lint error (`react-hooks/refs`): refs are for effects/handlers, not render.
  const callbacksRef = useRef({ onDone, onFailed });
  useEffect(() => {
    callbacksRef.current = { onDone, onFailed };
  });

  useEffect(() => {
    let cancelled = false;
    let settled = false;
    let consecutiveErrors = 0;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      if (cancelled || settled) return;
      try {
        const res = await fetch(`${endpoint}/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
        if (!res.ok) throw new Error(String(res.status));
        consecutiveErrors = 0;
        const job = (await res.json()) as JobProgressJob;

        if (job.status === 'done') {
          settled = true;
          callbacksRef.current.onDone(job);
          return;
        }
        if (job.status === 'failed') {
          settled = true;
          const message = job.error || genericFailedLabel;
          setError(message);
          callbacksRef.current.onFailed?.(message);
          return;
        }
      } catch {
        consecutiveErrors += 1;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          settled = true;
          setError(unreachableLabel);
          callbacksRef.current.onFailed?.(unreachableLabel);
          return;
        }
      }
      if (!cancelled && !settled) {
        timer = setTimeout(poll, pollIntervalMs);
      }
    }

    timer = setTimeout(poll, 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, pollIntervalMs, genericFailedLabel, unreachableLabel, endpoint]);

  if (error) {
    return (
      <p className={styles.error} role="alert">
        {error}
      </p>
    );
  }

  return (
    <p className={styles.running}>
      <Eyebrow amber>{runningLabel}</Eyebrow>
    </p>
  );
}
