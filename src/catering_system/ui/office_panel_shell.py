"""Repo-owned presentation constants for the Office Panel UI v2 shell."""

from __future__ import annotations

from typing import Literal

OfficeSection = Literal[
    "home",
    "inquiries",
    "offers",
    "contacts",
    "email",
    "tasks",
    "calendar",
    "orders",
    "week",
    "callbacks",
    "proposal",
    "catalog",
]

OFFICE_PANEL_ICON_SPRITE = """<svg xmlns="http://www.w3.org/2000/svg"
style="display:none" aria-hidden="true">
<symbol id="office-i-grid" viewBox="0 0 24 24" fill="none"
stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
stroke-linejoin="round"><path d="M4 13h6V4H4v9Zm0 7h6v-4H4v4Zm10
0h6v-9h-6v9Zm0-16v4h6V4h-6Z"/></symbol>
<symbol id="office-i-doc" viewBox="0 0 24 24" fill="none"
stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
stroke-linejoin="round"><path d="M5 4h14v16H5zM8 8h8M8 12h8M8
16h5"/></symbol>
<symbol id="office-i-briefcase" viewBox="0 0 24 24" fill="none"
stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
stroke-linejoin="round"><path d="M4 7h16v13H4zM8 7V4h8v3M8
12h8"/></symbol>
<symbol id="office-i-calendar" viewBox="0 0 24 24" fill="none"
stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
stroke-linejoin="round"><path d="M4 6h16v14H4zM8 3v6M16 3v6M4
10h16"/></symbol>
<symbol id="office-i-phone" viewBox="0 0 24 24" fill="none"
stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
stroke-linejoin="round"><path d="M7 4H4v4c0 6.6 5.4 12 12 12h4v-3l-4-2-2
2c-3.4-1.1-5.9-3.6-7-7l2-2-2-4Z"/></symbol>
<symbol id="office-i-import" viewBox="0 0 24 24" fill="none"
stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
stroke-linejoin="round"><path d="M12 3v12M7 8l5-5 5 5M5 15v5h14v-5"/></symbol>
<symbol id="office-i-users" viewBox="0 0 24 24" fill="none"
stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
stroke-linejoin="round"><path d="M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M12
11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm8 8v-1a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0
7.75"/></symbol>
</svg>"""

OFFICE_PANEL_STYLE = """
:root {
  --accent: #5c6f63;
  --accent-deep: #4a5b50;
  --accent-soft: #e9eeea;
  --canvas: #f6f7f6;
  --surface: #ffffff;
  --ink: #1a1f1c;
  --line: #e2e5e2;
  --muted: #5f5e5a;
  --warm-accent: #c79262;
  --warning: #8a611e;
  --warning-soft: #fbf3e7;
  --danger: #9d3f38;
  --shadow: 0 10px 30px rgba(41, 54, 47, .06);
  --radius: 18px;
  --radius-small: 12px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  color: var(--ink);
  background: var(--canvas);
  font: 15px/1.5 Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); }
button, input, select, textarea { font: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }
button:focus-visible, a:focus-visible, input:focus-visible,
select:focus-visible, textarea:focus-visible, summary:focus-visible {
  outline: 3px solid var(--warm-accent);
  outline-offset: 3px;
}
button { cursor: pointer; }
svg { display: block; }
.office-app {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  min-height: 100vh;
}
.office-sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: 24px 18px 20px;
  border-right: 1px solid var(--line);
  background: var(--surface);
}
.office-brand {
  margin: 0 10px 28px;
}
.office-brand img {
  display: block;
  width: 174px;
  max-width: 100%;
  height: auto;
}
.office-nav-label {
  margin: 0 12px 8px;
  color: #6e756f;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .1em;
  text-transform: uppercase;
}
.office-nav {
  display: grid;
  gap: 4px;
}
.office-nav-link {
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  min-height: 44px;
  padding: 10px 12px;
  border-radius: 11px;
  color: #536057;
  text-decoration: none;
  transition: background .15s ease, color .15s ease;
}
.office-nav-link:hover {
  color: var(--accent-deep);
  background: var(--canvas);
}
.office-nav-link[aria-current="page"] {
  color: var(--accent-deep);
  background: var(--accent-soft);
  font-weight: 750;
}
.office-nav-link svg {
  flex: 0 0 auto;
  width: 19px;
  height: 19px;
}
.office-nav-link .badge {
  min-width: 24px;
  margin-left: auto;
  padding: 1px 7px;
  border-radius: 99px;
  color: #fff;
  background: var(--accent);
  text-align: center;
  font-size: 11px;
  font-weight: 800;
}
.office-user {
  margin-top: auto;
  padding: 14px 10px 2px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 11px;
}
.office-user strong {
  display: block;
  color: var(--ink);
  font-size: 12px;
}
.office-workspace { min-width: 0; }
.office-topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  min-height: 76px;
  padding: 0 clamp(24px, 4vw, 54px);
  border-bottom: 1px solid var(--line);
  background: rgba(246, 247, 246, .96);
}
.office-crumb {
  color: var(--muted);
  font-size: 13px;
}
.office-content {
  max-width: 1440px;
  min-width: 0;
  margin: 0 auto;
  padding: 34px clamp(24px, 4vw, 54px) 64px;
}
.office-content > h1 {
  margin: 0 0 24px;
  font-size: clamp(29px, 3.2vw, 40px);
  line-height: 1.15;
  font-weight: 760;
  letter-spacing: -.025em;
}
.office-content h2 {
  margin: 30px 0 14px;
  font-size: 19px;
  line-height: 1.25;
  letter-spacing: -.025em;
}
.office-content h3 {
  margin-top: 24px;
  letter-spacing: -.015em;
}
.office-content table {
  width: 100%;
  margin-bottom: 24px;
  border-collapse: separate;
  border-spacing: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.office-content th,
.office-content td {
  padding: 11px 14px;
  border: 0;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
.office-content tr:last-child th,
.office-content tr:last-child td { border-bottom: 0; }
.office-content .catalog-price { white-space: nowrap; }
.office-content th {
  color: #33413a;
  background: var(--accent-soft);
  font-size: 12px;
  font-weight: 750;
}
.office-content fieldset {
  margin: 0 0 18px;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.office-content label {
  display: inline-block;
  min-width: 12rem;
  color: #3c4640;
  font-weight: 650;
}
.office-content input,
.office-content select,
.office-content textarea {
  max-width: 100%;
  padding: 8px 10px;
  border: 1px solid #d3d6d1;
  border-radius: 9px;
  color: var(--ink);
  background: var(--surface);
}
.office-content textarea {
  width: min(100%, 42rem);
  vertical-align: top;
}
.office-content button {
  min-height: 38px;
  padding: 8px 14px;
  border: 1px solid var(--accent);
  border-radius: 9px;
  color: #fff;
  background: var(--accent);
  font-weight: 700;
}
.office-content button:hover {
  border-color: var(--accent-deep);
  background: var(--accent-deep);
}
.office-content form.inline { display: inline; }
.office-content .blocked { color: var(--danger); }
.office-content .ok { color: #3b6d11; }
.office-content .cancelled { color: var(--danger); font-weight: 800; }
.office-content .attention {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 22px;
}
.office-content .attention a,
.office-content .attention span {
  padding: 12px 15px;
  border: 1px solid var(--line);
  border-radius: var(--radius-small);
  color: inherit;
  background: var(--surface);
  box-shadow: 0 6px 18px rgba(41, 54, 47, .04);
  text-decoration: none;
}
.office-content .attention a:hover { border-color: var(--accent); }
.office-content .attention strong { color: var(--accent-deep); }
.office-content .searchbox { margin-bottom: 16px; }
.office-content .searchbox input { min-width: min(100%, 18rem); }
.office-content .subtitle {
  margin: -12px 0 20px;
  color: var(--muted);
  font-size: 13px;
}
.office-content .proposal-banner {
  margin-bottom: 20px;
  padding: 12px 15px;
  border: 1px solid #e5cfab;
  border-radius: var(--radius-small);
  color: #76501c;
  background: var(--warning-soft);
  font-weight: 700;
}
.office-content ul,
.office-content ol { padding-left: 22px; }
.office-content li { margin: 7px 0; }

/* UI2B Arbeitszentrale. Dashboard selectors are intentionally scoped so the
   remaining legacy presentation screens keep their UI2A appearance. */
.dashboard-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}
.dashboard-page-header h1 {
  margin: 3px 0 6px;
  font-size: clamp(31px, 3.2vw, 42px);
  line-height: 1.12;
  letter-spacing: -.035em;
}
.dashboard-page-header p,
.dashboard-card-head p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}
.dashboard-eyebrow {
  color: var(--accent);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.dashboard-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 9px 15px;
  border: 1px solid var(--accent);
  border-radius: 10px;
  color: #fff;
  background: var(--accent);
  font-size: 13px;
  font-weight: 750;
  line-height: 1.2;
  text-align: center;
  text-decoration: none;
}
.dashboard-button:hover { color: #fff; background: var(--accent-deep); }
.dashboard-button.secondary {
  color: var(--accent-deep);
  background: var(--surface);
}
.dashboard-button.secondary:hover { background: var(--accent-soft); }
.dashboard-attention {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.dashboard-attention-card {
  position: relative;
  display: grid;
  grid-template-columns: 42px 1fr;
  column-gap: 13px;
  padding: 19px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.dashboard-attention-card.unavailable { background: #fafafa; }
.dashboard-attention-icon {
  grid-row: 1 / span 3;
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  color: var(--accent-deep);
  background: var(--accent-soft);
}
.dashboard-attention-icon.warm { color: #805836; background: #f5ece4; }
.dashboard-attention-icon svg,
.dashboard-work-kind svg { width: 20px; height: 20px; }
.dashboard-attention-card > strong {
  font-size: 25px;
  line-height: 1.05;
}
.dashboard-attention-card > span:not(.dashboard-attention-icon) {
  color: var(--muted);
  font-size: 12px;
}
.dashboard-attention-card > a {
  margin-top: 9px;
  font-size: 12px;
  font-weight: 750;
  text-decoration: none;
}
.dashboard-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(290px, .8fr);
  gap: 22px;
  margin-top: 22px;
}
.dashboard-main,
.dashboard-side { display: grid; align-content: start; gap: 22px; }
.dashboard-card {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.dashboard-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 19px 21px 15px;
  border-bottom: 1px solid var(--line);
}
.office-content .dashboard-card-head h2 {
  margin: 0 0 3px;
  font-size: 17px;
}
.dashboard-text-link {
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 750;
  text-decoration: none;
}
.dashboard-work-row,
.dashboard-event-row {
  display: grid;
  align-items: center;
  gap: 14px;
  padding: 15px 21px;
  border-bottom: 1px solid var(--line);
}
.dashboard-work-row:last-child,
.dashboard-event-row:last-child { border-bottom: 0; }
.dashboard-work-row { grid-template-columns: 38px minmax(0, 1fr) auto; }
.dashboard-work-kind {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 11px;
  color: var(--accent-deep);
  background: var(--accent-soft);
}
.dashboard-work-kind.warm { color: #805836; background: #f5ece4; }
.dashboard-work-copy,
.dashboard-event-copy { min-width: 0; }
.dashboard-work-copy h3,
.dashboard-event-copy h3 {
  margin: 0 0 3px;
  font-size: 14px;
  line-height: 1.3;
}
.dashboard-work-copy h3 a,
.dashboard-event-copy h3 a { color: inherit; text-decoration: none; }
.dashboard-work-copy h3 a:hover,
.dashboard-event-copy h3 a:hover { color: var(--accent); }
.dashboard-work-copy p,
.dashboard-event-copy p {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--muted);
  font-size: 12px;
}
.dashboard-work-row form { margin: 0; }
.dashboard-work-row form button { white-space: nowrap; }
.dashboard-event-row {
  grid-template-columns: 46px minmax(0, 1fr) auto;
}
.dashboard-date-tile {
  display: grid;
  place-items: center;
  width: 44px;
  min-height: 48px;
  border-radius: 10px;
  color: var(--accent-deep);
  background: var(--accent-soft);
  line-height: 1.05;
}
.dashboard-date-tile strong { font-size: 17px; }
.dashboard-date-tile span,
.dashboard-guest-count {
  color: var(--muted);
  font-size: 11px;
}
.dashboard-week-days {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 4px;
  padding: 19px;
}
.dashboard-week-day {
  position: relative;
  display: grid;
  justify-items: center;
  min-height: 58px;
  padding: 7px 2px;
  border-radius: 10px;
  color: var(--muted);
  font-size: 10px;
}
.dashboard-week-day strong { color: var(--ink); font-size: 14px; }
.dashboard-week-day.today { color: var(--accent-deep); background: var(--accent-soft); }
.dashboard-week-day small {
  display: grid;
  place-items: center;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  border-radius: 99px;
  color: #fff;
  background: var(--accent);
  font-size: 9px;
  font-weight: 800;
}
.dashboard-notice,
.dashboard-service-state,
.dashboard-empty { margin: 16px 19px; }
.dashboard-notice {
  padding: 10px 12px;
  border-radius: 10px;
  color: var(--warning);
  background: var(--warning-soft);
  font-size: 12px;
}
.dashboard-empty,
.dashboard-service-state {
  padding: 18px;
  border-radius: 11px;
  color: var(--muted);
  background: var(--canvas);
  font-size: 12px;
}
.dashboard-service-state strong,
.dashboard-service-state span { display: block; }
.dashboard-service-state strong { margin-bottom: 3px; color: var(--ink); }
.dashboard-service-state.ok strong { color: var(--accent-deep); }
.dashboard-service-state.unavailable strong { color: var(--danger); }
.dashboard-callback-row {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr);
  gap: 12px;
  padding: 13px 19px;
  border-bottom: 1px solid var(--line);
}
.dashboard-callback-row:last-child { border-bottom: 0; }
.dashboard-callback-row > div,
.dashboard-callback-row > p { margin: 0; }
.dashboard-callback-row strong,
.dashboard-callback-row span { display: block; }
.dashboard-callback-row span { color: var(--muted); font-size: 11px; }

/* UI2C Arbeitszentrale — WorkCenterSnapshot cards (5A-2). */
.wc-page { display: grid; gap: 22px; }
.wc-page-header h1 {
  margin: 4px 0 8px;
  font-size: clamp(28px, 3vw, 38px);
  line-height: 1.12;
  letter-spacing: -.03em;
}
.wc-page-header p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}
.wc-eyebrow {
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.wc-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}
.wc-card {
  display: grid;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.wc-card-static { background: #fafafa; }
.wc-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.wc-card-head h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.2;
}
.wc-card-mark { font-size: 18px; line-height: 1; }
.wc-card-rule {
  margin: 0;
  border: 0;
  border-top: 1px solid var(--line);
}
.wc-card-summary {
  margin: 0;
  font-size: 14px;
}
.wc-card-summary strong { font-size: 22px; }
.wc-card p {
  margin: 0;
  color: var(--ink);
  font-size: 13px;
}
.wc-card-lines {
  margin: 0;
  padding: 0;
  list-style: none;
}
.wc-card-lines li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 0;
  font-size: 13px;
}
.wc-card-lines span { color: var(--muted); }
.wc-card-lines strong { font-size: 16px; }
.wc-card-action {
  display: inline-flex;
  align-self: start;
  min-height: 36px;
  padding: 8px 14px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  color: var(--ink);
  background: var(--surface);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}
.wc-card-action:hover {
  color: var(--accent-deep);
  border-color: var(--accent);
  background: var(--accent-soft);
}

.inquiry-back {
  display: inline-flex;
  margin-bottom: 18px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}
.inquiry-back:hover { color: var(--accent-deep); }
.inquiry-notice {
  margin-bottom: 16px;
  padding: 11px 14px;
  border: 1px solid #e5cfab;
  border-radius: var(--radius-small);
  color: #76501c;
  background: var(--warning-soft);
  font-size: 12px;
}
.inquiry-notice.blocked {
  border-color: #e1bbb7;
  color: var(--danger);
  background: #fbefee;
}
.inquiry-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(250px, .42fr);
  gap: 28px;
  align-items: center;
  padding: clamp(25px, 4vw, 42px);
  border-radius: 24px;
  color: #fff;
  background:
    radial-gradient(circle at 85% 10%, rgba(255, 255, 255, .12), transparent 34%),
    linear-gradient(135deg, var(--accent-deep), var(--accent));
  box-shadow: 0 18px 45px rgba(41, 54, 47, .13);
}
.inquiry-eyebrow {
  margin-bottom: 8px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .11em;
  text-transform: uppercase;
}
.office-content .inquiry-hero h1 {
  margin: 0;
  font-size: clamp(27px, 3.4vw, 42px);
  line-height: 1.1;
  letter-spacing: -.035em;
}
.inquiry-hero-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 9px 18px;
  margin-top: 18px;
  color: rgba(255, 255, 255, .86);
  font-size: 12px;
}
.inquiry-state-panel {
  padding: 19px 20px;
  border: 1px solid rgba(255, 255, 255, .18);
  border-radius: 15px;
  background: rgba(255, 255, 255, .1);
  backdrop-filter: blur(5px);
}
.inquiry-state-panel > span {
  display: block;
  margin-bottom: 6px;
  color: rgba(255, 255, 255, .72);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.inquiry-state-panel strong {
  display: block;
  font-size: 17px;
  line-height: 1.25;
}
.inquiry-state-panel p {
  margin: 8px 0 0;
  color: rgba(255, 255, 255, .79);
  font-size: 12px;
}
.inquiry-detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, .72fr);
  gap: 22px;
  margin-top: 22px;
}
.inquiry-detail-main,
.inquiry-detail-side {
  display: grid;
  align-content: start;
  gap: 22px;
}
.inquiry-card,
.inquiry-next-step,
.inquiry-edit {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.inquiry-content-card { padding: 21px; }
.office-content .inquiry-content-card h2,
.office-content .inquiry-next-step h2 {
  margin: 0 0 14px;
  font-size: 17px;
}
.inquiry-message {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  color: #3d443f;
  line-height: 1.75;
}
.inquiry-facts-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0;
  margin: 0;
}
.inquiry-facts-list.single { grid-template-columns: 1fr; }
.inquiry-facts-list > div {
  min-width: 0;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
.inquiry-facts-list > div:nth-last-child(-n + 2) { border-bottom: 0; }
.inquiry-facts-list.single > div:last-child { border-bottom: 0; }
.inquiry-facts-list dt {
  color: var(--muted);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.inquiry-facts-list dd {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
  color: var(--ink);
  font-weight: 650;
}
.inquiry-next-step {
  padding: 22px;
  border-color: var(--accent);
  color: #fff;
  background: var(--accent);
}
.office-content .inquiry-next-step h2 { color: #fff; }
.inquiry-next-step p {
  margin: 0 0 17px;
  color: rgba(255, 255, 255, .8);
  font-size: 12px;
}
.inquiry-next-step form { margin: 0; }
.office-content .inquiry-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 8px 14px;
  border: 1px solid #fff;
  border-radius: 9px;
  color: var(--accent-deep);
  background: #fff;
  font-size: 12px;
  font-weight: 800;
  text-decoration: none;
}
.office-content .inquiry-button:hover {
  border-color: var(--accent-soft);
  color: var(--accent-deep);
  background: var(--accent-soft);
}
.office-content .inquiry-button.secondary {
  border-color: var(--accent);
  color: var(--accent-deep);
  background: var(--surface);
}
.office-content .inquiry-button.secondary:hover { background: var(--accent-soft); }
.inquiry-blocker-lead {
  margin: 0 0 10px;
  color: var(--danger);
  font-size: 12px;
  font-weight: 800;
}
.inquiry-check-list,
.inquiry-order-list {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.inquiry-check-list li {
  display: grid;
  grid-template-columns: 23px minmax(0, 1fr);
  gap: 9px;
  align-items: start;
  margin: 0;
  color: #3d443f;
  font-size: 12px;
}
.inquiry-check-icon {
  display: grid;
  place-items: center;
  width: 21px;
  height: 21px;
  border-radius: 99px;
  color: var(--danger);
  background: #fbefee;
  font-size: 11px;
  font-weight: 900;
}
.inquiry-no-checks,
.inquiry-section-note {
  margin: 0 0 14px;
  color: var(--muted);
  font-size: 12px;
}
.inquiry-order-list li {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-bottom: 11px;
  border-bottom: 1px solid var(--line);
}
.inquiry-order-list li:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}
.inquiry-order-status {
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
}
.inquiry-order-list .inquiry-button { justify-self: start; }
.inquiry-edit {
  margin-top: 22px;
  overflow: hidden;
}
.inquiry-edit summary {
  padding: 17px 21px;
  color: var(--accent-deep);
  font-weight: 800;
  cursor: pointer;
}
.inquiry-edit[open] summary { border-bottom: 1px solid var(--line); }
.inquiry-edit-body { padding: 20px; }
.inquiry-edit-body fieldset {
  margin: 0;
  box-shadow: none;
}
.order-back {
  display: inline-flex;
  margin-bottom: 18px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}
.order-back:hover { color: var(--accent-deep); }
.order-cancelled-banner,
.order-notice {
  margin-bottom: 16px;
  padding: 11px 14px;
  border-radius: var(--radius-small);
  font-size: 12px;
}
.order-cancelled-banner {
  border: 1px solid #e1bbb7;
  color: var(--danger);
  background: #fbefee;
  font-weight: 900;
  letter-spacing: .08em;
}
.order-notice.blocked {
  border: 1px solid #e1bbb7;
  color: var(--danger);
  background: #fbefee;
}
.order-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(250px, .42fr);
  gap: 28px;
  align-items: center;
  padding: clamp(25px, 4vw, 42px);
  border-radius: 24px;
  color: #fff;
  background:
    radial-gradient(circle at 85% 10%, rgba(255, 255, 255, .12), transparent 34%),
    linear-gradient(135deg, #45574c, var(--accent));
  box-shadow: 0 18px 45px rgba(41, 54, 47, .13);
}
.order-eyebrow,
.order-section-kicker {
  margin-bottom: 8px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .11em;
  text-transform: uppercase;
}
.order-section-kicker { color: var(--warm-accent); }
.office-content .order-hero h1 {
  margin: 0;
  font-size: clamp(27px, 3.4vw, 42px);
  line-height: 1.1;
  letter-spacing: -.035em;
}
.order-hero-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 9px 18px;
  margin-top: 18px;
  color: rgba(255, 255, 255, .86);
  font-size: 12px;
}
.order-state-panel {
  padding: 19px 20px;
  border: 1px solid rgba(255, 255, 255, .18);
  border-radius: 15px;
  background: rgba(255, 255, 255, .1);
}
.order-state-panel > span {
  display: block;
  margin-bottom: 6px;
  color: rgba(255, 255, 255, .72);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.order-state-panel strong {
  display: block;
  font-size: 17px;
  line-height: 1.25;
}
.order-state-panel p {
  margin: 8px 0 0;
  color: rgba(255, 255, 255, .79);
  font-size: 12px;
}
.order-detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(300px, .75fr);
  gap: 22px;
  margin-top: 22px;
}
.order-detail-main,
.order-detail-side {
  display: grid;
  align-content: start;
  gap: 22px;
}
.order-card,
.order-next-step,
.order-history {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.order-content-card { padding: 21px; }
.office-content .order-content-card h2,
.office-content .order-next-step h2 {
  margin: 0 0 14px;
  font-size: 17px;
}
.order-facts-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0;
  margin: 0;
}
.order-facts-list > div {
  min-width: 0;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
.order-facts-list > div:nth-last-child(-n + 2) { border-bottom: 0; }
.order-facts-list dt,
.order-version-facts dt,
.order-payment-facts dt {
  color: var(--muted);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.order-facts-list dd,
.order-version-facts dd,
.order-payment-facts dd {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
  color: var(--ink);
  font-weight: 650;
}
.order-next-step {
  padding: 22px;
  border-color: var(--accent);
  color: #fff;
  background: var(--accent);
}
.order-next-step.complete {
  border-color: var(--accent-deep);
  background: var(--accent-deep);
}
.order-next-step.muted {
  border-color: #bbb6b0;
  color: var(--ink);
  background: #eeecea;
}
.office-content .order-next-step h2 { color: inherit; }
.order-next-step p {
  margin: 0 0 17px;
  color: rgba(255, 255, 255, .8);
  font-size: 12px;
}
.order-next-step.muted p { color: var(--muted); }
.order-next-step form { margin: 0; }
.order-next-actions,
.order-version-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.order-next-actions form,
.order-version-actions form { margin: 0; }
.office-content .order-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 8px 14px;
  border: 1px solid #fff;
  border-radius: 9px;
  color: var(--accent-deep);
  background: #fff;
  font-size: 12px;
  font-weight: 800;
  text-decoration: none;
}
.office-content .order-button:hover {
  border-color: var(--accent-soft);
  color: var(--accent-deep);
  background: var(--accent-soft);
}
.office-content .order-button.secondary {
  border-color: var(--accent);
  color: var(--accent-deep);
  background: var(--surface);
}
.office-content .order-next-step .order-button.secondary {
  border-color: rgba(255, 255, 255, .55);
  color: #fff;
  background: transparent;
}
.office-content .order-button.ghost {
  min-height: 34px;
  padding: 6px 10px;
  border-color: var(--line);
  color: var(--accent-deep);
  background: var(--surface);
  font-size: 11px;
}
.order-progress-list {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.order-progress-item {
  position: relative;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 11px;
  margin: 0;
  padding: 0 0 20px;
}
.order-progress-item:last-child { padding-bottom: 0; }
.order-progress-item:not(:last-child)::after {
  position: absolute;
  top: 27px;
  bottom: 3px;
  left: 14px;
  width: 1px;
  background: var(--line);
  content: "";
}
.order-progress-mark {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 29px;
  height: 29px;
  border: 1px solid var(--line);
  border-radius: 99px;
  color: var(--muted);
  background: var(--surface);
  font-size: 11px;
  font-weight: 900;
}
.order-progress-item.done .order-progress-mark {
  border-color: var(--accent);
  color: #fff;
  background: var(--accent);
}
.order-progress-item.current .order-progress-mark {
  border-color: var(--warm-accent);
  color: #805836;
  background: #f5ece4;
}
.order-progress-item strong,
.order-progress-item span { display: block; }
.order-progress-item strong { font-size: 13px; }
.order-progress-item div > span {
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
}
.order-blockers {
  margin-top: 18px;
  padding: 13px 15px;
  border-radius: 11px;
  color: var(--danger);
  background: #fbefee;
  font-size: 12px;
}
.order-blockers ul { margin: 7px 0 0; }
.order-ready-form { margin: 17px 0 0; }
.order-context-note,
.order-section-note {
  margin: 14px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.order-history {
  overflow: hidden;
}
.order-history > summary {
  padding: 17px 21px;
  color: var(--accent-deep);
  font-weight: 800;
  cursor: pointer;
}
.order-history[open] > summary { border-bottom: 1px solid var(--line); }
.order-history-body { padding: 0 21px; }
.order-version-row {
  padding: 20px 0;
  border-bottom: 1px solid var(--line);
}
.order-version-row:last-child { border-bottom: 0; }
.order-version-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.order-version-head strong,
.order-version-head span { display: block; }
.order-version-head > div > span {
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
}
.order-version-statuses {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 5px;
}
.order-version-status {
  padding: 3px 7px;
  border-radius: 99px;
  color: var(--accent-deep);
  background: var(--accent-soft);
  font-size: 9px;
  font-weight: 800;
}
.order-version-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 15px 0;
}
.order-payment-card {
  border-top: 3px solid var(--warm-accent);
}
.order-payment-facts {
  display: grid;
  gap: 9px;
  margin: 0;
}
.order-payment-facts > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.order-payment-facts dd { text-align: right; }
.order-payment-next {
  margin-top: 14px;
  padding: 12px;
  border-radius: 10px;
  background: #f5ece4;
}
.order-payment-next span,
.order-payment-next strong { display: block; }
.order-payment-next span {
  color: #805836;
  font-size: 10px;
  font-weight: 800;
  text-transform: uppercase;
}
.order-payment-next strong {
  margin-top: 3px;
  color: #5f432d;
  font-size: 12px;
}
.order-payment-edit,
.order-version-edit,
.order-danger {
  margin-top: 15px;
  border-top: 1px solid var(--line);
}
.order-payment-edit summary,
.order-version-edit summary,
.order-danger summary {
  padding: 13px 0 0;
  color: var(--accent-deep);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}
.order-payment-edit form,
.order-version-edit form { margin-top: 14px; }
.order-payment-edit fieldset,
.order-version-edit fieldset {
  margin: 0;
  padding: 0;
  border: 0;
  box-shadow: none;
}
.order-text-link {
  font-size: 12px;
  font-weight: 750;
  text-decoration: none;
}
.order-danger summary { color: var(--danger); }
.order-danger p {
  color: var(--danger);
  font-size: 11px;
}
.office-content .order-danger button {
  border-color: var(--danger);
  color: #fff;
  background: var(--danger);
}
@media (max-width: 820px) {
  .office-app { display: block; }
  .office-sidebar {
    position: static;
    width: auto;
    height: auto;
    padding: 12px 18px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .office-brand,
  .office-nav-label,
  .office-user { display: none; }
  .office-nav {
    display: flex;
    gap: 4px;
    overflow-x: auto;
    overscroll-behavior-inline: contain;
    scrollbar-width: thin;
  }
  .office-nav-link {
    flex: 0 0 auto;
    width: auto;
    white-space: nowrap;
  }
  .office-topbar {
    position: static;
    min-height: 58px;
    padding-inline: 18px;
  }
  .office-content { padding: 26px 18px 48px; }
  .office-content table {
    display: block;
    overflow-x: auto;
    white-space: nowrap;
  }
  .dashboard-attention { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .dashboard-layout { grid-template-columns: 1fr; }
  .dashboard-side { grid-template-columns: 1fr 1fr; }
  .inquiry-hero { grid-template-columns: 1fr; }
  .inquiry-detail-layout { grid-template-columns: 1fr; }
  .inquiry-detail-side { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .order-hero { grid-template-columns: 1fr; }
  .order-detail-layout { grid-template-columns: 1fr; }
  .order-detail-side { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .order-next-step { grid-column: 1 / -1; }
}
@media (max-width: 620px) {
  .office-content > h1 { font-size: 28px; }
  .office-content fieldset { padding: 15px; }
  .office-content label {
    display: block;
    min-width: 0;
    margin-bottom: 5px;
  }
  .office-content input,
  .office-content select,
  .office-content textarea { width: 100%; }
  .office-content form.inline { display: inline-block; margin: 3px 0; }
  .dashboard-page-header { display: grid; }
  .dashboard-page-header .dashboard-button { justify-self: start; }
  .dashboard-attention,
  .dashboard-side { grid-template-columns: 1fr; }
  .dashboard-work-row { grid-template-columns: 38px minmax(0, 1fr); }
  .dashboard-work-row > form,
  .dashboard-work-row > .dashboard-button { grid-column: 2; justify-self: start; }
  .dashboard-event-row { grid-template-columns: 46px minmax(0, 1fr); }
  .dashboard-guest-count { grid-column: 2; }
  .inquiry-hero { padding: 24px 20px; }
  .inquiry-state-panel { padding: 16px; }
  .inquiry-detail-side,
  .inquiry-facts-list { grid-template-columns: 1fr; }
  .inquiry-facts-list > div:nth-last-child(2) { border-bottom: 1px solid var(--line); }
  .inquiry-edit-body { padding: 14px; }
  .order-hero { padding: 24px 20px; }
  .order-state-panel { padding: 16px; }
  .order-detail-side,
  .order-facts-list { grid-template-columns: 1fr; }
  .order-facts-list > div:nth-last-child(2) { border-bottom: 1px solid var(--line); }
  .order-version-head { display: grid; }
  .order-version-statuses { justify-content: flex-start; }
  .order-version-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .office-nav-link { transition: none; }
}
"""
