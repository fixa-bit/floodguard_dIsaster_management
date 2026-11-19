import type { Feature, MultiPolygon, Polygon, Position } from "geojson";
import type { ExpressionSpecification } from "maplibre-gl";
import { catchmentColors, rgba, rgbOf } from "./catchmentColors";

/**
 * The selected catchment's neon reveal, after the user's reference video. The catchment waits
 * faintly blue; then a glowing cyan line traces its boundary at a steady pace while the inside
 * fills in rich blue behind it, sweeping round as the line goes; when the line closes, the whole
 * catchment brightens and glossy cyan highlights shine along its edges. A soft pulse of light
 * then keeps running round the boundary.
 *
 * The inside is drawn on a canvas that the map drapes over the terrain (a MapLibre canvas source).
 * The boundary is drawn by the map's own line layers, coloured each frame by `outlineGradient`.
 */

type Corners = [[number, number], [number, number], [number, number], [number, number]];
type Ring = { points: [number, number][]; lengths: number[]; total: number; middle: [number, number] };

const maxSize = 1100;
const traceSeconds = 6;     // the boundary is traced in this long, at a steady pace
const shineSeconds = 1.6;   // then the catchment brightens and its edges shine
const orbitSeconds = 7;     // then a pulse of light runs once round the edge in this long
const waitingGlow = 0.32;   // how lit the inside is before the line starts
const maskScale = 0.25;     // the sweep's soft mask is worked out at this fraction of the canvas size

// The colours themselves live in catchmentColors.ts.
const blue = rgbOf(catchmentColors.lineGlow), paleBlue = rgbOf(catchmentColors.lineCore), white = rgbOf(catchmentColors.lineHot);

// Web Mercator, 0..1 across the world.
const mercatorX = (lng: number) => (lng + 180) / 360;
const mercatorY = (lat: number) => {
  const phi = (lat * Math.PI) / 180;
  return (1 - Math.log(Math.tan(phi) + 1 / Math.cos(phi)) / Math.PI) / 2;
};
const longitude = (x: number) => x * 360 - 180;
const latitude = (y: number) => (Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180) / Math.PI;
const clamp = (value: number) => Math.max(0, Math.min(1, value));
const easeInOut = (t: number) => 0.5 - 0.5 * Math.cos(Math.PI * clamp(t));
const easeOut = (t: number) => 1 - (1 - clamp(t)) ** 3;
const mix = (a: number[], b: number[], t: number) => a.map((value, index) => Math.round(value + (b[index] - value) * t));
/** How far round the boundary the line has reached: a steady pace, easing only at the very start and end. */
const traceProgress = (elapsed: number) => {
  const t = clamp(elapsed / traceSeconds);
  return 0.85 * t + 0.15 * easeInOut(t);
};

export class CatchmentLight {
  readonly canvas: HTMLCanvasElement;
  /** Where the canvas sits on the map (top-left, top-right, bottom-right, bottom-left). */
  coordinates: Corners = [[69, 31], [69.01, 31], [69.01, 30.99], [69, 30.99]];
  /** The zoom at which the whole catchment fills the view; the inside's light fades out well past it. */
  fitZoom = 0;
  private ctx: CanvasRenderingContext2D;
  private inner: HTMLCanvasElement | null = null;
  private shine: HTMLCanvasElement | null = null;
  private swept: HTMLCanvasElement | null = null;
  private mask: HTMLCanvasElement | null = null;
  private shape: Path2D | null = null;
  private rings: Ring[] = [];
  private edge = 1;
  private revealStart = 0;
  private drawn = "";
  private key = "";

  constructor() {
    this.canvas = document.createElement("canvas");
    this.canvas.width = this.canvas.height = 4;
    this.ctx = this.canvas.getContext("2d")!;
  }

  get active() { return this.shape !== null; }

  /** A time at which the reveal has long finished (the still picture, for viewers who prefer less motion). */
  get settledSeconds() { return (Number.isFinite(this.revealStart) ? this.revealStart : 0) + traceSeconds + shineSeconds + 1; }

  /** Keeps the catchment unlit (nothing traced yet) until `restartReveal`: the tour camera is still on its way. */
  holdReveal() {
    this.revealStart = Infinity;
    this.drawn = "";
  }

  /** Shows the catchment already fully drawn, with no reveal (monitoring mode off). */
  settle() {
    this.restartReveal(performance.now() / 1000 - 1000);
  }

  /** Plays the reveal again from the start (the catchment has just come on screen). */
  restartReveal(seconds = performance.now() / 1000) {
    this.revealStart = seconds;
    this.drawn = "";
  }

  /** Prepares the light for a catchment; returns false when nothing changed. */
  setCatchment(catchment: Feature<Polygon | MultiPolygon> | null, origin: [number, number] | null) {
    const key = catchment && origin ? `${origin.join(",")}:${JSON.stringify(catchment.geometry.coordinates).length}:${catchment.id ?? ""}` : "";
    if (key === this.key) return false;
    this.key = key;
    this.drawn = "";
    if (!catchment || !origin) {
      this.shape = null;
      this.inner = this.shine = this.swept = this.mask = null;
      this.rings = [];
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      return true;
    }
    const outlines: Position[][] = catchment.geometry.type === "Polygon" ? [catchment.geometry.coordinates[0]]
      : catchment.geometry.coordinates.map((polygon) => polygon[0]);
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const ring of outlines) for (const [lng, lat] of ring) {
      const x = mercatorX(lng), y = mercatorY(lat);
      minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const pad = Math.max(maxX - minX, maxY - minY) * 0.03;
    minX -= pad; minY -= pad; maxX += pad; maxY += pad;
    const scale = maxSize / Math.max(maxX - minX, maxY - minY);
    const width = Math.max(64, Math.round((maxX - minX) * scale)), height = Math.max(64, Math.round((maxY - minY) * scale));
    this.canvas.width = width;
    this.canvas.height = height;
    this.coordinates = [
      [longitude(minX), latitude(minY)], [longitude(maxX), latitude(minY)],
      [longitude(maxX), latitude(maxY)], [longitude(minX), latitude(maxY)],
    ];
    // Zoom at which the catchment spans about 900 screen pixels.
    this.fitZoom = Math.log2(900 / (512 * Math.max(maxX - minX, maxY - minY)));
    const toPixel = ([lng, lat]: Position): [number, number] => [(mercatorX(lng) - minX) * scale, (mercatorY(lat) - minY) * scale];
    const shape = new Path2D();
    this.rings = outlines.map((ring) => {
      const points = ring.map(toPixel);
      const lengths = [0];
      let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
      points.forEach((point, index) => {
        if (index === 0) shape.moveTo(...point); else shape.lineTo(...point);
        if (index > 0) lengths.push(lengths[index - 1] + Math.hypot(point[0] - points[index - 1][0], point[1] - points[index - 1][1]));
        left = Math.min(left, point[0]); right = Math.max(right, point[0]); top = Math.min(top, point[1]); bottom = Math.max(bottom, point[1]);
      });
      shape.closePath();
      return { points, lengths, total: lengths[lengths.length - 1] || 1, middle: [(left + right) / 2, (top + bottom) / 2] as [number, number] };
    });
    this.shape = shape;
    this.edge = Math.max(width, height) * 0.03;
    this.inner = this.paintInner(width, height);
    this.shine = this.paintShine(width, height);
    this.swept = document.createElement("canvas");
    this.swept.width = width;
    this.swept.height = height;
    this.mask = document.createElement("canvas");
    this.mask.width = Math.ceil(width * maskScale);
    this.mask.height = Math.ceil(height * maskScale);
    this.holdReveal();
    return true;
  }

  /** The middle of all the rings together (for the inside's depth). */
  private bounds() {
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const { points } of this.rings) for (const [x, y] of points) {
      left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
    }
    return { middleX: (left + right) / 2, middleY: (top + bottom) / 2, radius: Math.max(right - left, bottom - top) / 2 };
  }

  /**
   * The lit inside: a soft, subtle blue that glows strongest along the edge and grows more and more
   * see-through toward the middle, so the terrain shows clearly through the heart of the catchment.
   */
  private paintInner(width: number, height: number) {
    const inner = document.createElement("canvas");
    inner.width = width;
    inner.height = height;
    const ctx = inner.getContext("2d")!;
    const shape = this.shape!, edge = this.edge, { middleX, middleY } = this.bounds();
    ctx.save();
    ctx.clip(shape);
    // A faint wash everywhere; the colour itself comes from the glow rising in from the edge (below).
    ctx.fillStyle = rgba(catchmentColors.wash, 0.08);
    ctx.fillRect(0, 0, width, height);
    // Glow from the edge inward, in widening, fainter bands: dense at the edge, clear in the middle.
    ctx.lineJoin = "round";
    [[7, 2.6, 0.16], [4, 1.5, 0.22]].forEach(([band, blur, alpha]) => {
      ctx.filter = `blur(${edge * blur}px)`;
      ctx.strokeStyle = rgba(catchmentColors.insideGlow, alpha);
      ctx.lineWidth = edge * band;
      ctx.stroke(shape);
    });
    ctx.filter = "none";
    // Glossy layers of light inside the edge: the outline again, smaller and slightly turned each time.
    ctx.lineJoin = "round";
    [[0.94, 0.03, 0.22], [0.87, -0.025, 0.14], [0.79, 0.04, 0.09]].forEach(([size, turn, alpha]) => {
      ctx.save();
      ctx.translate(middleX, middleY);
      ctx.rotate(turn);
      ctx.scale(size, size * 0.985);
      ctx.translate(-middleX, -middleY);
      ctx.filter = `blur(${edge * 0.35}px)`;
      ctx.strokeStyle = rgba(catchmentColors.innerLayers, alpha * 0.8);
      ctx.lineWidth = edge * 0.5 / size;
      ctx.stroke(shape);
      ctx.restore();
    });
    // Blue light glowing in from the edge: a wide soft band, then a tight brighter one.
    ctx.filter = `blur(${edge * 0.8}px)`;
    ctx.strokeStyle = rgba(catchmentColors.edgeGlow, 0.5);
    ctx.lineWidth = edge * 1.8;
    ctx.stroke(shape);
    ctx.filter = `blur(${edge * 0.25}px)`;
    ctx.strokeStyle = rgba(catchmentColors.edgeRim, 0.55);
    ctx.lineWidth = edge * 0.35;
    ctx.stroke(shape);
    ctx.filter = "none";
    ctx.restore();
    return inner;
  }

  /** The shine once the line closes: a brighter wash, cyan light along the edge and a few glossy highlights. */
  private paintShine(width: number, height: number) {
    const shine = document.createElement("canvas");
    shine.width = width;
    shine.height = height;
    const ctx = shine.getContext("2d")!;
    const shape = this.shape!, edge = this.edge;
    ctx.save();
    ctx.clip(shape);
    ctx.fillStyle = rgba(catchmentColors.shineWash, 0.06);
    ctx.fillRect(0, 0, width, height);
    ctx.lineJoin = "round";
    ctx.filter = `blur(${edge * 0.4}px)`;
    ctx.strokeStyle = rgba(catchmentColors.shineEdge, 0.55);
    ctx.lineWidth = edge * 0.7;
    ctx.stroke(shape);
    ctx.filter = "none";
    // Glossy highlights where light pools inside the edge (the same places every time for a catchment).
    let seed = 11;
    const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    for (const { points, lengths, total, middle } of this.rings) {
      const count = 5;
      for (let spot = 0; spot < count; spot += 1) {
        const reach = ((spot + random() * 0.6) / count) * total;
        const index = Math.max(1, lengths.findIndex((length) => length >= reach));
        const [x, y] = points[index];
        // A little inside the edge, toward the ring's middle.
        const inward = 0.06 + random() * 0.05;
        const cx = x + (middle[0] - x) * inward, cy = y + (middle[1] - y) * inward;
        const size = edge * (1.8 + random() * 1.8);
        const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, size);
        glow.addColorStop(0, rgba(catchmentColors.highlight, 0.75));
        glow.addColorStop(0.35, rgba(catchmentColors.highlightMid, 0.35));
        glow.addColorStop(1, rgba(catchmentColors.highlightOuter, 0));
        ctx.fillStyle = glow;
        ctx.fillRect(cx - size, cy - size, size * 2, size * 2);
      }
    }
    ctx.restore();
    return shine;
  }

  /**
   * The boundary traced so far (`progress` 0 to 1 of each ring), where each trace has reached, and
   * the area the line has swept round (from each ring's middle to the traced boundary).
   */
  private traced(progress: number) {
    const path = new Path2D(), sweep = new Path2D(), tips: [number, number][] = [];
    for (const { points, lengths, total, middle } of this.rings) {
      const reach = progress * total;
      path.moveTo(...points[0]);
      sweep.moveTo(...middle);
      sweep.lineTo(...points[0]);
      let tip = points[0];
      for (let index = 1; index < points.length; index += 1) {
        if (lengths[index] <= reach) { tip = points[index]; path.lineTo(...tip); sweep.lineTo(...tip); continue; }
        const part = (reach - lengths[index - 1]) / (lengths[index] - lengths[index - 1] || 1);
        tip = [points[index - 1][0] + (points[index][0] - points[index - 1][0]) * part, points[index - 1][1] + (points[index][1] - points[index - 1][1]) * part];
        path.lineTo(...tip);
        sweep.lineTo(...tip);
        break;
      }
      sweep.closePath();
      tips.push(tip);
    }
    return { path, sweep, tips };
  }

  /** The inside as far as the line has swept, with a soft edge to the sweep. */
  private paintSwept(sweep: Path2D, path: Path2D) {
    const mask = this.mask!, swept = this.swept!, inner = this.inner!;
    const maskCtx = mask.getContext("2d")!;
    maskCtx.setTransform(1, 0, 0, 1, 0, 0);
    maskCtx.clearRect(0, 0, mask.width, mask.height);
    maskCtx.setTransform(maskScale, 0, 0, maskScale, 0, 0);
    maskCtx.filter = `blur(${this.edge * 0.5 * maskScale}px)`;
    maskCtx.fillStyle = "#fff";
    maskCtx.fill(sweep);
    // Light spills a little ahead along the edge just traced.
    maskCtx.strokeStyle = "#fff";
    maskCtx.lineWidth = this.edge * 2.4;
    maskCtx.lineJoin = "round";
    maskCtx.lineCap = "round";
    maskCtx.stroke(path);
    maskCtx.filter = "none";
    const ctx = swept.getContext("2d")!;
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, swept.width, swept.height);
    ctx.drawImage(inner, 0, 0);
    ctx.globalCompositeOperation = "destination-in";
    ctx.drawImage(mask, 0, 0, swept.width, swept.height);
    ctx.globalCompositeOperation = "source-over";
    return swept;
  }

  /** Draws the inside at time `seconds` and strength `level` (0 to 1); returns false when the picture did not change. */
  draw(seconds: number, level: number) {
    const elapsed = seconds - this.revealStart;
    const progress = traceProgress(elapsed);
    const whole = easeOut((elapsed - traceSeconds * 0.96) / 0.7);
    const shining = easeOut((elapsed - traceSeconds) / shineSeconds);
    const settled = elapsed >= traceSeconds + shineSeconds;
    // Before the line starts (the tour camera still on its way) the catchment is already faintly blue.
    const waiting = !Number.isFinite(this.revealStart) || elapsed <= 0;
    const state = !this.shape || level <= 0.003 ? "blank" : waiting ? `waiting:${level.toFixed(3)}` : settled ? `lit:${level.toFixed(3)}` : "";
    if (state && state === this.drawn) return false;
    this.drawn = state;
    const ctx = this.ctx, { width, height } = this.canvas;
    ctx.clearRect(0, 0, width, height);
    if (state === "blank" || !this.inner) return true;
    ctx.save();
    if (whole < 1) {
      ctx.globalAlpha = level * waitingGlow;
      ctx.drawImage(this.inner, 0, 0);
    }
    if (!waiting && whole < 1 && progress > 0) {
      // The inside fills in behind the line as it goes round.
      const { path, sweep, tips } = this.traced(progress);
      ctx.globalAlpha = level;
      ctx.drawImage(this.paintSwept(sweep, path), 0, 0);
      // A bright spark where the line has reached.
      if (progress < 1) for (const [x, y] of tips) {
        const spark = ctx.createRadialGradient(x, y, 0, x, y, this.edge * 1.3);
        spark.addColorStop(0, rgba(catchmentColors.spark, 0.9));
        spark.addColorStop(0.4, rgba(catchmentColors.sparkMid, 0.45));
        spark.addColorStop(1, rgba(catchmentColors.sparkOuter, 0));
        ctx.fillStyle = spark;
        ctx.fillRect(x - this.edge * 1.3, y - this.edge * 1.3, this.edge * 2.6, this.edge * 2.6);
      }
    }
    if (whole > 0) {
      ctx.globalAlpha = level * whole;
      ctx.drawImage(this.inner, 0, 0);
    }
    if (shining > 0 && this.shine) {
      ctx.globalAlpha = level * shining * 0.9;
      ctx.drawImage(this.shine, 0, 0);
    }
    ctx.restore();
    return true;
  }

  /**
   * The boundary line's colour along its length at time `seconds` (for the map's `line-gradient`):
   * drawn only as far as the trace has reached, white-hot at the tracing tip, and once traced, a
   * pulse of light running round it. `core` is the bright centre line; otherwise the glow around it.
   */
  outlineGradient(seconds: number, core: boolean): ExpressionSpecification {
    const elapsed = seconds - this.revealStart, traced = elapsed >= traceSeconds;
    const progress = traceProgress(elapsed), orbit = (((elapsed - traceSeconds) / orbitSeconds) % 1 + 1) % 1;
    const base = core ? paleBlue : blue, hot = core ? white : paleBlue;
    const samples = 120, stops: (number | string)[] = [];
    for (let index = 0; index <= samples; index += 1) {
      const along = index / samples;
      let alpha = 1, heat: number;
      if (!traced) {
        alpha = elapsed > 0 && progress > 0 && along <= progress ? 1 : 0;
        heat = along <= progress ? clamp(1 - (progress - along) / 0.06) : 0;
      } else {
        const behind = (orbit - along + 1) % 1;
        heat = behind < 0.18 ? (1 - behind / 0.18) ** 2 : 0;
      }
      // Glossy: the line's brightness ripples along it, with small bright glints drifting slowly round,
      // so it reads as polished light rather than a solid painted stroke.
      const sheen = 0.5 + 0.5 * Math.sin(along * Math.PI * 2 * 7 + seconds * 0.7);
      const glint = sheen ** 8;
      alpha *= core ? 0.45 + 0.4 * sheen : 0.35 + 0.5 * sheen;
      const [red, green, blueValue] = mix(base, hot, Math.max(heat, glint * 0.85));
      stops.push(along, `rgba(${red},${green},${blueValue},${+alpha.toFixed(3)})`);
    }
    return ["interpolate", ["linear"], ["line-progress"], ...stops] as unknown as ExpressionSpecification;
  }
}
