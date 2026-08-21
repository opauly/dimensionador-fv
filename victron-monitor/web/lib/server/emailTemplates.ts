import 'server-only';

// The activation/invite email's HTML, rendered directly in TypeScript.
//
// This is a deliberate, visually-matched port of
// `victron/templates/invite_email.html` (the Jinja2 template
// PLAN_PHASE14.md §2 Step 7 also asks for) — not a shared file, because
// Node cannot render Jinja2 and the two processes that would need to render
// it (this app, for real invites today; a future Phase 12 Python job, for
// scheduled report emails, which needs its own different template's content
// anyway) don't share a template engine. This is the SAME visual design
// (table layout, inline styles only, no <style> block, no `data:` URIs —
// Gmail strips/blocks both) kept in sync **by hand**, not by mechanism —
// exactly the kind of deliberate, documented duplication PLAN_PHASE14.md
// §1.3 already accepts for the two independent `assertOwnsSite()`
// implementations (Next.js and vrm_api): two copies that must independently
// agree beat one copy split across a language boundary that would just
// silently drift the same way. If this template's look ever changes, both
// files need the edit — there is no build step that would catch a missed one.
export type ActivationEmailInput = {
  heading: string;
  intro: string;
  ctaLabel: string;
  ctaUrl: string;
  footerNote: string;
};

// #0789d4 — the shipped `--victron` token (styles/tokens.css), not the
// older #0089B6 RAL 5012 placeholder PLAN_PHASE14.md §1.8 floated before
// the swatch page decided.
const VICTRON_BLUE = '#0789d4';

// Absolute URL, not a relative `/pauly_logo.png` — email clients fetch
// images over plain HTTP with no notion of "relative to this app," so the
// path has to be resolved against a real origin. Falls back to the
// production domain the same way `lib/server/signup.ts`'s own `SITE_URL()`
// does; in local dev (`SITE_URL=http://localhost:3000`) the image simply
// won't load in a real mail client, since nothing outside this machine can
// reach localhost — expected, not a bug, and `alt` below is what a
// recipient sees either way until they click "show images" (most clients'
// default), which is why it carries the real brand name, not just "logo."
function siteBase(): string {
  return (process.env.SITE_URL ?? 'https://monitor.paulyco.com').replace(/\/+$/, '');
}

function logoUrl(): string {
  return `${siteBase()}/pauly_logo.png`;
}

// The footer's own link back to the marketing site — a small, deliberate
// "carry the branding" touch: every one of this template's five callers
// (invite, resend, password reset, signup-verify, existing-account) links
// somewhere task-specific in the CTA button, but none of them otherwise
// mention where VRM Monitor actually lives.
function siteHomeUrl(): string {
  return siteBase();
}

export function renderActivationEmail({ heading, intro, ctaLabel, ctaUrl, footerNote }: ActivationEmailInput): string {
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${escapeHtml(heading)}</title>
  </head>
  <body style="margin:0; padding:0; background-color:#0b2231; font-family:Helvetica, Arial, sans-serif;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0;">${escapeHtml(intro)}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#0b2231;">
      <tr>
        <td align="center" style="padding:32px 16px;">
          <table role="presentation" width="480" cellpadding="0" cellspacing="0" border="0"
                 style="width:480px; max-width:100%; background-color:#12324a; border-radius:8px; overflow:hidden;">
            <tr>
              <td style="padding:28px 32px 0 32px;">
                <!-- 567x156 native (public/pauly_logo.png) — displayed at a fixed
                     136x37 (same ~3.65:1 ratio) so email clients that ignore CSS
                     width/height still lay it out correctly; real dimension
                     attributes matter more than the style ones here. -->
                <img src="${escapeAttr(logoUrl())}" alt="Pauly &amp; Co. — VRM Monitor" width="136" height="37"
                     style="display:block; width:136px; height:37px; border:0; outline:none;" />
              </td>
            </tr>
            <tr>
              <td style="padding:20px 32px 0 32px; border-top:1px solid #234a63;">&nbsp;</td>
            </tr>
            <tr>
              <td style="padding:8px 32px 0 32px;">
                <h1 style="margin:0 0 16px 0; font-family:Helvetica, Arial, sans-serif; font-size:20px; line-height:1.3; color:#e9f2f6;">
                  ${escapeHtml(heading)}
                </h1>
                <p style="margin:0 0 24px 0; font-family:Helvetica, Arial, sans-serif; font-size:14px; line-height:1.6; color:#afc7d4;">
                  ${escapeHtml(intro)}
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 8px 32px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td align="center" bgcolor="${VICTRON_BLUE}" style="border-radius:3px;">
                      <a href="${escapeAttr(ctaUrl)}"
                         style="display:inline-block; padding:12px 28px; font-family:Helvetica, Arial, sans-serif;
                                font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;
                                color:#ffffff; text-decoration:none; border-radius:3px;">
                        ${escapeHtml(ctaLabel)}
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 32px 8px 32px;">
                <p style="margin:0; font-family:Helvetica, Arial, sans-serif; font-size:12px; line-height:1.6; color:#6f93a6;">
                  ${escapeHtml(footerNote)}
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 32px 0 32px;">
                <p style="margin:0; font-family:Helvetica, Arial, sans-serif; font-size:11px; line-height:1.6; color:#6f93a6; word-break:break-all;">
                  If the button above doesn't work, copy and paste this link:<br />
                  <a href="${escapeAttr(ctaUrl)}" style="color:#4fc8ec;">${escapeHtml(ctaUrl)}</a>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 28px 32px; border-top:1px solid #234a63;">
                <p style="margin:16px 0 0 0; font-family:Helvetica, Arial, sans-serif; font-size:11px; color:#6f93a6;">
                  &copy; Pauly &amp; Co. Solar &middot;
                  <a href="${escapeAttr(siteHomeUrl())}" style="color:#6f93a6;">${escapeHtml(siteHomeUrl().replace(/^https?:\/\//, ''))}</a>
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>`;
}

// Every value interpolated above is either this app's own copy (not user
// input) or a URL this app itself built (`buildActivationUrl` in
// `invites.ts`) — but the one field that IS admin-typed indirectly, the
// customer's own name/email showing up nowhere in this template today,
// stays that way specifically so this escaping is defence in depth, not
// the only thing standing between an admin-entered name and broken markup
// if a future edit adds one.
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escapeAttr(value: string): string {
  return escapeHtml(value).replace(/'/g, '&#39;');
}
