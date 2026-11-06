# Algua brand kit

Current identity: the November 6, 2026 wave kit in [Google Drive](https://drive.google.com/drive/folders/1KkAKKaYL-iZTGqg_43f1qQ2UrSWcyfPp).
The supplied A, wave, and Algua wordmark replace the previous Sea identity.

## Assets

- `sources/`: the six original Drive PNGs, preserved unchanged. `sources.json` records their Drive IDs and SHA-256 hashes.
- `logo-horizontal.svg` and `logo-horizontal-reversed.svg`: light and dark presentation wrappers around the supplied artwork, not traced vectors.
- `logo-mark.svg` and `logo-mark-reversed.svg`: standalone marks.
- `exports/`: dashboard-sized wordmarks, app/avatar icons, and light/dark repository banners.
- `tokens.css` and `fonts/`: shared palette and self-hosted Lato, with its SIL Open Font License.
- `archive/sea/`: historical generator and mockups. Do not use them for current branding.

The original white wordmark export has damaged transparency. Current inverse derivatives use the intact black artwork with an SVG color matrix: neutral ink becomes white, the wave remains blue, and source geometry and alpha are preserved. Source originals remain available for comparison.

## Palette and type

| Role | Light | Dark |
|---|---|---|
| Black | `#0B0B0D` | `#0B0B0D` |
| White | `#FFFFFF` | `#FFFFFF` |
| Ocean Blue | `#5CA9F8` | `#00A8FF` |
| Ice Blue | `#A9D7FF` | `#7DD7FF` |
| Mist | `#EAF4FB` | `#E6F5FF` |

Use Lato for product typography. Retain a monospace face for code and aligned data where useful. The wordmark is supplied artwork; do not retype it.

Keep surfaces quiet, with blue reserved for selection, links, and meaningful data. Small interactive text on light surfaces uses a darker Ocean derivative, `#006BA6`, for contrast. Status colors retain their operational meaning. Do not add decorative wave backgrounds to data-heavy pages.

Preserve artwork proportions and clear space. The dashboard lockup is 120 px wide and adapts to system appearance. Use the standalone mark for app icons and avatars. Keep maskable-icon artwork within its safe area.

## Regenerate

After installing the existing frontend dependencies and Chrome:

```sh
node docs/brand/build_assets.mjs
```

This renders the supplied artwork into consistent dashboard, app-icon, README, and avatar exports. It does not redraw the logo or require an external image service. The dashboard imports generated wordmarks as fingerprinted assets and serves the font locally; it makes no Google Fonts requests at runtime.

The root README selects the light/dark banner using GitHub's appearance preference. `exports/social-avatar.png` is available for repository-related profiles; it is not an instruction to change the owner's personal GitHub avatar.
