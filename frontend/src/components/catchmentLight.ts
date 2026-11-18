import type { Feature, MultiPolygon, Polygon, Position } from "geojson";
import type { ExpressionSpecification } from "maplibre-gl";

/**
 * The selected catchment's neon reveal. When a catchment comes on screen, a glowing cyan line
 * traces its boundary and the inside lights up behind it, a deep navy glowing cyan along the
 * edge, like a glowing glass orb. Once the whole catchment is lit, a brighter pulse of light keeps running around the edge.
 *
 * The inside is drawn on a canvas that the map drapes over the terrain (a MapLibre canvas source).
 * The boundary is drawn by the map's own line layers, coloured each frame by `outlineGradient`.
 */

type Corners = [[number, number], [number, number], [number, number], [number, number]];
type Ring = { points: [number, number][]; lengths: number[]; total: number };

const maxSize = 1100;
const traceSeconds = 2.2;   // the boundary is traced in this long
const fillSeconds = 0.9;    // then the whole inside lights up
const orbitSeconds = 7;     // then a pulse of light runs once round the edge in this long

const blue = [48, 172, 255], paleBlue = [168, 234, 255], white = [236, 252, 255];

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

export class CatchmentLight {
  readonly canvas: HTMLCanvasElement;
  /** Where the canvas sits on the map (top-left, top-right, bottom-right, bottom-left). */
  coordinates: Corners = [[69, 31], [69.01, 31], [69.01, 30.99], [69, 30.99]];
  /** The zoom at which the whole catchment fills the view; the inside's light fades out well past it. */
  fitZoom = 0;
  private ctx: CanvasRenderingContext2D;
  private inner: HTMLCanvasElement | null = null;
  private innerPattern: CanvasPattern | null = null;
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
  get settledSeconds() { return (Number.isFinite(this.revealStart) ? this.revealStart : 0) + traceSeconds + fillSeconds + 1; }

  /** Plays the reveal again from the start (the catchment has just come on screen). */
  /** Keeps the catchment unlit (nothing traced yet) until `restartReveal`: the tour camera is still on its way. */
  holdReveal() {
    this.revealStart = Infinity;
    this.drawn = "";
  }

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
      this.inner = null;
      this.innerPattern = null;
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
      points.forEach((point, index) => {
        if (index === 0) shape.moveTo(...point); else shape.lineTo(...point);
        if (index > 0) lengths.push(lengths[index - 1] + Math.hypot(point[0] - points[index - 1][0], point[1] - points[index - 1][1]));
      });
      shape.closePath();
      return { points, lengths, total: lengths[lengths.length - 1] || 1 };
    });
    this.shape = shape;
    this.edge = Math.max(width, height) * 0.03;
    this.inner = this.paintInner(width, height);
    this.innerPattern = this.ctx.createPattern(this.inner, "no-repeat");
    this.holdReveal();
    return true;
  }

  /**
   * The lit inside, after a glowing glass orb: a deep, nearly opaque navy, darkest in the middle,
   * with faint glossy layers of cyan light inside the edge and a bright cyan glow along it.
   */
  private paintInner(width: number, height: number) {
    const inner = document.createElement("canvas");
    inner.width = width;
    inner.height = height;
    const ctx = inner.getContext("2d")!;
    const shape = this.shape!, edge = this.edge;
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const { points } of this.rings) for (const [x, y] of points) {
      left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
    }
    const middleX = (left + right) / 2, middleY = (top + bottom) / 2, radius = Math.max(right - left, bottom - top) / 2;
    ctx.save();
    ctx.clip(shape);
    ctx.fillStyle = "rgba(3,16,34,0.82)";
    ctx.fillRect(0, 0, width, height);
    const depth = ctx.createRadialGradient(middleX, middleY, 0, middleX, middleY, radius);
    depth.addColorStop(0, "rgba(0,3,10,0.55)");
    depth.addColorStop(0.6, "rgba(0,6,16,0.2)");
    depth.addColorStop(1, "rgba(0,8,20,0)");
    ctx.fillStyle = depth;
    ctx.fillRect(0, 0, width, height);
    // Glossy layers of light inside the edge: the outline again, smaller and slightly turned each time.
    ctx.lineJoin = "round";
    [[0.94, 0.03, 0.2], [0.87, -0.025, 0.13], [0.79, 0.04, 0.08]].forEach(([size, turn, alpha]) => {
      ctx.save();
      ctx.translate(middleX, middleY);
      ctx.rotate(turn);
      ctx.scale(size, size * 0.985);
      ctx.translate(-middleX, -middleY);
      ctx.filter = `blur(${edge * 0.35}px)`;
      ctx.strokeStyle = `rgba(70,190,255,${alpha})`;
      ctx.lineWidth = edge * 0.5 / size;
      ctx.stroke(shape);
      ctx.restore();
    });
    // Cyan light glowing in from the edge: a wide soft band, then a tight bright one.
    ctx.filter = `blur(${edge * 0.75}px)`;
    ctx.strokeStyle = "rgba(30,155,255,0.75)";
    ctx.lineWidth = edge * 1.7;
    ctx.stroke(shape);
    ctx.filter = `blur(${edge * 0.2}px)`;
    ctx.strokeStyle = "rgba(150,228,255,0.85)";
    ctx.lineWidth = edge * 0.45;
    ctx.stroke(shape);
    ctx.filter = "none";
    ctx.restore();
    return inner;
  }

  /** The boundary traced so far (`progress` 0 to 1 of each ring), and where each trace has reached. */
  private traced(progress: number) {
    const path = new Path2D(), tips: [number, number][] = [];
    for (const { points, lengths, total } of this.rings) {
      const reach = progress * total;
      path.moveTo(...points[0]);
      let tip = points[0];
      for (let index = 1; index < points.length; index += 1) {
        if (lengths[index] <= reach) { path.lineTo(...points[index]); tip = points[index]; continue; }
        const part = (reach - lengths[index - 1]) / (lengths[index] - lengths[index - 1] || 1);
        tip = [points[index - 1][0] + (points[index][0] - points[index - 1][0]) * part, points[index - 1][1] + (points[index][1] - points[index - 1][1]) * part];
        path.lineTo(...tip);
        break;
      }
      tips.push(tip);
    }
    return { path, tips };
  }

  /** Draws the inside at time `seconds` and strength `level` (0 to 1); returns false when the picture did not change. */
  draw(seconds: number, level: number) {
    const elapsed = seconds - this.revealStart;
    const trace = clamp(elapsed / traceSeconds), fill = clamp((elapsed - traceSeconds * 0.8) / fillSeconds);
    const settled = trace >= 1 && fill >= 1;
    const state = !this.shape || level <= 0.003 || !Number.isFinite(this.revealStart) ? "blank" : settled ? `lit:${level.toFixed(3)}` : "";
    if (state && state === this.drawn) return false;
    this.drawn = state;
    const ctx = this.ctx, { width, height } = this.canvas;
    ctx.clearRect(0, 0, width, height);
    if (state === "blank" || !this.inner) return true;
    const progress = easeInOut(trace), lit = 0.18 * progress + 0.82 * easeOut(fill);
    ctx.save();
    ctx.globalAlpha = level * lit;
    ctx.drawImage(this.inner, 0, 0);
    if (!settled && this.innerPattern) {
      // The inside lights up just behind the tracing line.
      const { path, tips } = this.traced(progress);
      ctx.clip(this.shape!);
      ctx.globalAlpha = level * (1 - lit) * 0.85;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.strokeStyle = this.innerPattern;
      ctx.lineWidth = this.edge * 3.2;
      ctx.stroke(path);
      // A bright spark where the trace has reached.
      if (trace > 0 && trace < 1) for (const [x, y] of tips) {
        const spark = ctx.createRadialGradient(x, y, 0, x, y, this.edge * 2.2);
        spark.addColorStop(0, "rgba(220,244,255,0.9)");
        spark.addColorStop(0.4, "rgba(60,160,255,0.45)");
        spark.addColorStop(1, "rgba(30,120,255,0)");
        ctx.globalAlpha = level;
        ctx.fillStyle = spark;
        ctx.fillRect(x - this.edge * 2.2, y - this.edge * 2.2, this.edge * 4.4, this.edge * 4.4);
      }
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
    const elapsed = seconds - this.revealStart, trace = clamp(elapsed / traceSeconds);
    const progress = easeInOut(trace), orbit = (((elapsed - traceSeconds) / orbitSeconds) % 1 + 1) % 1;
    const base = core ? paleBlue : blue, hot = core ? white : paleBlue;
    const samples = 72, stops: (number | string)[] = [];
    for (let index = 0; index <= samples; index += 1) {
      const along = index / samples;
      let alpha = 1, heat: number;
      if (trace < 1) {
        alpha = progress > 0 && along <= progress ? 1 : 0;
        heat = along <= progress ? clamp(1 - (progress - along) / 0.07) : 0;
      } else {
        const behind = (orbit - along + 1) % 1;
        heat = behind < 0.18 ? (1 - behind / 0.18) ** 2 : 0;
      }
      const [red, green, blueValue] = mix(base, hot, heat);
      stops.push(along, `rgba(${red},${green},${blueValue},${alpha})`);
    }
    return ["interpolate", ["linear"], ["line-progress"], ...stops] as unknown as ExpressionSpecification;
  }
}
