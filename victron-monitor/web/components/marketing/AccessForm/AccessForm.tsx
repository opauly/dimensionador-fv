'use client';

import { type ChangeEvent, type FormEvent, useState } from 'react';
import { Button, Eyebrow, Field, Input, ModeToggle, Select, Textarea } from '@/components/ui';
import styles from './AccessForm.module.css';

type Audience = 'installer' | 'owner';

type FormFields = {
  name: string;
  email: string;
  company: string;
  fleet: string;
  systemtype: string;
  installer: string;
  message: string;
};

const EMPTY_FIELDS: FormFields = {
  name: '',
  email: '',
  company: '',
  fleet: '',
  systemtype: '',
  installer: '',
  message: '',
};

// landing_template.html's own regex (L791) — deliberately not a stricter
// RFC 5322 pattern; this is a "did you forget the @" check ahead of a
// mailto:, not validation of an address that will ever be sent to a server.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const RECIPIENT = 'proyectos@paulyco.com';

type MailtoResult = { href: string; valid: boolean };

// Pure function, not a MutationObserver reacting to a DOM attribute change:
// the template's script (L786-869) had to observe #access-form's
// data-mode because a *separate* <script> block (L887-914) owned the click
// handler that set it, and script-order made a direct call unreliable
// (documented at L887-896 as the same bug class that broke the pricing
// toggle). Here `audience` and `fields` are both React state in the same
// component, so this just recomputes on every render — nothing to observe.
function buildMailto(audience: Audience, fields: FormFields): MailtoResult {
  const { name, email, company, fleet, systemtype, installer, message } = fields;
  let subject: string;
  let lines: string[];
  let valid: boolean;

  if (audience === 'owner') {
    valid = Boolean(name && systemtype && EMAIL_RE.test(email));
    subject = `VRM Monitor — Early access request from ${name || 'a system owner'}`;
    lines = [
      `Name: ${name}`,
      `Email: ${email}`,
      'Account type: System owner',
      `System type: ${systemtype}`,
      `Installer: ${installer || '(not specified)'}`,
      '',
      message || '(no message)',
    ];
  } else {
    valid = Boolean(name && company && fleet && EMAIL_RE.test(email));
    subject = `VRM Monitor — Early access request from ${company || name}`;
    lines = [
      `Name: ${name}`,
      `Company: ${company}`,
      `Email: ${email}`,
      'Account type: Solar installer',
      `Fleet size: ${fleet}`,
      '',
      message || '(no message)',
    ];
  }

  if (!valid) return { href: `mailto:${RECIPIENT}`, valid };
  // encodeURIComponent, not URLSearchParams — matches the template (L836-838)
  // exactly, and deliberately: URLSearchParams percent-encodes per
  // application/x-www-form-urlencoded (spaces become "+"), but a mailto:'s
  // query values are just percent-encoded text (RFC 6068) — some mail
  // clients render a literal "+" instead of a space if you build the link
  // with URLSearchParams here.
  const query = `subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join('\n'))}`;
  return { href: `mailto:${RECIPIENT}?${query}`, valid };
}

export function AccessForm() {
  const [audience, setAudience] = useState<Audience>('installer');
  const [fields, setFields] = useState<FormFields>(EMPTY_FIELDS);

  // One shared handler for every field, mirroring the template's single
  // `form.addEventListener('input'/'change', update)` (L856-857) — React
  // normalizes text/select/textarea into one onChange event, so this reads
  // `name`/`value` off whichever control fired it. Attached per-control
  // (not once on the <form>, which the template's DOM-level delegation
  // could do) because a controlled input/select/textarea's `value` prop
  // requires an `onChange` prop on that same element or React logs a
  // "you provided a value without an onChange" warning — a form-level
  // listener still updates state correctly (the native event bubbles), but
  // React's controlled-input check doesn't know that.
  function handleFieldChange(event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) {
    const { name, value } = event.target;
    setFields((prev) => ({ ...prev, [name]: value }));
  }

  const { href, valid } = buildMailto(audience, fields);

  // Belt-and-suspenders, same as the template (L846-852): aria-disabled +
  // pointer-events:none (CSS) block mouse clicks while invalid, but an <a>
  // has no native `disabled` the way a <button> would, so a focused,
  // keyboard-activated click still fires — this handler is what actually
  // stops that.
  function handleSendClick(event: FormEvent) {
    if (!valid) event.preventDefault();
  }

  return (
    <section id="cta" className={styles.band}>
      <div className="wrap">
        <Eyebrow className={styles.centeredEyebrow}>For owners &amp; installers</Eyebrow>
        <h2 className={styles.heading}>
          Every Victron system already has this data.
          <br />
          Most of it goes unread.
        </h2>
        <p className={`lede ${styles.lede}`}>
          We&apos;re onboarding a small group of owners and installers running Victron equipment before opening this
          up broadly. Tell us about your system — we&apos;ll generate a sample report from a real export, on us.
        </p>

        <form className={styles.form}>
          <div className={styles.audienceRow}>
            <span className={styles.audienceLabel}>I am a</span>
            <ModeToggle
              aria-label="I am a..."
              value={audience}
              onChange={(next) => setAudience(next as Audience)}
              options={[
                { value: 'installer', label: 'Solar installer' },
                { value: 'owner', label: 'System owner' },
              ]}
            />
          </div>

          <div className={styles.fieldRow}>
            <Field label="Name" htmlFor="af-name" required>
              <Input
                id="af-name"
                name="name"
                placeholder="Jane Solar"
                autoComplete="name"
                value={fields.name}
                onChange={handleFieldChange}
              />
            </Field>
            <Field label="Email" htmlFor="af-email" required>
              <Input
                type="email"
                id="af-email"
                name="email"
                placeholder="jane@yourcompany.com"
                autoComplete="email"
                value={fields.email}
                onChange={handleFieldChange}
              />
            </Field>
          </div>

          {audience === 'installer' && (
            <div className={styles.fieldRow}>
              <Field label="Company" htmlFor="af-company" required>
                <Input
                  id="af-company"
                  name="company"
                  placeholder="Your installer name"
                  autoComplete="organization"
                  value={fields.company}
                  onChange={handleFieldChange}
                />
              </Field>
              <Field label="Fleet size" htmlFor="af-fleet" required>
                <Select id="af-fleet" name="fleet" value={fields.fleet} onChange={handleFieldChange}>
                  <option value="">Select a range</option>
                  <option value="Fewer than 10 sites">Fewer than 10 sites</option>
                  <option value="10-50 sites">10 – 50 sites</option>
                  <option value="50+ sites">50+ sites</option>
                </Select>
              </Field>
            </div>
          )}

          {audience === 'owner' && (
            <div className={styles.fieldRow}>
              <Field label="System type" htmlFor="af-systemtype" required>
                <Select id="af-systemtype" name="systemtype" value={fields.systemtype} onChange={handleFieldChange}>
                  <option value="">Select your system</option>
                  <option value="Hybrid (grid + battery)">Hybrid (grid + battery)</option>
                  <option value="Off-grid">Off-grid</option>
                  <option value="Grid-tied, no battery">Grid-tied, no battery</option>
                </Select>
              </Field>
              <Field label="Installer" htmlFor="af-installer" optional>
                <Input
                  id="af-installer"
                  name="installer"
                  placeholder="Who installed your system?"
                  autoComplete="off"
                  value={fields.installer}
                  onChange={handleFieldChange}
                />
              </Field>
            </div>
          )}

          <Field label="What would you like to know?" htmlFor="af-message" optional>
            <Textarea
              id="af-message"
              name="message"
              placeholder="Tell us about your system, or ask us anything."
              value={fields.message}
              onChange={handleFieldChange}
            />
          </Field>

          <Button
            href={href}
            arrow
            className={styles.sendLink}
            aria-disabled={!valid}
            onClick={handleSendClick}
          >
            Send request
          </Button>
          <div className={styles.formFoot}>
            <span className={styles.formNote}>
              Opens in your email client, addressed to Pauly &amp; Co. — nothing sends automatically.
            </span>
            <a href="#preview" className={styles.formNote} style={{ textDecoration: 'none' }}>
              See the sample report again →
            </a>
          </div>
        </form>
      </div>
    </section>
  );
}
