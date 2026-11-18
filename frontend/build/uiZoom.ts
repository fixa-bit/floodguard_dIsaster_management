// The whole interface is drawn at 80% on desktop screens (see the :root rule in
// src/styles.css), matching how the portal looks at 80% browser zoom.
//
// CSS `zoom` also shrinks lengths measured in viewport units, so `100vh` would only
// fill 80% of the screen. This PostCSS step divides every vh/vw value by the same
// factor (the --ui-zoom variable, 1 where no zoom applies), so full-height and
// full-width layouts still fill the window. Media queries are left alone.
import type { Plugin } from "postcss";

const VIEWPORT_UNIT = /(-?\d*\.?\d+)(d|s|l)?(vh|vw|vmin|vmax)\b/g;

export function uiZoomViewportUnits(): Plugin {
  return {
    postcssPlugin: "floodguard-ui-zoom-viewport-units",
    Declaration(declaration) {
      // PostCSS visits a declaration again after it changes, so skip ones already corrected.
      if (declaration.prop.startsWith("--") || declaration.value.includes("--ui-zoom")) return;
      const value = declaration.value.replace(VIEWPORT_UNIT, "calc($1$2$3 / var(--ui-zoom, 1))");
      if (value !== declaration.value) declaration.value = value;
    },
  };
}
