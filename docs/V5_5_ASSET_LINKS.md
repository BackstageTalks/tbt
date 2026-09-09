# BlinQ v5.5 — static asset links

This patch intentionally links repository-owned visual assets without embedding or modifying the image files themselves.

## Linked assets

- `/assets/blinq_favi.png` — favicon
- `/assets/blinq_background.png` — dashboard background layer
- `/assets/missing_foto_m.png` — ATP player-photo fallback
- `/assets/missing_foto_w.png` — WTA player-photo fallback
- `/assets/rookie_m.webp`, `/assets/rookie_w.webp`
- `/assets/pro_m.webp`, `/assets/pro_w.webp`
- `/assets/elite_m.webp`, `/assets/elite_w.webp`
- `/assets/legend_m.webp`, `/assets/legend_w.webp`
- `/assets/goat.webp`

The account avatar variant is a presentation preference (`m`, `w`, or initials), stored in normal user metadata. It does not change access permissions. GOAT uses the single `goat.webp` asset.

Player cards prefer a real cached `/assets/players/...` photo. If none is available, ATP/WTA uses the corresponding repository fallback image. If the fallback itself cannot load, the UI falls back to initials.

The filenames are the stable contract. The image contents can be replaced later without code changes.
