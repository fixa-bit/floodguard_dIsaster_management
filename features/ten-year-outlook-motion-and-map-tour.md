# Ten-year outlook: animated exploration

## Scope

The user asked for stronger visuals, moving maps, and moving graphs in the existing 10-Year Outlook sub-tab. This adds controlled animation to the [hypothetical preview](ten-year-hypothetical-maps-and-charts.md). It does not change the fixture, add real climate data, or introduce trained predictions.

## Timeline and visual strategy

- Add a sticky **Decade Explorer** with Play decade / Pause timeline, restart, a keyboard-accessible year scrubber, and an animated year-progress dial.
- Playback advances through the constructed 2026-2036 years every 1.5 seconds and stops at 2036. Starting at the end restarts from 2026; pausing preserves the selected year.
- The Planning year selector includes the 2026 baseline so the slider, selector, cards, map readouts, and chart always describe the same year.
- Draw the chart's active trace progressively to the selected year. Keep the remaining example curve as a faint dashed reference; move the selected-year playhead and glowing endpoint smoothly.
- Animate the index bars, summary-value entrances, and area-change bars. Use restrained teal/gold gradients and an ambient light accent in the timeline.
- Decorative effects never add observations or alter the illustrative scores, range bounds, or model explanation.

## Map movement

**Start map tour** frames each of the eight example districts in turn every 6.5 seconds. Both cameras stay synchronized. A tour transition lasts 1.8 seconds, with 24-degree pitch and -9-degree bearing; ordinary area selections use a 950 ms framing transition. Stop map tour cancels camera motion. Users can operate the tour and timeline together or independently.

Example location markers have subtle CSS pulse rings. District colors blend between the existing category colors over 750 ms. Manual area, hazard, scenario, or year changes stop automated playback/touring so users can inspect their choice. User-initiated map movement also stops playback; programmatic synchronization does not.

## Performance and cleanup

Geometry is loaded once through the existing compressed-asset cache. Playback updates feature state for eight example districts per map instead of repeatedly serializing and uploading the full district GeoJSON. Features have stable IDs. Mutable feature state stores the current hypothetical index and display color; immutable geometry does not carry an outdated year-specific score.

Color interpolation lasts only 750 ms after a relevant change and applies updates at most every 40 ms. Pulse/dial/value animations use CSS. No animation library, extra canvas, tile service, or mobile tooling is added.

`useOutlookMotion` listens to browser reduced-motion preferences and document visibility. Switching off **Motion on**, leaving the sub-tab, hiding the document, or enabling reduced motion disables visual motion and stops playback/tour timers. Returning to the view does not restart playback automatically. The existing map unmount behavior still releases both WebGL canvases, markers, ResizeObservers, and pending animation frames.

The timeline and tour are user-started. The overall Motion switch also disables decorative animations and transitions. Under reduced motion, manual selectors, slider, map navigation, chart, and method panel continue to work. Automated summary changes suppress live-region announcements while playing/touring.

## Files

- `frontend/src/components/TenYearRiskOutlook.tsx`: timeline state, playback/tour timers, manual takeover, controls, and animated summary bars.
- `frontend/src/components/useOutlookMotion.ts`: reduced-motion and visibility lifecycle.
- `frontend/src/components/TenYearComparisonMaps.tsx`: cinematic framing, synchronized cameras, pulsing markers, feature-state color transitions, and cleanup.
- `frontend/src/components/TenYearOutlookChart.tsx`: progressive trace, moving playhead, endpoint, and illustration shading.
- `frontend/src/ten-year-risk-outlook.css`: scoped motion styles, pause/reduced-motion overrides, and responsive layout.

## Verification

```powershell
cd frontend
node scripts/check-ten-year-preview.mjs
node scripts/validate-ten-year-preview.mjs
node scripts/validate-ten-year-motion.mjs
npm run build
```

The motion-specific browser check covers actual year advancement, pause stability, keyboard scrubbing, synchronized pitched cameras, automatic tour progression to the next district, combined timeline/tour operation, manual takeover, Motion off, reduced-motion media changes, a controlled document-visibility event, and inactive-tab timer/canvas cleanup. It also checks that no backend writes or browser runtime errors occur.

The existing preview checks cover selector consistency, map pin clicks, zoom synchronization, methodology, near-term regression behavior, and desktop/compact layout. Screenshot: `frontend/screenshots/ten-year-motion-tour.png`. Completion results are recorded after executing the checks.

Completion results: the fixture checks, existing preview browser suite, motion browser suite, and production build passed. The document-visibility handler was tested using a controlled hidden/visible event, confirming that playback stops and does not auto-resume. Browser tests reported no runtime errors or backend writes. The pitched map-tour screenshot was visually inspected.
