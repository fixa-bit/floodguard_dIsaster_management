import { useEffect, useRef, useState } from "react";

/**
 * Measures a chart container so SVG charts can draw at their real pixel size.
 * A fixed viewBox stretched to 100% width scales text and height with the
 * container, so wide screens get oversized charts that no longer fit one view.
 * Height follows the width but is capped to a share of the window height.
 */
export function useChartBox({ fallbackWidth = 760, aspect = 0.42, minHeight = 200, maxHeight = 380, viewportShare = 0.45 } = {}) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: fallbackWidth, viewportHeight: typeof window === "undefined" ? 900 : window.innerHeight });
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => setSize({ width: Math.max(300, Math.round(element.getBoundingClientRect().width)), viewportHeight: window.innerHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    window.addEventListener("resize", update);
    return () => { observer.disconnect(); window.removeEventListener("resize", update); };
  }, []);
  const cap = Math.max(minHeight, Math.min(maxHeight, Math.round(size.viewportHeight * viewportShare)));
  const height = Math.max(minHeight, Math.min(cap, Math.round(size.width * aspect)));
  return { ref, width: size.width, height, narrow: size.width < 560 };
}
