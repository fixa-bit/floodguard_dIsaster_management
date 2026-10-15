# Simulation: natural water surface and advected trails

Updated 2026-10-15 in **Simulation → Storm replay**. Replaces the initial animation after the user supplied a closer reference showing dense flow trails over natural-looking blue water. The old sparse dashes and brightly outlined nested blue bands are removed from this view. Existing controls, scenario levels, extents, population totals, line inspection, 2D comparison, Cinematic 3D, and monitoring workflows remain intact.

## Rendering strategy

The existing canvas now composites a translucent blue material with developed particle trails. Material color varies smoothly with distance to the reference river, bank distance, and low-amplitude procedural texture. The bank opacity fades inward, and both material and trails are strictly masked to the selected existing footprint, including polygon holes. The six footprint bands retain their data and filters, but their internal outlines and contrasting ring colors are no longer drawn.

The renderer builds a small view-local vector field using the nearest three projected river segments. Tangents are aligned before distance-weighted averaging; bilinear sampling smooths the field between grid points. A two-pass chamfer calculation estimates display-space distance to dry banks. These are **artistic display features**, not velocities, depths, or results from terrain routing.

Between 180 and 4,200 particles are seeded inside the **visible** water area, based on that area, rather than distributed sparsely along an entire district's river length. A midpoint advection step follows the field, with mild procedural transverse motion, variable artistic speed, finite lifetimes, and smooth brightness changes. Previous strokes persist in an offscreen trail buffer and decay exponentially. Fine strokes accumulate into curved, continuous texture instead of isolated moving dashes. Six low-opacity color groups allow batched drawing with occasional brighter foam-like traces.

Paused scenes are initialized with fifteen deterministic development steps. This creates a textured static view for initial snapshots and reduced-motion settings. When playback pauses, the exact developed frame remains; no field, particle, or trail reset occurs. Current toggles hide the trails while preserving the water material. Level zero and unsupported/missing water data clear the material and history.

## Geographic and scientific limits

The renderer still uses the existing hypothetical river-buffer extents. Appearance does not add accuracy to those extents or the six-hour example timeline. Currents follow reference coordinate order and an artistic field, with no validated downstream direction or speed. Shading is not a depth scale. The population and inspection methods are unchanged and continue to use the saved footprint geometry.

Real Jhang elevation and a historical FFC floodplain reference were obtained in parallel; see [the separate terrain feature](simulation-jhang-terrain-and-hydraulic-reference.md). Elevation adds optional real hillshade context, **not** a hydraulic solver or a calibrated stage-to-inundation relationship. The available approximately 262 m display grid cannot resolve building/levee-scale hydraulics like the supplied close-up. Current return periods, boundary hydrographs, channel bathymetry, friction, depth/velocity outputs, and historical validation are still missing for that capability.

## Performance and lifecycle

- One existing 2D overlay canvas remains above the existing MapLibre map; no new WebGL context, rendering engine, package, mobile tooling, or external graphics service is introduced.
- Three bounded offscreen buffers hold the mask, surface, and persistent trails. Output/trails cap device-pixel ratio at 1.5. The flow grid has at most about 220 cells along the longest viewport dimension, with a minimum cell size of four CSS pixels.
- Rendering caps at 30 updates/second. The river field and masks are prepared on geographic/level/size changes, not on every animation frame. Fine-particle paths are drawn in six batches.
- During camera movement the overlay is hidden and a uniform MapLibre footprint remains geographically aligned. At movement end the field is rebuilt for the new view. This avoids repeatedly computing nearest-river fields during each camera-animation frame.
- The existing pause, reduced-motion, document visibility, offscreen, and unmount controls govern the animation. Leaving the subtab cancels animation frames and map listeners and releases the offscreen buffers. A canvas initialization failure retains the native map footprint.

## Files and verification

- `frontend/src/components/ReplayWaterRenderer.ts`: material, masks, particle lifecycle/advection, persistent trails, compositing, and camera/resource handling.
- `frontend/src/components/replayWaterField.ts`: nearest-segment field, bank distance, and bilinear sampling.
- `frontend/src/components/useReplayCurrents.ts`: renderer lifecycle and existing controls.
- `frontend/src/components/useStormReplayMap.ts`: uniform native fallback without bright internal ring edges; optional imagery/terrain failures remain separate from required map failures.

Checks from `frontend`:

```powershell
node scripts/check-replay-water-field.mjs
node scripts/validate-natural-replay-water.mjs
node scripts/validate-storm-replay.mjs
npm run build
```

The independent field fixtures check straight/bent reference directions, dry ground, polygon holes, bank distance, and empty fields. The browser check compares actual pixel fingerprints before/after advection and across pause, tests the strict geographic mask against independent point-in-polygon checks, verifies clear/current toggles and real terrain coverage, and checks for errors and operational writes. The existing replay check covers all original playback, camera, scenario, line-inspection, draft-preservation, reduced-motion and cleanup behavior.

All four commands passed on 2026-10-15, along with the original Simulation 2D and Cinematic 3D browser checks. The pixel check found no leaks across 1,769 dry-location samples and no browser errors or operational writes. The production build passed with the existing large-chunk advisory. Live satellite verification also passed.

Screenshots in `frontend/screenshots/` include `simulation-natural-water.png` and `simulation-natural-water-satellite.png`. A 6.4-second browser capture with real satellite imagery, 3,229 visible-area particles, and the original playback controls is saved as `simulation-natural-water-preview.mp4`; `simulation-natural-water-motion-contact.jpg` contains sequential review frames. These are presentation review artifacts, not videos of a real flood. The recording used the actual renderer, rather than an offline generated animation.
