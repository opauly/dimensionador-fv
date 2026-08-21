'use client';

// Hosts ONVO's own SDK-rendered card form (PLAN_PHASE16.md §6.3 / §8 Step 5
// — "no `<input>` for a card number, expiry, or CVV exists anywhere in this
// repo. Not disabled, not hidden — absent"). There is NO hand-rolled card
// field anywhere in this file, on purpose: the widget below is a plain
// `<script src="https://sdk.onvopay.com/sdk.js">` (via `next/script`) that
// renders a third-party-owned form into `#onvo-payment-method-form`, and
// this component never styles or reads its internals — a card number, CVV,
// or raw PAN never reaches this component's state, this app's server, or
// any request this component itself constructs.
//
// Corrected at Step 5 (2026-08-20) — PLAN_PHASE16.md §5.2 point 3 / §5.3's
// `payment-method/session` bullet: the ONVO SDK widget will not render a
// working card form without a real `subscriptionId` to attach the card to
// (confirmed live, `tools/validate_billing_step5_fix.py`) — a `customerId`
// alone is not enough. That real id now reaches this component one of two
// ways, matching the two callers (§5.2 step 3 / §5.3, `vrm_api`'s own
// `post_subscription()`/`post_payment_method_session()` docstrings):
//   - `mode="subscribe"` — first card on a brand-new (or re-subscribing)
//     customer. `BillingManager` already called `POST /api/billing/subscribe`
//     BEFORE mounting this component (creating an ONVO subscription with NO
//     card attached at all) and hands its response down as `subscribeSession`
//     — this component never calls subscribe itself.
//   - `mode="replace"` — swapping the card on a live subscription. This
//     component primes its OWN session via
//     `POST /api/billing/payment-method/session` on mount, which returns the
//     customer's EXISTING live `onvo_subscription_id`.
// Either way, once the widget has a real `subscriptionId` + `customerId` +
// publishable key, the SAME thing happens on success: `onSuccess(data)` is
// treated as an untrusted HINT ONLY (§0.2/§0.5) — this component extracts a
// payment-method-id-SHAPED field purely to decide whether the callback looks
// like a real success worth acting on at all (a UX gate, not a trust
// decision: nothing extracted here is ever sent in a request body to
// anywhere, `vrm_api` or otherwise) — and then calls
// `POST /api/billing/refresh`, the only thing allowed to turn "the widget
// says it worked" into real state, by re-reading the subscription from ONVO
// itself (`vrm_api`'s own `billing.reconcile_customer()`).
import { startTransition, useEffect, useRef, useState } from 'react';
import Script from 'next/script';
import { Button } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
import type { BillingStatusOut } from '@/lib/server/pipeline';
import styles from './billing.module.css';

// The ONVO web SDK is a plain global script, not an npm package (§0.2 [C])
// — no published types exist to import, so this is the minimal shape this
// component actually calls. `render()`'s return value and every other
// method the real SDK may expose are deliberately left untyped/unused.
declare global {
  interface Window {
    onvo?: {
      pay: (config: {
        publicKey: string;
        customerId: string;
        subscriptionId: string;
        paymentType: 'one_time' | 'subscription';
        locale: 'en' | 'es';
        manualSubmit: boolean;
        onSuccess: (data: unknown) => void;
        onError: (data: unknown) => void;
      }) => { render: (selector: string) => void };
    };
  }
}

const CONTAINER_ID = 'onvo-payment-method-form';

export type PaymentMethodSession = {
  onvoSubscriptionId: string;
  onvoCustomerId: string;
  publishableKey: string;
};

export type PaymentMethodPanelProps = {
  lang: Lang;
  mode: 'subscribe' | 'replace';
  /** Required when `mode === 'subscribe'` — the response of
   * `BillingManager`'s own `POST /api/billing/subscribe` call, made BEFORE
   * this component ever mounts (§5.2: the subscription must exist, with no
   * card attached, before the widget can render at all). Unused in
   * `'replace'` mode, which primes its own session on mount instead. */
  subscribeSession?: PaymentMethodSession;
  onSuccess: (status: BillingStatusOut) => void;
  onCancel?: () => void;
};

type Phase = 'priming' | 'ready' | 'saving' | 'error';

/** §0.5 / §0.2: `onSuccess(data)`'s exact shape is UNDOCUMENTED by ONVO —
 * this app never treats it as trustworthy STATE (no card brand/last4 is
 * ever read out of it here; every field the UI eventually shows comes from
 * `vrm_api`'s own reconcile, via the follow-up `POST /api/billing/refresh`
 * below). It only serves as a UX gate — does this callback even look like a
 * real success? — never as something whose extracted value is sent
 * anywhere. Validated live against the real SDK (Step 5's spike page):
 * `onSuccess(data)` came back as `{id, status, refNumber, customerId,
 * paymentMethodId}`, confirming `paymentMethodId` is the right field to
 * check first. `billing_payment_method_error_no_id` is the named,
 * already-translated fallback for when none of these candidates exist. */
function extractPaymentMethodId(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null;
  const rec = data as Record<string, unknown>;
  const nested = (key: string): Record<string, unknown> | undefined => {
    const value = rec[key];
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : undefined;
  };
  const candidates: unknown[] = [
    rec.paymentMethodId,
    rec.paymentMethodID,
    rec.id,
    nested('data')?.id,
    nested('data')?.paymentMethodId,
    nested('paymentMethod')?.id,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate) return candidate;
  }
  return null;
}

export function PaymentMethodPanel({ lang, mode, subscribeSession, onSuccess, onCancel }: PaymentMethodPanelProps) {
  const [phase, setPhase] = useState<Phase>('priming');
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<PaymentMethodSession | null>(
    mode === 'subscribe' ? subscribeSession ?? null : null,
  );
  const [scriptReady, setScriptReady] = useState(false);
  const rendered = useRef(false);

  // `mode === 'replace'` only: prime a session for the customer's EXISTING
  // live subscription (§5.3) — `mode === 'subscribe'` already has its
  // session from `subscribeSession` (the subscribe call already happened in
  // `BillingManager`, before this component mounted) and skips this
  // entirely. Runs once on mount.
  useEffect(() => {
    if (mode !== 'replace') return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/billing/payment-method/session', { method: 'POST' });
        if (!res.ok) throw new Error('session_failed');
        const data = (await res.json()) as {
          onvo_subscription_id: string;
          onvo_customer_id: string;
          publishable_key: string;
        };
        if (!cancelled) {
          setSession({
            onvoSubscriptionId: data.onvo_subscription_id,
            onvoCustomerId: data.onvo_customer_id,
            publishableKey: data.publishable_key,
          });
        }
      } catch {
        if (!cancelled) {
          setError(t(lang, 'billing_payment_method_error_session'));
          setPhase('error');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  async function handleWidgetSuccess(data: unknown) {
    // A UX gate only (see this function's own module-level doc comment
    // above `extractPaymentMethodId()`) — the extracted id is never sent in
    // any request body below. `POST /api/billing/refresh` is what turns
    // "the widget says it worked" into real, server-reconciled state
    // (§5.2 point 3 / §5.3, corrected 2026-08-20).
    const paymentMethodId = extractPaymentMethodId(data);
    if (!paymentMethodId) {
      setError(t(lang, 'billing_payment_method_error_no_id'));
      setPhase('error');
      return;
    }
    setError(null);
    setPhase('saving');
    try {
      const refreshRes = await fetch('/api/billing/refresh', { method: 'POST' });
      if (!refreshRes.ok) {
        setError(t(lang, 'billing_payment_method_error_generic'));
        setPhase('ready');
        return;
      }
      onSuccess((await refreshRes.json()) as BillingStatusOut);
    } catch {
      setError(t(lang, 'billing_payment_method_error_unreachable'));
      setPhase('ready');
    }
  }

  function handleWidgetError() {
    setError(t(lang, 'billing_payment_method_error_generic'));
  }

  useEffect(() => {
    if (!scriptReady || !session || rendered.current) return;
    // `startTransition` wraps the state updates below — same
    // `react-hooks/set-state-in-effect`-satisfying shape
    // `VrmFleetManager.tsx:refresh()` already establishes elsewhere in this
    // app. `instance.render()` itself is an imperative third-party DOM
    // call, not a React state update, and runs synchronously regardless.
    startTransition(() => {
      if (!window.onvo) {
        setError(t(lang, 'billing_payment_method_error_unreachable'));
        setPhase('error');
        return;
      }
      rendered.current = true;
      const instance = window.onvo.pay({
        publicKey: session.publishableKey,
        customerId: session.onvoCustomerId,
        // The fix for the gap the PREVIOUS version of this file flagged:
        // `paymentType: "subscription"` requires `subscriptionId` AND
        // `customerId` (confirmed live via the SDK's own validation, Step 5's
        // spike) — `session.onvoSubscriptionId` now genuinely exists in BOTH
        // callers (see this component's own module doc comment), closing the
        // gap without needing a `"one_time"` fallback.
        subscriptionId: session.onvoSubscriptionId,
        paymentType: 'subscription',
        // The customer's REAL stored language preference — deliberately NOT
        // routed through `t()`/`FORCE_LANG`. `lib/i18n/strings.ts`'s own
        // `FORCE_LANG` override is scoped to THIS app's string table; the
        // ONVO widget is a third party with no knowledge of it, so it gets
        // `lang` (== `session.uiLanguage`, untouched by the override) as-is
        // — the one place a customer's real preference reaches a component
        // even while every `t()` call in this same file resolves to English.
        locale: lang,
        manualSubmit: false,
        onSuccess: handleWidgetSuccess,
        onError: handleWidgetError,
      });
      instance.render(`#${CONTAINER_ID}`);
      setPhase('ready');
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptReady, session]);

  return (
    <div className={styles.panel}>
      <Script
        src="https://sdk.onvopay.com/sdk.js"
        strategy="afterInteractive"
        onReady={() => setScriptReady(true)}
        onError={() => {
          setError(t(lang, 'billing_payment_method_error_unreachable'));
          setPhase('error');
        }}
      />
      <h2>{t(lang, 'billing_payment_method_title')}</h2>
      {(phase === 'priming' || !scriptReady) && phase !== 'error' && (
        <p className={styles.status}>{t(lang, 'billing_payment_method_loading')}</p>
      )}
      <div id={CONTAINER_ID} className={styles.sdkContainer} />
      {phase === 'saving' && <p className={styles.status}>{t(lang, 'billing_payment_method_saving')}</p>}
      {error && <p className={styles.error}>{error}</p>}
      {onCancel && (
        <div className={styles.formActions}>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={phase === 'saving'}>
            {t(lang, 'billing_payment_method_cancel_button')}
          </Button>
        </div>
      )}
    </div>
  );
}
