# Onboarding, Theme, and Rail Interaction

## Purpose

Help first-time TunnelView users learn the project workflow without forcing them
through destructive actions, while keeping the inspection viewer legible in both
dark and low-glare gray themes.

## Onboarding

- The client identifies a first-time user through browser `localStorage`.
  Different browsers or computers have independent onboarding state; a shared
  browser profile shares it.
- The tour is contextual rather than a single cross-page script:
  - Home introduces search, projects, existing tunnel cards, tunnel creation,
    and detailed help.
  - The creation wizard introduces its three import stages.
  - The viewer introduces mileage search, complete/fill image presentation,
    synchronized camera views, annotation, anchors, anomaly overview, the rail,
    information panel, and detailed help.
- The first home visit shows a welcome card. Users can start, defer, skip a
  section, or disable all automatic tours.
- Completion and per-section skips are persisted. The settings menu can replay
  the active section, reset tours, or disable them globally.
- The `?` control opens detailed page-specific help. It is the reference for
  controls and shortcuts that are intentionally not expanded in every tour step.
- A home tour step targets a real tunnel card when one exists. On an empty home
  page it targets the card area and shows a sample card in the tour, so it never
  incorrectly highlights the search field.

## Important Updates

- Important releases use a separate versioned announcement, not a replay of the
  full first-use tour.
- An announcement offers viewing a short related tour, skipping this version,
  or disabling future update announcements.
- `CURRENT_UPDATE` in `frontend/src/lib/onboarding.js` is intentionally `null`
  until a release has approved announcement copy and steps.

## Themes

- Dark remains the default visual language.
- The alternate theme uses low-glare mid-gray surfaces instead of white.
- The selected theme is saved as `tv_theme` in `localStorage` and applied on the
  document root.
- Base UI colors use CSS tokens. Image-overlay controls use a dedicated
  `--image-accent` so corner markers, rotation controls, and selected layout
  cells remain visible on photographs even when the light theme uses darker
  interface amber.

## Mileage Rail

- Rail canvas colors and legend colors come from the same theme tokens.
- Individual layers can be independently toggled and persisted:
  - Anchors
  - Missing photos
  - Aspect-ratio anomalies
  - Defect annotations
- Hidden layers are neither painted nor indexed as snap targets.
- Marker snapping is enabled by default and can be disabled. Moving over the
  rail shows the nearest visible marker within the snap radius; clicking jumps
  to that marker.
- If multiple visible markers lie within the same cluster radius, clicking opens
  a small candidate list with mileage, group number, and marker types. Selecting
  an item performs the jump.
- The current-position cursor is always visible and is not an optional layer.
