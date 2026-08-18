import type { CSSProperties } from 'react';
import { Button, Eyebrow, Field, Input, ModeToggle, Panel, Select, Stat, Textarea } from '@/components/ui';
import {
  BLUE_CANDIDATES,
  BLUE_LABELS,
  BTN_LABELS,
  BTN_TREATMENTS,
  deriveDeepHex,
  hexToRgbTriplet,
  parseBlueParam,
  parseBtnParam,
  type BlueCandidate,
  type BtnTreatment,
} from './colors';
import styles from './styleguide.module.css';

// Next 16's typed-routes PageProps<'/styleguide'> only exists once this
// route has been through a build (it's generated from the actual app/
// directory into .next/types). Spelling the shape out here instead avoids
// a chicken-and-egg dependency on build order for `npm run typecheck`.
type StyleguidePageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

// React's CSSProperties type doesn't know about arbitrary custom properties;
// this is the minimal, explicit (no `any`) extension for the three tokens
// the ?blue=/?btn= A/B actually rebinds.
type BrandVars = CSSProperties & {
  '--victron'?: string;
  '--victron-rgb'?: string;
  '--btn-fill'?: string;
};

function buildHref(blue: BlueCandidate, btn: BtnTreatment): string {
  return `/styleguide?blue=${blue}&btn=${btn}`;
}

export default async function StyleguidePage({ searchParams }: StyleguidePageProps) {
  const params = await searchParams;
  const blue = parseBlueParam(params.blue);
  const btn = parseBtnParam(params.btn);

  // §1.8's whole point: re-bind --victron (+ its rgb companion, for the
  // rgba() glows) and --btn-fill at the root of this page only. Every
  // component below reads those same tokens it would read on the real
  // site — nothing here is a styleguide-only copy of Button/Panel/etc.
  //
  // 'deep' does NOT read tokens.css's fixed --victron-deep (#046c90) here —
  // that value was derived once from #0089b6 specifically, so reusing it
  // unchanged for every candidate made the primary button look identical
  // across all three ?blue= choices, defeating the point of an A/B page
  // (confirmed by clicking through it: no visible change). deriveDeepHex()
  // reproduces the same relative lightness/saturation drop against whichever
  // base blue is selected, so 'deep' stays a meaningfully darker version of
  // *that* candidate. tokens.css's shipped #046c90 is untouched by this.
  const deepHex = deriveDeepHex(blue);
  const brandVars: BrandVars = {
    '--victron': `#${blue}`,
    '--victron-rgb': hexToRgbTriplet(blue),
    '--btn-fill': btn === 'deep' ? `#${deepHex}` : 'var(--victron)',
  };

  return (
    <main className={`wrap ${styles.page}`} style={brandVars}>
      <div className={styles.intro}>
        <Eyebrow>Design system</Eyebrow>
        <h1 style={{ fontSize: 'var(--text-h2)' }}>Styleguide</h1>
        <p>
          Every components/ui/* primitive built in Phase 14 Step 1, ported from{' '}
          <code className="mono">victron-monitor/landing-page/landing_template.html</code>. Compare this page
          against <code className="mono">landing-page/landing_page.html</code> at 1440px — buttons, stat tiles,
          eyebrows and fields should be visually indistinguishable at the default blue.
        </p>
      </div>

      <div className={styles.abControls}>
        <div className={styles.abGroup}>
          <span className={styles.abGroupLabel}>§1.8 brand blue — current: {BLUE_LABELS[blue]}</span>
          <div className={styles.abLinks}>
            {BLUE_CANDIDATES.map((candidate) => (
              <a
                key={candidate}
                href={buildHref(candidate, btn)}
                className={`${styles.abLink} ${candidate === blue ? styles.abLinkActive : ''}`}
              >
                ?blue={candidate}
              </a>
            ))}
          </div>
        </div>
        <div className={styles.abGroup}>
          <span className={styles.abGroupLabel}>
            §1.8 button fill — current: {BTN_LABELS[btn]}
            {btn === 'deep' && ` (derived from #${blue} → #${deepHex} for this candidate)`}
          </span>
          <div className={styles.abLinks}>
            {BTN_TREATMENTS.map((treatment) => (
              <a
                key={treatment}
                href={buildHref(blue, treatment)}
                className={`${styles.abLink} ${treatment === btn ? styles.abLinkActive : ''}`}
              >
                ?btn={treatment}
              </a>
            ))}
          </div>
        </div>
      </div>

      {/* ---------- Button ---------- */}
      <section className={styles.section}>
        <span className={styles.sectionLabel}>Button — .btn / .btn.ghost</span>
        <div className={styles.row}>
          <Button href="#">Request early access</Button>
          <Button href="#" arrow>
            Request early access
          </Button>
          <Button href="#" variant="ghost">
            See a sample report
          </Button>
          <Button type="button">Button element</Button>
        </div>
        <p className={styles.footNote}>Tab through these to check the focus-visible ring; hover to check the glow.</p>
      </section>

      {/* ---------- Panel: card ---------- */}
      <section className={styles.section}>
        <span className={styles.sectionLabel}>Panel variant=&quot;card&quot; — .card, inside .modules&apos; grid chrome</span>
        <div className={styles.cardGrid}>
          <Panel variant="card">
            <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--mute)' }}>
              Scoring
            </span>
            <h3>Health score</h3>
            <p style={{ fontSize: 13.5 }}>0–100, alongside solar generation, grid independence, and events.</p>
          </Panel>
          <Panel variant="card" interactive led>
            <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--mute)' }}>
              Narrative
            </span>
            <h3>AI narrative (interactive, led)</h3>
            <p style={{ fontSize: 13.5 }}>Hover this one — background lifts to --panel-2, like inside .modules.</p>
          </Panel>
          <Panel variant="card" led>
            <span className="mono" style={{ fontSize: 10.5, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--mute)' }}>
              Events
            </span>
            <h3>Outages &amp; alarms</h3>
            <p style={{ fontSize: 13.5 }}>The small dot top-right is .card .led.</p>
          </Panel>
        </div>
      </section>

      {/* ---------- Panel: readout ---------- */}
      <section className={styles.section}>
        <span className={styles.sectionLabel}>Panel variant=&quot;readout&quot; — .readout, with Stat + Eyebrow inside</span>
        <div className={styles.readoutDemo}>
          <Panel variant="readout" hairline>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 18,
                paddingBottom: 16,
                borderBottom: '1px solid var(--line)',
              }}
            >
              <span className="mono" style={{ fontSize: 12, color: 'var(--paper-dim)' }}>
                SAMPLE SITE <b style={{ color: '#fff', fontWeight: 500 }}>· 7-DAY REPORT</b>
              </span>
              <Eyebrow amber>Live</Eyebrow>
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: 16,
                marginBottom: 18,
              }}
            >
              <Stat label="Health score" value={84} unit="/100 · Good" good />
              <Stat label="Solar generated" value={429} unit="kWh" />
              <Stat label="Grid independence" value={96.1} unit="%" />
              <Stat label="Alarm episodes" value={3} unit="events" />
            </div>
          </Panel>
        </div>
      </section>

      {/* ---------- Panel: price ---------- */}
      <section className={styles.section}>
        <span className={styles.sectionLabel}>Panel variant=&quot;price&quot; — .price-card / .price-card.featured</span>
        <div className={styles.priceGrid}>
          <Panel variant="price">
            <h3>Starter</h3>
            <p style={{ margin: '20px 0' }}>$14 / site / mo</p>
            <Button href="#" variant="ghost">
              Get started
            </Button>
          </Panel>
          <Panel variant="price" featured hairline featuredTag="Most installers">
            <h3>Growth</h3>
            <p style={{ margin: '20px 0' }}>$9 / site / mo</p>
            <Button href="#">Get started</Button>
          </Panel>
          <Panel variant="price">
            <h3>Fleet</h3>
            <p style={{ margin: '20px 0' }}>Custom</p>
            <Button href="#" variant="ghost">
              Talk to us
            </Button>
          </Panel>
        </div>
      </section>

      {/* ---------- Stat, standalone ---------- */}
      <section className={styles.section}>
        <span className={styles.sectionLabel}>Stat, standalone — .stat / .stat.good</span>
        <div className={styles.statGrid}>
          <Stat label="Health score" value={84} unit="/100 · Good" good />
          <Stat label="Solar generated" value={429} unit="kWh" />
          <Stat label="Grid independence" value={96.1} unit="%" />
          <Stat label="Alarm episodes" value={3} unit="events" />
        </div>
      </section>

      {/* ---------- Eyebrow ---------- */}
      <section className={styles.section}>
        <span className={styles.sectionLabel}>Eyebrow — .eyebrow / .eyebrow.amber</span>
        <div className={styles.row}>
          <Eyebrow>Built on Victron VRM data</Eyebrow>
          <Eyebrow amber>Live</Eyebrow>
        </div>
        <p className={styles.footNote}>The amber dot pulses; disabled entirely under prefers-reduced-motion.</p>
      </section>

      {/* ---------- Field ---------- */}
      <section className={styles.section}>
        <span className={styles.sectionLabel}>Field — .field / .field label / .field input,select,textarea</span>
        <div className={styles.fieldDemo}>
          <Field label="Name" htmlFor="sg-name" required>
            <Input id="sg-name" name="name" placeholder="Jane Solar" />
          </Field>
          <Field label="Installer" htmlFor="sg-installer" optional>
            <Input id="sg-installer" name="installer" placeholder="Who installed your system?" />
          </Field>
          <Field label="Fleet size" htmlFor="sg-fleet" required>
            <Select id="sg-fleet" name="fleet" defaultValue="">
              <option value="" disabled>
                Select a range
              </option>
              <option value="Fewer than 10 sites">Fewer than 10 sites</option>
              <option value="10-50 sites">10 – 50 sites</option>
            </Select>
          </Field>
          <Field label="What would you like to know?" htmlFor="sg-message" optional>
            <Textarea id="sg-message" name="message" placeholder="Tell us about your system, or ask us anything." />
          </Field>
        </div>
        <p className={styles.footNote}>Click into a field to check the focus ring (3px --victron box-shadow).</p>
      </section>

      {/* ---------- ModeToggle ---------- */}
      <section className={styles.section}>
        <span className={styles.sectionLabel}>ModeToggle — .mode-toggle / .mode-toggle button.active</span>
        <ModeToggle
          aria-label="Report mode"
          options={[
            { value: 'detallado', label: 'Detallado · ≤31 days' },
            { value: 'overview', label: 'Resumen · 32 days–6 months' },
          ]}
        />
        <p className={styles.footNote}>
          useState, not the template&apos;s data-mode + querySelectorAll script — structurally can&apos;t reproduce
          the script-ordering bug at landing_template.html L887–896.
        </p>
      </section>
    </main>
  );
}
