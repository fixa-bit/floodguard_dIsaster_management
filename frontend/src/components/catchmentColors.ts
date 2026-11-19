/**
 * COLOURS OF THE HIGHLIGHTED CATCHMENT (the neon reveal) — change them here, nowhere else.
 *
 * Each value is a hex colour "#rrggbb" (pick one with any colour picker). Save the file: the dev
 * app (npm run dev, http://localhost:3000) picks it up by itself; reload the page so the
 * catchment is drawn again with the new colours. How strong or see-through each colour shows is
 * part of the design and set where it is used, so changing a colour here never changes the look's
 * shape or animation. Production gets the change the next time you promote a version.
 */
export const catchmentColors = {
  // The border line that traces round the catchment.
  lineGlow: "#28c4ee",       // the glow around the border line and its soft outer halo
  lineCore: "#96eeff",       // the thin bright centre of the border line
  lineHot: "#e8feff",        // the white-hot tip while tracing, the running pulse and the glints

  // The inside of the catchment.
  wash: "#106e8c",           // the faint tint over the whole inside
  insideGlow: "#1e96b9",     // the glow rising in from the edge toward the middle
  innerLayers: "#52b7ce",    // the glossy layers of light just inside the edge
  edgeGlow: "#32bee6",       // the soft band along the inside of the edge
  edgeRim: "#96f0ff",        // the fine bright rim along the edge

  // The shine when the line closes.
  shineWash: "#28aac8",      // the brightening over the whole inside
  shineEdge: "#a0f2ff",      // the light along the edge
  highlight: "#dcffff",      // the glossy highlights: centre,
  highlightMid: "#5ae1fa",   //   middle,
  highlightOuter: "#28bee6", //   and fading edge

  // The spark at the tip of the tracing line: centre, middle and fading edge.
  spark: "#e1ffff",
  sparkMid: "#3ccdf0",
  sparkOuter: "#1eaad7",

  // The catchment's name written inside it.
  label: "#dcfbff",
  labelHalo: "#03303d",
};

/** A colour from the list above as [red, green, blue]. */
export const rgbOf = (hex: string) => [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));
/** A colour from the list above at the given strength (0 see-through to 1 solid). */
export const rgba = (hex: string, alpha: number) => `rgba(${rgbOf(hex).join(",")},${alpha})`;
