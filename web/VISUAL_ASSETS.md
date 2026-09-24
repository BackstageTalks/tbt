# BlinQ visual assets: canonical usage

Updated 2026-09-24. This map prevents confusion between the two similarly named
backgrounds when changing login, loading, dashboard, or hero art.

| Asset | Canonical usage | Keep? |
| --- | --- | --- |
| `/assets/blinq_page_background.webp` | **Green tennis/globe graphic**, shown on the login dialog and behind the loading animation. Shared through `--blinq-login-loader-backdrop` in `blinq-app.css`. | Yes |
| `/assets/blinq_background.webp` | Darker main dashboard/page background. **Not** the login/loading artwork. | Yes |
| `/assets/blinq_logo.svg` | Header/brand identity, login watermark, and small non-interactive attribution per prediction. Not a global home/hero/footer overlay. | Yes |
| `/assets/blinq-loader.webp` | Approved animated loading illustration (GIF and static WebP fallbacks remain). | Yes |
| Hero banner images | Configurable in admin. A logo embedded directly in the image **cannot** be removed by hiding a CSS watermark; edit/replace that banner artwork. | Depends on active admin configuration |

The final, authoritative shared **login and loader backdrop** rule is marked
`BlinQ visual revision green-login-loader-20260924` near the end of
`blinq-app.css`. Keep their background image and dark overlay in one variable
rather than adding separate `!important` overrides. This revision does not
change the approved animation, auth form, login watermark, main dashboard
background, or per-prediction attribution.

**Repository cleanup:** older sections in `blinq-app.css` still contain
historical loading/background overrides. They are superseded by the canonical
rule but cannot safely be removed en masse without checking desktop/mobile
cascade behavior and admin overrides. Remove obsolete declarations in a
separate regression-tested refactor. Do not delete either WebP merely because
they look similarly named: both are currently needed.
