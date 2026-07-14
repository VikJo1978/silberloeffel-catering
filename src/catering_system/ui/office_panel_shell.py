"""Repo-owned presentation constants for the Office Panel UI v2 shell."""

from __future__ import annotations

from typing import Literal

OfficeSection = Literal[
    "home",
    "inquiries",
    "orders",
    "week",
    "callbacks",
    "proposal",
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
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .office-nav-link { transition: none; }
}
"""
