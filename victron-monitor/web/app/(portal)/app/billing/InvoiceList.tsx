'use client';

// `GET /api/billing/invoices` (PLAN_PHASE16.md §5.1 / §8 Step 5) — mirrored
// renewals, newest first, paginated. Self-contained: fetches its own first
// page on mount rather than taking invoices as a prop, because this is the
// one panel on `/app/billing` a `firstRun` customer never sees at all
// (§8 Step 5: "hides cancel/invoices/address entirely") and a normal
// customer may never need to page through — no reason to make the parent
// page's initial server render wait on it.
import { startTransition, useEffect, useState } from 'react';
import { Button, Table } from '@/components/ui';
import { t, type Lang, type StringKey } from '@/lib/i18n/strings';
import { formatDate, type DateLocale } from '@/lib/dates';
import type { BillingInvoiceOut, BillingInvoicesOut } from '@/lib/server/pipeline';
import styles from './billing.module.css';

const DATE_LOCALE: Record<Lang, DateLocale> = { en: 'en-US', es: 'es-CR' };
const PAGE_SIZE = 20;

const INVOICE_STATUS_KEY: Record<string, StringKey> = {
  paid: 'billing_invoice_status_paid',
  open: 'billing_invoice_status_open',
  draft: 'billing_invoice_status_draft',
  void: 'billing_invoice_status_void',
  uncollectible: 'billing_invoice_status_uncollectible',
};

function statusLabel(lang: Lang, status: string | null): string {
  if (!status) return '—';
  const key = INVOICE_STATUS_KEY[status];
  return key ? t(lang, key) : status;
}

function formatMoney(minor: number | null, currency: string | null): string {
  if (minor === null) return '—';
  const amount = (minor / 100).toFixed(2);
  return currency === 'USD' ? `$${amount}` : `${amount} ${currency ?? ''}`.trim();
}

function periodLabel(lang: Lang, invoice: BillingInvoiceOut): string {
  if (!invoice.period_start || !invoice.period_end) return '—';
  return `${formatDate(invoice.period_start, DATE_LOCALE[lang])} → ${formatDate(invoice.period_end, DATE_LOCALE[lang])}`;
}

export function InvoiceList({ lang }: { lang: Lang }) {
  const [invoices, setInvoices] = useState<BillingInvoiceOut[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // `startTransition` here matches `VrmFleetManager.tsx:refresh()`'s own
  // shape — this repo's established pattern for "fetch-and-setState from an
  // effect or a button click," and what keeps `react-hooks/set-state-in-
  // effect` satisfied without disabling it.
  function load(offset: number) {
    startTransition(async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/billing/invoices?limit=${PAGE_SIZE}&offset=${offset}`);
        if (!res.ok) throw new Error('failed');
        const data = (await res.json()) as BillingInvoicesOut;
        setInvoices((prev) => (offset === 0 ? data.invoices : [...prev, ...data.invoices]));
        setHasMore(data.has_more);
      } catch {
        setError(t(lang, 'billing_invoices_error'));
      } finally {
        setLoading(false);
      }
    });
  }

  useEffect(() => {
    load(0);
    // Runs once on mount — same "load once, re-call explicitly after a
    // mutation" shape `VrmFleetManager.tsx`'s own effect uses.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className={styles.panel}>
      <h2>{t(lang, 'billing_invoices_title')}</h2>
      {loading && invoices.length === 0 ? (
        <p className={styles.status}>{t(lang, 'billing_invoices_loading')}</p>
      ) : error ? (
        <p className={styles.error}>{error}</p>
      ) : invoices.length === 0 ? (
        <p className={styles.invoiceEmpty}>{t(lang, 'billing_invoices_empty')}</p>
      ) : (
        <>
          <Table>
            <thead>
              <tr>
                <th>{t(lang, 'billing_invoices_col_period')}</th>
                <th>{t(lang, 'billing_invoices_col_status')}</th>
                <th>{t(lang, 'billing_invoices_col_amount')}</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <tr key={invoice.id}>
                  <td>{periodLabel(lang, invoice)}</td>
                  <td>{statusLabel(lang, invoice.status)}</td>
                  <td>{formatMoney(invoice.total_minor, invoice.currency)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
          {hasMore && (
            <div className={styles.formActions}>
              <Button type="button" variant="ghost" onClick={() => load(invoices.length)} disabled={loading}>
                {t(lang, 'billing_invoices_load_more')}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
