'use client';

// `POST /api/billing/cancel` `{mode: 'at_period_end'}` (PLAN_PHASE16.md §5.3
// / §8 Step 5, Q4: graceful-only in the customer-facing UI). A styled inline
// panel (`.confirmBox`, same box `PlanPicker`'s over-limit confirmation
// uses) rather than a native `<dialog>` — this app has no modal primitive
// yet (`VrmLinkPanel.tsx`'s own disconnect flow uses a plain
// `window.confirm()` for a one-line question; this one needs real copy with
// a real date substituted in, so it gets its own small component instead).
// Purely presentational + the confirm/dismiss callbacks — `BillingManager`
// owns the actual fetch and the busy/error state, same division of labor
// every other panel in this folder uses.
import { Button } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
import { formatDate, type DateLocale } from '@/lib/dates';
import styles from './billing.module.css';

const DATE_LOCALE: Record<Lang, DateLocale> = { en: 'en-US', es: 'es-CR' };

export type CancelDialogProps = {
  lang: Lang;
  currentPeriodEnd: string | null;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onDismiss: () => void;
};

export function CancelDialog({ lang, currentPeriodEnd, busy, error, onConfirm, onDismiss }: CancelDialogProps) {
  const dateLabel = currentPeriodEnd ? formatDate(currentPeriodEnd, DATE_LOCALE[lang]) : '—';
  return (
    <div className={styles.confirmBox} role="alertdialog" aria-modal="true" aria-labelledby="cancel-dialog-title">
      <h3 id="cancel-dialog-title">{t(lang, 'billing_cancel_dialog_title')}</h3>
      <p>{t(lang, 'billing_cancel_dialog_body').replace('{date}', dateLabel)}</p>
      {error && <p className={styles.error}>{error}</p>}
      <div className={styles.formActions}>
        <Button type="button" onClick={onConfirm} disabled={busy}>
          {busy ? t(lang, 'billing_canceling') : t(lang, 'billing_cancel_dialog_confirm_button')}
        </Button>
        <Button type="button" variant="ghost" onClick={onDismiss} disabled={busy}>
          {t(lang, 'billing_cancel_dialog_dismiss_button')}
        </Button>
      </div>
    </div>
  );
}
