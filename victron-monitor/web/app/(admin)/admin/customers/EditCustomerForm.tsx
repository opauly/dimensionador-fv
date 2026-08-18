'use client';

import { useActionState, useEffect } from 'react';
import { Button, Field, Input, Select, Textarea } from '@/components/ui';
import type { AdminCustomerRow } from '@/lib/server/db/admin';
import { PLANS, type PlanKey } from '@/lib/plans';
import { COUNTRIES } from '@/lib/countries';
import { updateCustomerAction, type UpdateCustomerState } from './actions';
import styles from './customers.module.css';

const PLAN_KEYS = Object.keys(PLANS) as PlanKey[];
const COUNTRY_CODES = Object.keys(COUNTRIES);

// Edit form for one customer row — the admin-only counterpart of
// `app/(portal)/app/profile/ProfileForm.tsx`, but with the wider whitelist
// only `/admin/*` may write (`plan`, `site_limit`, `account_type` — never
// reachable from a customer's own `/app/profile`, see
// `lib/server/db/admin.ts:ADMIN_CUSTOMER_WHITELIST`'s own comment).
// `auth_email`/invite state is deliberately NOT editable here — that's
// `CustomersManager`'s "Enviar/Reenviar invitación" buttons
// (`lib/server/invites.ts`), a distinct action from a generic field edit.
export function EditCustomerForm({ customer, onDone }: { customer: AdminCustomerRow; onDone: () => void }) {
  const boundAction = updateCustomerAction.bind(null, customer.id);
  const [state, formAction, pending] = useActionState<UpdateCustomerState, FormData>(boundAction, {});

  useEffect(() => {
    if (state.success) onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onDone intentionally excluded, see SiteForm.tsx's own precedent
  }, [state.success]);

  return (
    <form action={formAction} className={styles.form}>
      <div className={styles.fieldRow}>
        <Field label="Nombre" htmlFor={`ec-name-${customer.id}`} required>
          <Input id={`ec-name-${customer.id}`} name="name" defaultValue={customer.name} required disabled={pending} />
        </Field>
        <Field label="Tipo de cuenta" htmlFor={`ec-type-${customer.id}`}>
          <Select id={`ec-type-${customer.id}`} name="accountType" defaultValue={customer.account_type} disabled={pending}>
            <option value="owner">Owner (dueño de sitio)</option>
            <option value="installer">Installer (instalador)</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Plan" htmlFor={`ec-plan-${customer.id}`}>
          <Select id={`ec-plan-${customer.id}`} name="plan" defaultValue={customer.plan} disabled={pending}>
            {PLAN_KEYS.includes(customer.plan as PlanKey) ? null : <option value={customer.plan}>{customer.plan}</option>}
            {PLAN_KEYS.map((key) => (
              <option key={key} value={key}>
                {PLANS[key].label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Límite de sitios" htmlFor={`ec-limit-${customer.id}`} optional optionalLabel=" (vacío = ilimitado)">
          <Input
            id={`ec-limit-${customer.id}`}
            name="siteLimit"
            type="number"
            min="0"
            step="1"
            defaultValue={customer.site_limit ?? ''}
            disabled={pending}
          />
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="País" htmlFor={`ec-country-${customer.id}`}>
          <Select id={`ec-country-${customer.id}`} name="country" defaultValue={customer.country ?? 'CR'} disabled={pending}>
            {COUNTRY_CODES.map((code) => (
              <option key={code} value={code}>
                {COUNTRIES[code]}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Idioma del panel" htmlFor={`ec-lang-${customer.id}`}>
          <Select id={`ec-lang-${customer.id}`} name="uiLanguage" defaultValue={customer.ui_language} disabled={pending}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Nombre de contacto" htmlFor={`ec-contact-name-${customer.id}`} optional>
          <Input id={`ec-contact-name-${customer.id}`} name="contactName" defaultValue={customer.contact_name ?? ''} disabled={pending} />
        </Field>
        <Field label="Correo de contacto" htmlFor={`ec-contact-email-${customer.id}`} optional>
          <Input
            id={`ec-contact-email-${customer.id}`}
            name="contactEmail"
            type="email"
            defaultValue={customer.contact_email ?? ''}
            disabled={pending}
          />
        </Field>
      </div>

      <Field label="Notas internas" htmlFor={`ec-notes-${customer.id}`} optional>
        <Textarea id={`ec-notes-${customer.id}`} name="notes" rows={2} defaultValue={customer.notes ?? ''} disabled={pending} />
      </Field>

      <p className={styles.subtle}>
        Correo de acceso: <strong>{customer.auth_email ?? '— sin configurar —'}</strong> — no editable desde este formulario;
        cambiar el correo de acceso de un cliente ya invitado no está soportado todavía.
      </p>

      {state.error && <p className={styles.error}>{state.error}</p>}

      <div className={styles.formActions}>
        <Button type="submit" disabled={pending}>
          {pending ? 'Guardando…' : 'Guardar'}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone} disabled={pending}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}
