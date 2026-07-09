# AISC Collaborative Assessment Dashboard — Colour Reference

All colour codes used across the customization, mapped to the functionality they
drive. Source of truth: `superset_config.py` (`THEME_OVERRIDES`,
`EXTRA_CATEGORICAL_COLOR_SCHEMES`) and `aisc/aisc.css` (injected UI).

## 1. Brand palette (core tokens)

| Token | Hex | Swatch meaning / usage |
|---|---|---|
| **Brand navy** | `#001075` | primary brand — top bar, primary buttons, KPI numbers, drawers |
| Navy dark | `#000a4d` | `primary.dark1` (hover/pressed) |
| Navy light | `#3a52b5` | `primary.light1` (tints) |
| **Brand red** | `#D7193B` | secondary/accent — accent line, request button, badges |
| Brand blue | `#1976d2` | data/accent blue (chart series, collab-dashboard primary) |
| Teal | `#2dd4bf` | secondary chart series |
| Amber | `#fbbf24` | chart series / warning tint |
| Violet | `#7c3aed` | chart series |
| Sky | `#0ea5e9` | chart series |
| Green | `#10b981` | chart series / "good" |

## 2. Chart categorical palette (`aisc` scheme, default)

Order used by charts (`EXTRA_CATEGORICAL_COLOR_SCHEMES` in `superset_config.py`):

| # | Hex | Name |
|---|---|---|
| 1 | `#001075` | navy |
| 2 | `#1976d2` | blue |
| 3 | `#D7193B` | red |
| 4 | `#2dd4bf` | teal |
| 5 | `#fbbf24` | amber |
| 6 | `#7c3aed` | violet |
| 7 | `#0ea5e9` | sky |
| 8 | `#10b981` | green |

## 3. Functionality → colour map

| Functionality / element | Colour | Hex |
|---|---|---|
| Top navigation bar (AppBar) | navy | `#001075` |
| Top bar accent line (under nav) | red | `#D7193B` |
| Active nav item underline | white | `#ffffff` |
| Primary buttons / KPI big-numbers | navy | `#001075` |
| Default chart primary series | navy → blue | `#001075` / `#1976d2` |
| **Comments** — launcher FAB (💬) | navy | `#001075` |
| **Comments** — drawer header | navy | `#001075` |
| **Comments** — author avatar (gradient) | navy → red | `#001075` → `#D7193B` |
| **Comments** — "Post" button | navy | `#001075` |
| **Comments** — input focus border | navy | `#001075` |
| **Comments** — per-chart 💬 button | navy outline | `#001075` |
| **Review request** — "Send request" button | red | `#D7193B` |
| **Tasks** — bell button (📋) | white bg / navy icon | `#ffffff` / `#001075` |
| **Tasks** — count badge | red | `#D7193B` |
| **Tasks** — drawer header | navy | `#001075` |
| **Tasks** — "Mark done" / resolve button | navy | `#001075` |
| Flash / toast confirmation | navy | `#001075` |
| Links | navy | `#001075` |
| Role badge — Editor (collab-dashboard) | red | `#D7193B` |
| Role badge — Viewer | grey | `#5b6478` |

## 4. Surfaces & text (light theme)

| Element | Hex |
|---|---|
| Page background | `#f4f6fb` |
| Card / paper | `#ffffff` |
| Text primary | `#1a2233` |
| Text secondary | `#5b6478` |
| Divider | `rgba(20,30,60,0.10)` |

## 5. Semantic colours (status)

| Meaning | Hex |
|---|---|
| Good / pass | `#10b981` (or `#34d399`) |
| Warning | `#fbbf24` |
| Bad / fail | `#D7193B` (or `#fb7185`) |

> The two non-negotiable brand colours are **navy `#001075`** and **red
> `#D7193B`** (the Luxembourg AI Factory identity). Everything else is a
> supporting accent. To re-skin, change `THEME_OVERRIDES` + the `aisc` scheme in
> `superset_config.py` and the hex values in `aisc/aisc.css`.
