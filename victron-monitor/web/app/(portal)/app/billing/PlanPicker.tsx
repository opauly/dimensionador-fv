'use client';

// The tier grid for `/app/billing` (PLAN_PHASE16.md §5.1 / §8 Step 5) — the
// "authenticated app page" sibling of `components/marketing/Pricing/
// Pricing.tsx` (visual reference only, per the coder brief: this is
// `app/(portal)/app/**`'s own `components/ui` conventions, not an import of
// the marketing component). Used in TWO modes, both reusing this same
// component and the same `GET /api/billing/plans` call:
//   - `mode="subscribe"` — no live subscription exists yet (first-run, or a
//     fully-canceled customer re-subscribing). Selecting a plan calls
//     `BillingManager`'s own `handlePlanSelected()`, which creates the ONVO
//     subscription (`POST /api/billing/subscribe {plan_id}` — no
//     `payment_method_id`, corrected at Step 5 2026-08-20) and then hands
//     off to `PaymentMethodPanel` to collect a card against it, even if one
//     is already on file (§5.2).
//   - `mode="change"` — a live subscription exists. Selecting a plan calls
//     `POST /api/billing/change` directly (no card panel — §5.3: "reuses
//     the existing default payment method").
// `GET /v1/billing/plans` already does every filter this component needs
// (`active`/`mode`/`account_types`/`self_serve` when `pending_subscription`)
// — this component renders exactly what it gets back, no client-side
// re-filtering (§5.1's own docstring).
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
// `lib/plans.ts:planLabel()` takes `vrm.customers.plan` (a customer's OWN
// current plan string) — this needs the same lookup against a CATALOGUE
// row's `plan_key`, which is the identical vocabulary (`starter`/`growth`/…)
// by construction (migration 025 seeds `vrm.plans.plan_key` FROM that same
// vocabulary). A thin re-import under a name that reads correctly at this
// call site (a plan row, not a customer), not a reimplementation.
import { planLabel as planLabelFromKey } from '@/lib/plans';
import type { BillingPlanOut } from '@/lib/server/pipeline';
import styles from './billing.module.css';

export type PlanPickerProps = {
  lang: Lang;
  mode: 'subscribe' | 'change';
  onSelect: (plan: BillingPlanOut) => void;
  onCancel?: () => void;
  busy?: boolean;
  /** The plan the customer picked during `/signup` (`?plan=` there, threaded
   * through `redeemSignupToken()`'s redirect target as `/app/billing?plan=`,
   * PLAN_PHASE16.md §5.5 Step 2) — highlighted here so the choice they
   * already made doesn't look forgotten. Display only: still just a border
   * around the matching card, not an auto-selected/auto-submitted plan —
   * `onSelect` only ever fires from an explicit "Select" click, same as
   * every other card. */
  initialPlanId?: string | null;
};

// v1 is USD-only (§0.6 Q1) but `currency` stays a real field, not a hard-
// coded assumption — a non-USD currency still renders sensibly (code
// prefix instead of a `$` glyph) rather than silently mislabeling an amount.
function formatMoney(amountMinor: number, currency: string): string {
  const amount = (amountMinor / 100).toFixed(2);
  return currency === 'USD' ? `$${amount}` : `${amount} ${currency}`;
}

function intervalKey(interval: string): 'billing_plan_per_month' | 'billing_plan_per_year' | null {
  if (interval === 'month') return 'billing_plan_per_month';
  if (interval === 'year') return 'billing_plan_per_year';
  return null;
}

export function PlanPicker({ lang, mode, onSelect, onCancel, busy = false, initialPlanId = null }: PlanPickerProps) {
  const [plans, setPlans] = useState<BillingPlanOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/billing/plans');
        if (!res.ok) throw new Error('failed');
        const data = (await res.json()) as { plans: BillingPlanOut[] };
        if (!cancelled) setPlans(data.plans);
      } catch {
        if (!cancelled) setError(t(lang, 'billing_plans_error'));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [lang]);

  return (
    <div className={styles.panel}>
      <h2>{t(lang, 'billing_plans_title')}</h2>

      {error ? (
        <p className={styles.error}>{error}</p>
      ) : plans === null ? (
        <p className={styles.status}>{t(lang, 'billing_plans_loading')}</p>
      ) : plans.length === 0 ? (
        <p className={styles.status}>{t(lang, 'billing_plans_empty')}</p>
      ) : (
        <div className={styles.grid}>
          {plans.map((plan) => {
            const perKey = intervalKey(plan.billing_interval);
            const sitesLabel =
              plan.site_limit === null
                ? t(lang, 'billing_plan_sites_unlimited')
                : t(lang, 'billing_plan_sites_up_to').replace('{limit}', String(plan.site_limit));
            // `plan.plan_label_key` is `vrm_api`'s own `f"billing.plan.{plan_key}"`
            // (an i18n lookup key, per that field's own docstring) — but
            // `lib/i18n/strings.ts` has no `billing.plan.*` entries, and
            // `t()` only accepts a literal `StringKey`. `lib/plans.ts:
            // planLabel()` already exists for exactly this ("`vrm.customers.
            // plan` is free text ... a customer's own `plan` string, human
            // label"), is already used by `/app/profile`, and covers the
            // same plan-key vocabulary — used here instead of inventing a
            // parallel dynamic-i18n-key mechanism for one field.
            const disabled = busy || plan.is_current;
            const preSelected = plan.id === initialPlanId;
            return (
              <div key={plan.id} className={[styles.planCard, preSelected && styles.planCardSelected].filter(Boolean).join(' ')}>
                {plan.is_current && <span className={styles.planCurrentTag}>{t(lang, 'billing_plan_current_tag')}</span>}
                <h3>{planLabelFromKey(plan.plan_key)}</h3>
                <span className={styles.planRange}>{sitesLabel}</span>
                <div className={styles.planPrice}>
                  {formatMoney(plan.amount_minor, plan.currency)}
                  {perKey && <span className={styles.planPer}>{t(lang, perKey)}</span>}
                </div>
                <Button type="button" variant="ghost" disabled={disabled} onClick={() => onSelect(plan)}>
                  {t(lang, 'billing_plan_select_button')}
                </Button>
              </div>
            );
          })}
        </div>
      )}

      {mode === 'subscribe' && <p className={styles.hint}>{t(lang, 'billing_subscribe_note')}</p>}
      {mode === 'change' && <p className={styles.hint}>{t(lang, 'billing_change_note')}</p>}

      {onCancel && (
        <div className={styles.formActions}>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            {t(lang, 'billing_back_button')}
          </Button>
        </div>
      )}
    </div>
  );
}
