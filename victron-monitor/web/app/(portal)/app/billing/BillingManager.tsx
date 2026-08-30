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
  // A LOCAL-only value (vrm_api/billing.py:apply_entitlements(), migration
  // 030, 2026-08-29 fix) — never an ONVO status. Reported here instead of
  // the raw "trialing" ONVO would otherwise still show for a trial that
  // genuinely expired with no card on file (vrm_api/routers/billing.py:
  // _status_response()'s own override).
  trial_expired: 'billing_status_trial_expired',
};

function statusLabel(lang: Lang, status: string | null): string {
  if (!status) return t(lang, 'billing_status_unknown');
  const key = STATUS_LABEL_KEY[status];
  return key ? t(lang, key) : status;
}

function statusBadgeClass(status: string | null): string {
  if (status === 'active' || status === 'trialing') return styles.badgeGood;
  if (status === 'past_due' || status === 'unpaid' || status === 'incomplete' || status === 'trial_expired') return styles.badgeWarn;
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
  // The "Select a plan, but no card on file yet" flow (Oscar's request,
  // 2026-08-21): `pendingPlanChange` remembers what the customer was
  // actually trying to do while `panel` auto-switches to `payment_method`
  // — no second click on Add/Replace Card required, the customer already
  // clicked Select once. Once a card is saved, `pendingPlanConfirm` holds
  // the SAME plan for one explicit confirmation step (never auto-applies a
  // billing change right after a card save) before `submitChange()` runs
  // for real.
  const [pendingPlanChange, setPendingPlanChange] = useState<BillingPlanOut | null>(null);
  const [pendingPlanConfirm, setPendingPlanConfirm] = useState<BillingPlanOut | null>(null);

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
    setPendingPlanChange(null);
    setPendingPlanConfirm(null);
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
          // Clears the post-card confirmation box, if that's how we got
          // here (a plan that needed BOTH a card and a limit override) —
          // one confirmation box at a time, not two stacked.
          setPendingPlanConfirm(null);
          setChangeConfirm({
            plan,
            currentSiteCount: body.current_site_count ?? status.active_sites,
            newSiteLimit: body.new_site_limit === undefined ? plan.site_limit : body.new_site_limit,
          });
          return;
        }
        // A customer with no card on file yet (e.g. a trial that was never
        // completed) gets a real, actionable sentence here rather than the
        // generic one — `vrm_api/routers/billing.py:post_subscription_
        // change()`'s own `400 no_payment_method`, found 2026-08-21: this
        // branch previously set `changeError` correctly but nothing in the
        // "plans" panel ever rendered it, so every change failure — this
        // one included — looked like the Select button silently did
        // nothing.
        if (body?.error === 'no_payment_method') {
          // Auto-open the card form right away — the customer already
          // clicked Select once, they shouldn't have to click Add Card
          // separately too (Oscar's request, 2026-08-21).
          // `pendingPlanChange` is what lets `handlePaymentMethodChanged`
          // pick this back up as a confirmation step once the card saves,
          // instead of just closing the panel like a normal card-replace
          // does.
          setChangeError(t(lang, 'billing_change_error_no_payment_method'));
          setSelectedPlan(null);
          setPendingPlanChange(plan);
          setPanel('payment_method');
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
    if (pendingPlanChange) {
      // A card was just added specifically to unblock the plan change the
      // customer already asked for (Select, back when `submitChange` first
      // hit `no_payment_method`) — pick that back up as an explicit
      // confirmation step rather than silently applying it now that a card
      // exists (Oscar's request, 2026-08-21: "remember to add a
      // confirmation modal before the change is in place").
      setPanel('none');
      setChangeError(null);
      setPendingPlanConfirm(pendingPlanChange);
      setPendingPlanChange(null);
      router.refresh();
      return;
    }
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

      {/* Rendered directly under the Subscription panel above, where the
         "Cancel subscription" button that opens it actually lives (Oscar's
         report, 2026-08-21: this used to sit at the very bottom of the
         page, after Payment Method / Billing Address / Billing History —
         a customer who clicked Cancel had to scroll past three unrelated
         sections to see the confirmation they just asked for). */}
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

      {panel === 'plans' && (
        <>
          {subscribeError && <p className={styles.error}>{subscribeError}</p>}
          {/* `changeError` (mode="change" — a customer with a live
             subscription) was previously set but never rendered anywhere
             on this panel — found 2026-08-21 from a real "Select does
             nothing" report. `changeConfirm`'s own confirm box (below)
             renders it separately in the over-limit case; this covers
             every OTHER failure (e.g. no_payment_method). */}
          {changeError && <p className={styles.error}>{changeError}</p>}
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

      {/* The confirmation step after a card was just added specifically to
         unblock a plan change (Oscar's request, 2026-08-21) — a different
         box than `changeConfirm` above (that one is the over-site-limit
         case), but the same "never apply a billing change without an
         explicit confirm click" shape. */}
      {pendingPlanConfirm && (
        <div className={styles.confirmBox}>
          <h3>{t(lang, 'billing_change_after_card_title')}</h3>
          <p>{t(lang, 'billing_change_after_card_body').replace('{plan}', planLabel(pendingPlanConfirm.plan_key))}</p>
          {changeError && <p className={styles.error}>{changeError}</p>}
          <div className={styles.formActions}>
            <Button type="button" onClick={() => submitChange(pendingPlanConfirm, false)} disabled={changeBusy}>
              {changeBusy ? t(lang, 'billing_change_applying') : t(lang, 'billing_change_confirm_button')}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setPendingPlanConfirm(null)} disabled={changeBusy}>
              {t(lang, 'billing_back_button')}
            </Button>
          </div>
        </div>
      )}

      {/* `changeError` here specifically (not the copy inside the
         `pendingPlanConfirm` box above) covers the moment right after
         Select discovers `no_payment_method` and auto-opens this panel —
         positioned directly above it, and above the static "Payment
         Method" status block below, per Oscar's explicit request
         (2026-08-21) that this read as one connected flow instead of an
         error at the top of the page disconnected from the card form. */}
      {panel === 'payment_method' && pendingPlanChange && changeError && <p className={styles.error}>{changeError}</p>}

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
            {/* "Add card" when there's genuinely nothing on file yet,
               "Replace card" once there is (Oscar's request, 2026-08-21 —
               this always said "Replace card", even for a trial customer
               who has never entered one). */}
            {status.pm_last4 ? t(lang, 'billing_payment_method_replace_button') : t(lang, 'billing_payment_method_add_button')}
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
    </div>
  );
}
