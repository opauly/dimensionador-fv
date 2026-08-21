'use client';

// The orchestrator for `/app/billing` (PLAN_PHASE16.md §8 Step 5). Owns
// which secondary panel is open and every mutation's busy/error state;
// `PlanPicker`/`PaymentMethodPanel`/`BillingAddressForm`/`InvoiceList`/
// `CancelDialog` are all "dumb" below this — they take callbacks and hand
// back a fresh, server-reconciled `BillingStatusOut`, never their own
// locally-guessed state (§0.5: every render comes from a real reconcile).
//
// `firstRun` (derived by `page.tsx` from `status.provisioning_state ===
// 'pending_subscription'`, per this file's own build note in the plan) is
// what a `pending_subscription` customer sees: no status panel, no cancel/
// invoices/address at all — just "pick a plan, enter a card." Nothing
// calls this with `firstRun=true` yet (Step 5.5, not this step's job) —
// this component only has to thread the prop through and branch on it
// correctly, which is what the `trackedFirstRun` watcher below (and the
// `transitioning` state after a first-ever subscribe) actually exercises.
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui';
import { BillingBanners } from '@/components/app';
import { t, type Lang, type StringKey } from '@/lib/i18n/strings';
import { planLabel } from '@/lib/plans';
import { formatDate, type DateLocale } from '@/lib/dates';
import type { BillingPlanOut, BillingStatusOut } from '@/lib/server/pipeline';
import { PlanPicker } from './PlanPicker';
import { PaymentMethodPanel, type PaymentMethodSession } from './PaymentMethodPanel';
import { BillingAddressForm } from './BillingAddressForm';
import { InvoiceList } from './InvoiceList';
import { CancelDialog } from './CancelDialog';
import styles from './billing.module.css';

const DATE_LOCALE: Record<Lang, DateLocale> = { en: 'en-US', es: 'es-CR' };

const STATUS_LABEL_KEY: Record<string, StringKey> = {
  trialing: 'billing_status_trialing',
  active: 'billing_status_active',
  past_due: 'billing_status_past_due',
  canceled: 'billing_status_canceled',
  unpaid: 'billing_status_unpaid',
  incomplete: 'billing_status_incomplete',
  incomplete_expired: 'billing_status_incomplete_expired',
};

function statusLabel(lang: Lang, status: string | null): string {
  if (!status) return t(lang, 'billing_status_unknown');
  const key = STATUS_LABEL_KEY[status];
  return key ? t(lang, key) : status;
}

function statusBadgeClass(status: string | null): string {
  if (status === 'active' || status === 'trialing') return styles.badgeGood;
  if (status === 'past_due' || status === 'unpaid' || status === 'incomplete') return styles.badgeWarn;
  return styles.badgeNeutral;
}

function formatMoney(amountMinor: number | null, currency: string | null): string {
  if (amountMinor === null) return '—';
  const amount = (amountMinor / 100).toFixed(2);
  return currency === 'USD' || !currency ? `$${amount}` : `${amount} ${currency}`;
}

function intervalKey(interval: string | null): 'billing_plan_per_month' | 'billing_plan_per_year' | null {
  if (interval === 'month') return 'billing_plan_per_month';
  if (interval === 'year') return 'billing_plan_per_year';
  return null;
}

type PanelView = 'none' | 'plans' | 'payment_method';

type ChangeConfirm = {
  plan: BillingPlanOut;
  currentSiteCount: number;
  newSiteLimit: number | null;
};

export type BillingManagerProps = {
  status: BillingStatusOut;
  lang: Lang;
  firstRun: boolean;
  /** The plan chosen during signup (`/signup?plan=`, threaded through the
   * activation redirect) — display-only highlight in `PlanPicker`, per
   * that component's own prop comment. */
  initialPlanId: string | null;
};

export function BillingManager({ status: initialStatus, lang, firstRun, initialPlanId }: BillingManagerProps) {
  const router = useRouter();

  const [status, setStatus] = useState<BillingStatusOut>(initialStatus);

  // Same "adjust state during render" idiom `VrmLinkPanel.tsx` uses for its
  // own `status` prop: `firstRun` only ever changes when `page.tsx` (a
  // Server Component) actually re-executes with a fresh reconcile, which
  // only happens after this component itself calls `router.refresh()` —
  // so re-syncing here, rather than trusting a one-time initial value, is
  // what makes the transition OUT of first-run (after a real subscribe)
  // actually take effect without a full page reload.
  const [trackedFirstRun, setTrackedFirstRun] = useState(firstRun);
  const [transitioning, setTransitioning] = useState(false);
  if (firstRun !== trackedFirstRun) {
    setTrackedFirstRun(firstRun);
    setTransitioning(false);
  }

  const [panel, setPanel] = useState<PanelView>(
    !firstRun && (initialStatus.status === null || initialStatus.status === 'canceled') ? 'plans' : 'none',
  );
  const [selectedPlan, setSelectedPlan] = useState<BillingPlanOut | null>(null);
  const [changeConfirm, setChangeConfirm] = useState<ChangeConfirm | null>(null);
  const [changeBusy, setChangeBusy] = useState(false);
  const [changeError, setChangeError] = useState<string | null>(null);

  // §5.2, corrected at Step 5 (2026-08-20): a first-time (or re-)subscribe
  // now creates the ONVO subscription HERE, before `PaymentMethodPanel` ever
  // mounts — the SDK widget needs the resulting `onvo_subscription_id` to
  // render at all (`vrm_api/routers/billing.py:post_subscription()`'s own
  // docstring). `subscribeSession` is that response, handed straight to the
  // panel; `subscribeBusy`/`subscribeError` cover the gap between "plan
  // picked" and "panel ready to render."
  const [subscribeSession, setSubscribeSession] = useState<PaymentMethodSession | null>(null);
  const [subscribeBusy, setSubscribeBusy] = useState(false);
  const [subscribeError, setSubscribeError] = useState<string | null>(null);

  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const [resumeBusy, setResumeBusy] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);

  const hasLiveSubscription = status.status !== null && status.status !== 'canceled';

  function closePanel() {
    setPanel('none');
    setSelectedPlan(null);
    setChangeConfirm(null);
    setChangeError(null);
    setSubscribeSession(null);
    setSubscribeError(null);
  }

  async function handlePlanSelected(plan: BillingPlanOut) {
    if (hasLiveSubscription) {
      void submitChange(plan, false);
      return;
    }
    // §5.2, corrected 2026-08-20: create the ONVO subscription NOW (no
    // card yet — `POST /v1/billing/subscription` never takes a
    // `payment_method_id` any more) so `PaymentMethodPanel` has a real
    // `onvo_subscription_id` to render the SDK widget against as soon as it
    // mounts. Never optimistic local state (§5.4 point 3) — the panel only
    // opens once this real response is in hand.
    setSelectedPlan(plan);
    setSubscribeError(null);
    setSubscribeBusy(true);
    try {
      const res = await fetch('/api/billing/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: plan.id }),
      });
      if (!res.ok) {
        setSelectedPlan(null);
        setSubscribeError(t(lang, 'billing_action_error_generic'));
        return;
      }
      const data = (await res.json()) as {
        onvo_subscription_id: string;
        onvo_customer_id: string;
        publishable_key: string;
      };
      setSubscribeSession({
        onvoSubscriptionId: data.onvo_subscription_id,
        onvoCustomerId: data.onvo_customer_id,
        publishableKey: data.publishable_key,
      });
      setPanel('payment_method');
    } catch {
      setSelectedPlan(null);
      setSubscribeError(t(lang, 'billing_action_error_unreachable'));
    } finally {
      setSubscribeBusy(false);
    }
  }

  async function submitChange(plan: BillingPlanOut, confirm: boolean) {
    setChangeBusy(true);
    setChangeError(null);
    try {
      const res = await fetch('/api/billing/change', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan_id: plan.id, confirm }),
      });
      if (!res.ok) {
        // §8 Step 5's own gate: "Over-limit downgrade shows the
        // confirmation with real numbers" — `current_site_count`/
        // `new_site_limit` arrive here because `lib/server/pipeline.ts:
        // PipelineError` now carries the FastAPI error's extra detail
        // fields (see that file's own comment), not just `code`.
        const body = (await res.json().catch(() => null)) as
          | { error?: string; requires_confirmation?: boolean; current_site_count?: number; new_site_limit?: number | null }
          | null;
        if (body?.error === 'over_site_limit' && body.requires_confirmation) {
          setChangeConfirm({
            plan,
            currentSiteCount: body.current_site_count ?? status.active_sites,
            newSiteLimit: body.new_site_limit === undefined ? plan.site_limit : body.new_site_limit,
          });
          return;
        }
        setChangeError(t(lang, 'billing_action_error_generic'));
        return;
      }
      const next = (await res.json()) as BillingStatusOut;
      setStatus(next);
      closePanel();
      router.refresh();
    } catch {
      setChangeError(t(lang, 'billing_action_error_unreachable'));
    } finally {
      setChangeBusy(false);
    }
  }

  function handleSubscribed(next: BillingStatusOut) {
    setStatus(next);
    closePanel();
    // A brand-new (or first-ever) subscription just reconciled. When this
    // happened FROM first-run, that reconcile is expected to have promoted
    // `provisioning_state` to `'active'` (§4.5 rule 8) — the NEXT Server
    // Component render is what actually flips the `firstRun` prop, and this
    // transitional view covers the gap between "we know it worked" and "the
    // server confirmed it" (matching `VrmLinkPanel.tsx`'s own connecting/
    // disconnecting transitional pattern). An ALREADY-active customer
    // subscribing for the first time (the "no live subscription yet" branch
    // below `hasLiveSubscription`) never had `firstRun` true to begin with,
    // so `firstRun` never changes and this transitional view would never
    // clear — `trackedFirstRun` itself is the right guard for which case
    // this is.
    if (trackedFirstRun) setTransitioning(true);
    router.refresh();
  }

  function handlePaymentMethodChanged(next: BillingStatusOut) {
    setStatus(next);
    closePanel();
    router.refresh();
  }

  async function handleCancelConfirm() {
    setCancelBusy(true);
    setCancelError(null);
    try {
      const res = await fetch('/api/billing/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'at_period_end' }),
      });
      if (!res.ok) {
        setCancelError(t(lang, 'billing_action_error_generic'));
        return;
      }
      const next = (await res.json()) as BillingStatusOut;
      setStatus(next);
      setCancelOpen(false);
      router.refresh();
    } catch {
      setCancelError(t(lang, 'billing_action_error_unreachable'));
    } finally {
      setCancelBusy(false);
    }
  }

  async function handleResume() {
    setResumeBusy(true);
    setResumeError(null);
    try {
      const res = await fetch('/api/billing/resume', { method: 'POST' });
      if (!res.ok) {
        setResumeError(t(lang, 'billing_action_error_generic'));
        return;
      }
      const next = (await res.json()) as BillingStatusOut;
      setStatus(next);
      router.refresh();
    } catch {
      setResumeError(t(lang, 'billing_action_error_unreachable'));
    } finally {
      setResumeBusy(false);
    }
  }

  // ── Transitioning: a first-ever subscribe just landed, waiting for the
  // refreshed `firstRun` prop to actually reflect it ───────────────────
  if (transitioning) {
    return (
      <div>
        <h1>{t(lang, 'billing_first_run_title')}</h1>
        <p className={styles.status}>{t(lang, 'billing_payment_method_saving')}</p>
      </div>
    );
  }

  // ── First run: `provisioning_state === 'pending_subscription'` ───────
  if (trackedFirstRun) {
    return (
      <div>
        <h1>{t(lang, 'billing_first_run_title')}</h1>
        <p className={styles.intro}>{t(lang, 'billing_first_run_intro')}</p>
        {panel === 'payment_method' && selectedPlan && subscribeSession ? (
          <PaymentMethodPanel
            lang={lang}
            mode="subscribe"
            subscribeSession={subscribeSession}
            onSuccess={handleSubscribed}
            onCancel={closePanel}
          />
        ) : (
          <>
            {subscribeError && <p className={styles.error}>{subscribeError}</p>}
            <PlanPicker lang={lang} mode="subscribe" onSelect={handlePlanSelected} busy={subscribeBusy} initialPlanId={initialPlanId} />
          </>
        )}
      </div>
    );
  }

  // ── Normal: an already-provisioned account ────────────────────────────
  const perKey = intervalKey(status.billing_interval);
  const renewsDate = status.cancel_at_period_end
    ? status.current_period_end
    : status.status === 'trialing'
      ? status.trial_end
      : status.current_period_end;

  return (
    <div>
      <h1>{t(lang, 'billing_title')}</h1>
      <p className={styles.intro}>{t(lang, 'billing_intro')}</p>

      {/* PLAN_PHASE16.md §8 Step 6: past_due + over_limit banners now share
          one component with `/app`'s own landing page (`components/app/
          BillingBanners`) rather than this file rendering its own
          `over_limit`-only `<div className={styles.banner}>` — the link to
          `/app/billing` the past_due half renders is a no-op link on THIS
          page (already here), which is harmless and simpler than a second,
          page-aware variant. */}
      <BillingBanners status={status} lang={lang} />

      <div className={styles.panel}>
        <h2>{t(lang, 'billing_status_title')}</h2>
        {!hasLiveSubscription ? (
          <p className={styles.status}>{t(lang, 'billing_status_no_subscription')}</p>
        ) : (
          <>
            <div className={styles.statusRow}>
              <div className={styles.statusItem}>
                <span className={styles.statusLabel}>{t(lang, 'billing_status_plan_label')}</span>
                <span className={styles.statusValue}>{status.plan_key ? planLabel(status.plan_key) : '—'}</span>
              </div>
              <div className={styles.statusItem}>
                <span className={styles.statusLabel}>{t(lang, 'billing_status_status_label')}</span>
                <span className={`${styles.badge} ${statusBadgeClass(status.status)}`}>{statusLabel(lang, status.status)}</span>
              </div>
              <div className={styles.statusItem}>
                <span className={styles.statusLabel}>{t(lang, 'billing_status_price_label')}</span>
                <span className={styles.statusValue}>
                  {formatMoney(status.amount_minor, status.currency)}
                  {perKey && <span className={styles.planPer}>{t(lang, perKey)}</span>}
                </span>
              </div>
              <div className={styles.statusItem}>
                <span className={styles.statusLabel}>
                  {t(lang, status.status === 'trialing' && !status.cancel_at_period_end ? 'billing_status_trial_ends_label' : 'billing_status_renews_label')}
                </span>
                <span className={styles.statusValue}>{renewsDate ? formatDate(renewsDate, DATE_LOCALE[lang]) : '—'}</span>
              </div>
              <div className={styles.statusItem}>
                <span className={styles.statusLabel}>{t(lang, 'billing_sites_used_label')}</span>
                <span className={styles.statusValue}>
                  {status.active_sites} / {status.site_limit === null ? t(lang, 'billing_sites_unlimited') : status.site_limit}
                </span>
              </div>
            </div>

            {status.cancel_at_period_end && (
              <p className={styles.status}>
                {t(lang, 'billing_status_cancel_scheduled').replace(
                  '{date}',
                  status.current_period_end ? formatDate(status.current_period_end, DATE_LOCALE[lang]) : '—',
                )}
              </p>
            )}

            {resumeError && <p className={styles.error}>{resumeError}</p>}

            <div className={styles.formActions}>
              <Button type="button" variant="ghost" onClick={() => setPanel(panel === 'plans' ? 'none' : 'plans')}>
                {t(lang, 'billing_change_plan_button')}
              </Button>
              {status.cancel_at_period_end ? (
                <Button type="button" variant="ghost" onClick={handleResume} disabled={resumeBusy}>
                  {resumeBusy ? t(lang, 'billing_resuming') : t(lang, 'billing_resume_button')}
                </Button>
              ) : (
                <Button type="button" variant="ghost" onClick={() => setCancelOpen(true)}>
                  {t(lang, 'billing_cancel_button')}
                </Button>
              )}
            </div>
          </>
        )}
      </div>

      {panel === 'plans' && (
        <>
          {subscribeError && <p className={styles.error}>{subscribeError}</p>}
          <PlanPicker
            lang={lang}
            mode={hasLiveSubscription ? 'change' : 'subscribe'}
            onSelect={handlePlanSelected}
            onCancel={hasLiveSubscription ? closePanel : undefined}
            busy={changeBusy || subscribeBusy}
          />
        </>
      )}

      {changeConfirm && (
        <div className={styles.confirmBox}>
          <h3>{t(lang, 'billing_change_confirm_title')}</h3>
          <p>
            {t(lang, 'billing_change_confirm_body')
              .replace('{current}', String(changeConfirm.currentSiteCount))
              .replace('{limit}', changeConfirm.newSiteLimit === null ? '—' : String(changeConfirm.newSiteLimit))}
          </p>
          {changeError && <p className={styles.error}>{changeError}</p>}
          <div className={styles.formActions}>
            <Button type="button" onClick={() => submitChange(changeConfirm.plan, true)} disabled={changeBusy}>
              {changeBusy ? t(lang, 'billing_change_applying') : t(lang, 'billing_change_confirm_button')}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setChangeConfirm(null)} disabled={changeBusy}>
              {t(lang, 'billing_back_button')}
            </Button>
          </div>
        </div>
      )}

      {panel === 'payment_method' &&
        (selectedPlan && subscribeSession ? (
          // No live subscription (a legacy/lapsed customer, not first-run —
          // `firstRun` already has its OWN copy of this same panel above)
          // picked a plan and now needs a card, same as first-run's flow.
          <PaymentMethodPanel
            lang={lang}
            mode="subscribe"
            subscribeSession={subscribeSession}
            onSuccess={handleSubscribed}
            onCancel={closePanel}
          />
        ) : (
          <PaymentMethodPanel lang={lang} mode="replace" onSuccess={handlePaymentMethodChanged} onCancel={closePanel} />
        ))}

      <div className={styles.panel}>
        <h2>{t(lang, 'billing_payment_method_title')}</h2>
        {status.pm_last4 ? (
          <>
            <p className={styles.cardSummary}>
              {t(lang, 'billing_payment_method_summary')
                .replace('{brand}', status.pm_brand ?? '')
                .replace('{last4}', status.pm_last4)
                .replace('{month}', status.pm_exp_month !== null ? String(status.pm_exp_month) : '—')
                .replace('{year}', status.pm_exp_year !== null ? String(status.pm_exp_year) : '—')}
            </p>
          </>
        ) : (
          <p className={styles.status}>{t(lang, 'billing_payment_method_none')}</p>
        )}
        <div className={styles.formActions}>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setSelectedPlan(null);
              setPanel(panel === 'payment_method' ? 'none' : 'payment_method');
            }}
          >
            {t(lang, 'billing_payment_method_replace_button')}
          </Button>
        </div>
      </div>

      <BillingAddressForm
        lang={lang}
        address={status.billing_address}
        hasPaymentMethod={Boolean(status.pm_last4)}
        onSaved={(next) => setStatus(next)}
      />

      <InvoiceList lang={lang} />

      {cancelOpen && (
        <CancelDialog
          lang={lang}
          currentPeriodEnd={status.current_period_end}
          busy={cancelBusy}
          error={cancelError}
          onConfirm={handleCancelConfirm}
          onDismiss={() => {
            setCancelOpen(false);
            setCancelError(null);
          }}
        />
      )}
    </div>
  );
}
