'use client';

// The `/signup` client half (PLAN_PHASE16.md §5.5 Step 1 / §8 Step 5.5).
// Always rendered with `t('en', ...)` — same convention `/login`,
// `/forgot`, and `/activate` already follow (their own comments: a
// visitor's `ui_language` preference isn't known/enforced until AFTER they
// have a `vrm.customers` row, which doesn't exist yet at this point in the
// flow). The `ui_language` <select> below is the visitor's PREFERENCE for
// their future account, not a switch for this page's own copy.
import { useActionState, useState } from 'react';
import Link from 'next/link';
import { Button, Field, Input, ModeToggle, Select } from '@/components/ui';
import { t } from '@/lib/i18n/strings';
import { planLabel } from '@/lib/plans';
import type { AccountType } from '@/lib/server/db/types';
import type { SelfServePlanOut } from '@/lib/server/db/signup';
import { signUpAction, type SignupFormState } from './actions';
import styles from './signup.module.css';

const INITIAL_STATE: SignupFormState = {};

export type SignupFormProps = {
  plansByAccountType: Record<AccountType, SelfServePlanOut[]>;
  initialAccountType: AccountType;
  initialPlanId: string | null;
};

function formatMoney(amountMinor: number, currency: string): string {
  const amount = (amountMinor / 100).toFixed(2);
  return currency === 'USD' ? `$${amount}` : `${amount} ${currency}`;
}

function intervalKey(interval: string): 'billing_plan_per_month' | 'billing_plan_per_year' | null {
  if (interval === 'month') return 'billing_plan_per_month';
  if (interval === 'year') return 'billing_plan_per_year';
  return null;
}

function firstPlanId(plans: SelfServePlanOut[]): string | null {
  return plans[0]?.id ?? null;
}

/** Computed from the actual monthly/annual prices in `plans`, not a
 * hardcoded percentage — stays correct if pricing ever changes rather than
 * silently drifting from what the cards actually charge. `null` if this
 * plan isn't a `year` row, or its `month` sibling (same `plan_key`) isn't
 * in the list to compare against. */
function annualSavingsPct(plan: SelfServePlanOut, allPlans: SelfServePlanOut[]): number | null {
  if (plan.billing_interval !== 'year') return null;
  const monthly = allPlans.find((p) => p.plan_key === plan.plan_key && p.billing_interval === 'month' && p.currency === plan.currency);
  if (!monthly || monthly.amount_minor <= 0) return null;
  const annualizedMonthly = monthly.amount_minor * 12;
  const savings = annualizedMonthly - plan.amount_minor;
  if (savings <= 0) return null;
  return Math.round((savings / annualizedMonthly) * 100);
}

export function SignupForm({ plansByAccountType, initialAccountType, initialPlanId }: SignupFormProps) {
  const [state, formAction, pending] = useActionState(signUpAction, INITIAL_STATE);
  const [accountType, setAccountType] = useState<AccountType>(initialAccountType);
  const [planId, setPlanId] = useState<string | null>(() => {
    const initialPlans = plansByAccountType[initialAccountType];
    return initialPlanId && initialPlans.some((p) => p.id === initialPlanId) ? initialPlanId : firstPlanId(initialPlans);
  });
  // Gates the submit button rather than relying on the checkbox's own
  // `required` — the form already renders `noValidate` (see below), so a
  // plain HTML `required` wouldn't stop a submit anyway. `signUpAction`
  // also re-checks this server-side (`actions.ts`'s own `agreed_to_terms`
  // schema field) for a direct POST that skips this component entirely.
  const [agreed, setAgreed] = useState(false);

  const plans = plansByAccountType[accountType];

  function handleAccountTypeChange(next: string) {
    const nextType = next as AccountType;
    setAccountType(nextType);
    const nextPlans = plansByAccountType[nextType];
    setPlanId((current) => (current && nextPlans.some((p) => p.id === current) ? current : firstPlanId(nextPlans)));
  }

  if (state.submitted) {
    return (
      <div>
        <h1 className={styles.title}>{t('en', 'signup_title')}</h1>
        <p className={styles.confirmation}>{t('en', 'signup_confirmation').replace('{email}', state.email ?? '')}</p>
        <Link href="/login" className={styles.backLink}>
          {t('en', 'signup_back_to_login')}
        </Link>
      </div>
    );
  }

  return (
    <form action={formAction} className={styles.form} noValidate>
      <h1 className={styles.title}>{t('en', 'signup_title')}</h1>
      <div className={styles.trialBanner}>
        <span className={styles.trialBannerDot} aria-hidden="true" />
        {t('en', 'signup_trial_banner')}
      </div>
      <p className={styles.subtitle}>{t('en', 'signup_subtitle')}</p>

      {/* The honeypot (§6.6) — a real visitor never tabs into or sees this
          (aria-hidden + tabIndex=-1 + off-screen CSS); a naive bot filling
          every field on the page will. `submitSignup()` treats a non-empty
          value here as the same neutral success with no side effects. */}
      <div className={styles.honeypot} aria-hidden="true">
        <label htmlFor="signup-website">Website</label>
        <input id="signup-website" name="website" type="text" tabIndex={-1} autoComplete="off" />
      </div>

      <Field label={t('en', 'signup_name')} htmlFor="signup-name" required>
        <Input id="signup-name" name="name" autoComplete="name" required maxLength={120} disabled={pending} />
      </Field>

      <Field label={t('en', 'signup_email')} htmlFor="signup-email" required>
        <Input id="signup-email" name="email" type="email" autoComplete="email" required maxLength={254} disabled={pending} />
      </Field>

      <Field label={t('en', 'signup_account_type_label')} htmlFor="signup-account-type" className={styles.accountTypeField}>
        <input type="hidden" name="account_type" value={accountType} />
        <ModeToggle
          aria-label={t('en', 'signup_account_type_label')}
          value={accountType}
          onChange={handleAccountTypeChange}
          options={[
            { value: 'installer', label: t('en', 'signup_account_type_installer') },
            { value: 'owner', label: t('en', 'signup_account_type_owner') },
          ]}
        />
      </Field>

      <Field label={t('en', 'signup_language_label')} htmlFor="signup-language">
        <Select id="signup-language" name="ui_language" defaultValue="en" disabled={pending}>
          <option value="en">{t('en', 'lang_en')}</option>
          <option value="es">{t('en', 'lang_es')}</option>
        </Select>
      </Field>

      <div className={styles.plans}>
        <span className={styles.plansLabel}>{t('en', 'signup_plan_label')}</span>
        <input type="hidden" name="plan_id" value={planId ?? ''} />
        {plans.length === 0 ? (
          <p className={styles.status}>{t('en', 'signup_plan_none')}</p>
        ) : (
          <div className={styles.planGrid}>
            {plans.map((plan) => {
              const perKey = intervalKey(plan.billing_interval);
              const sitesLabel =
                plan.site_limit === null
                  ? t('en', 'billing_plan_sites_unlimited')
                  : t('en', 'billing_plan_sites_up_to').replace('{limit}', String(plan.site_limit));
              const selected = plan.id === planId;
              const savingsPct = annualSavingsPct(plan, plans);
              return (
                <button
                  type="button"
                  key={plan.id}
                  className={[styles.planCard, selected && styles.planCardSelected].filter(Boolean).join(' ')}
                  aria-pressed={selected}
                  disabled={pending}
                  onClick={() => setPlanId(plan.id)}
                >
                  <span className={styles.planName}>{planLabel(plan.plan_key)}</span>
                  <span className={styles.planSites}>{sitesLabel}</span>
                  <span className={styles.planPrice}>
                    <span className={styles.planPriceAmount}>
                      {formatMoney(plan.amount_minor, plan.currency)}
                      {perKey && <span className={styles.planPer}>{t('en', perKey)}</span>}
                    </span>
                    {savingsPct !== null && (
                      <span className={styles.planSavings}>{t('en', 'billing_plan_annual_savings').replace('{pct}', String(savingsPct))}</span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <label className={styles.agreeRow}>
        <input
          type="checkbox"
          name="agreed_to_terms"
          checked={agreed}
          onChange={(e) => setAgreed(e.target.checked)}
          disabled={pending}
        />
        <span>
          {t('en', 'signup_agree_prefix')}{' '}
          <Link href="/terms" target="_blank">
            {t('en', 'signup_agree_terms')}
          </Link>{' '}
          {t('en', 'signup_agree_and')}{' '}
          <Link href="/privacy" target="_blank">
            {t('en', 'signup_agree_privacy')}
          </Link>
        </span>
      </label>

      <Button type="submit" disabled={pending || !agreed} className={styles.submit}>
        {pending ? t('en', 'signup_submitting') : t('en', 'signup_submit')}
      </Button>
      <Link href="/login" className={styles.backLink}>
        {t('en', 'signup_have_account')}
      </Link>
    </form>
  );
}
