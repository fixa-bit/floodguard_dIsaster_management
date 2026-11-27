// Readable small text at 100% browser zoom.
//
// Desktop screens draw the interface at 80% (src/styles.css, :root zoom), so a 10px label shows
// at 8px. This PostCSS step gives every small font-size a floor in on-screen pixels: the smallest
// labels show at 10.5px, 10-12px text at about 11-12px, and sizes from 17px up (headings, big
// numbers) are left alone, so the look stays compact. It writes
//     font-size: max(<original>, calc(<floor> / var(--ui-zoom, 1)))
// so the floor is in screen pixels whatever the zoom (1 on narrow screens, where no zoom applies).
// SVG text is skipped: chart labels are sized in the chart's own units and scale with it.
import type { Plugin, Rule } from "postcss";

/** The smallest on-screen size (px) for text written at `px` in the CSS. */
export function readableFloor(px: number): number {
  return 10.5 + Math.max(0, px - 8) * 0.35;
}

const PLAIN_PX = /^(\d*\.?\d+)px$/;
// An svg or text element in the selector (not a class such as .text-muted or .svg-icon).
const SVG_SELECTOR = /(^|[\s>+~,(])(svg|text)(?=$|[\s.:#[,>+~)])/;

export function readableTextSizes(): Plugin {
  return {
    postcssPlugin: "floodguard-readable-text-sizes",
    Declaration: {
      "font-size"(declaration) {
        const match = PLAIN_PX.exec(declaration.value.trim());
        if (!match) return;
        const selector = (declaration.parent as Rule | undefined)?.selector ?? "";
        if (SVG_SELECTOR.test(selector)) return;
        const px = Number(match[1]);
        const floor = readableFloor(px);
        // Already readable at 80% (from about 17px up): leave it.
        if (floor <= px * 0.8) return;
        declaration.value = `max(${px}px, calc(${+floor.toFixed(2)}px / var(--ui-zoom, 1)))`;
      },
    },
  };
}
