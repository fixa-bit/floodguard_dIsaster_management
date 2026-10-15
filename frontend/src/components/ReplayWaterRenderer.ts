import type { Map as MapLibreMap } from "maplibre-gl";
import type { Polygon } from "geojson";
import { buildWaterField, sampleWaterField, type ScreenPoint, type WaterField } from "./replayWaterField";
import type { CurrentRoute } from "./stormReplayData";

type Particle = { x: number; y: number; age: number; life: number; speed: number; brightness: number };
const palette = ["rgba(100,182,228,.17)", "rgba(133,202,239,.25)", "rgba(166,219,245,.34)", "rgba(194,234,251,.44)", "rgba(223,246,255,.60)", "rgba(240,251,255,.80)"];

/** Artistic water material and persistent advected trails; never a hydraulic solver. */
export class ReplayWaterRenderer {
  private output: CanvasRenderingContext2D;
  private mask = document.createElement("canvas");
  private surface = document.createElement("canvas");
  private trails = document.createElement("canvas");
  private maskContext: CanvasRenderingContext2D;
  private surfaceContext: CanvasRenderingContext2D;
  private trailContext: CanvasRenderingContext2D;
  private field: WaterField | null = null;
  private particles: Particle[] = [];
  private routes: CurrentRoute[] = [];
  private polygons: Polygon[] = [];
  private width = 0;
  private height = 0;
  private ratio = 1;
  private seed = 93471;
  private currents = true;
  private running = false;
  private moving = false;
  private disposed = false;
  private frame = 0;
  private previous = 0;
  private lastDraw = 0;
  private phase = 0;
  private frames = 0;
  private level = 0;

  constructor(private canvas: HTMLCanvasElement, private map: MapLibreMap) {
    const output = canvas.getContext("2d");
    const mask = this.mask.getContext("2d", { willReadFrequently: true });
    const surface = this.surface.getContext("2d");
    const trails = this.trails.getContext("2d");
    if (!output || !mask || !surface || !trails) throw new Error("Canvas water material unavailable");
    this.output = output; this.maskContext = mask; this.surfaceContext = surface; this.trailContext = trails;
    canvas.dataset.renderer = "advected-water-v2";
    this.map.on("movestart", this.onMoveStart);
    this.map.on("moveend", this.onMoveEnd);
    this.map.on("resize", this.onMoveEnd);
  }

  private random() { this.seed = (1664525 * this.seed + 1013904223) >>> 0; return this.seed / 4294967296; }
  private mapOpacity(value: number) { try { if (this.map.getLayer("replay-water-fill")) this.map.setPaintProperty("replay-water-fill", "fill-opacity", value); } catch { /* Map can already be removed during parent cleanup. */ } }
  private onMoveStart = () => { this.moving = true; this.canvas.style.opacity = "0"; this.mapOpacity(.48); };
  private onMoveEnd = () => { if (!this.disposed) { this.moving = false; this.prepare(); this.canvas.style.opacity = "1"; } };

  setScene(routes: CurrentRoute[], polygons: Polygon[], level: number) {
    this.routes = routes; this.polygons = polygons; this.level = level; this.seed = 93471 + level * 127; this.prepare();
  }
  setCurrents(enabled: boolean) { this.currents = enabled; this.composite(); }
  setRunning(running: boolean) {
    if (this.running === running) return;
    this.running = running; cancelAnimationFrame(this.frame); this.frame = 0; this.previous = 0; this.lastDraw = 0;
    if (running) this.frame = requestAnimationFrame(this.tick);
  }
  private tick = (now: number) => {
    if (this.disposed || !this.running) return;
    if (!this.previous) this.previous = now;
    if (!this.moving && now - this.lastDraw >= 1000/30) {
      const started = performance.now(), delta = Math.min(.08, (now-this.previous)/1000);
      this.previous = now; this.lastDraw = now; this.phase += delta;
      if (this.currents && this.field?.seeds.length) this.advance(delta);
      this.composite();
      this.canvas.dataset.renderMs = (performance.now()-started).toFixed(2); this.canvas.dataset.frames = String(++this.frames);
    }
    this.frame = requestAnimationFrame(this.tick);
  };
  private spawn(particle?: Particle): Particle {
    const field = this.field!, index = field.seeds[Math.floor(this.random()*field.seeds.length)];
    const result = particle ?? { x: 0, y: 0, age: 0, life: 0, speed: 0, brightness: 0 };
    result.x = (index%field.columns + .15 + this.random()*.7)*field.cell;
    result.y = (Math.floor(index/field.columns) + .15 + this.random()*.7)*field.cell;
    result.age = 0; result.life = .8 + this.random()*2.5; result.speed = 25 + this.random()*34; result.brightness = this.random();
    return result;
  }
  private prepare() {
    if (this.disposed) return;
    const element = this.map.getContainer(); this.width = element.clientWidth; this.height = element.clientHeight;
    if (!this.width || !this.height) return;
    this.ratio = Math.min(1.5, window.devicePixelRatio || 1);
    this.canvas.width = Math.round(this.width*this.ratio); this.canvas.height = Math.round(this.height*this.ratio);
    this.output.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
    this.mask.width = this.width; this.mask.height = this.height;
    this.trails.width = this.canvas.width; this.trails.height = this.canvas.height;
    this.trailContext.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
    this.field = null; this.particles = []; this.canvas.dataset.streaks = "0";
    if (!this.polygons.length || !this.routes.length) { this.mapOpacity(.48); this.composite(); return; }
    const mask = new Path2D();
    for (const polygon of this.polygons) for (const ring of polygon.coordinates) {
      ring.forEach((coordinate, index) => { const p = this.map.project([coordinate[0], coordinate[1]]); if (!index) mask.moveTo(p.x, p.y); else mask.lineTo(p.x, p.y); });
      mask.closePath();
    }
    this.maskContext.fillStyle = "white"; this.maskContext.fill(mask, "evenodd");
    const paths: ScreenPoint[][] = this.routes.map((route) => {
      const points = route.points.map((point) => this.map.project(point));
      const kept: ScreenPoint[] = [];
      points.forEach((point, index) => { const previous = kept.at(-1); if (!previous || index === points.length-1 || Math.hypot(point.x-previous.x, point.y-previous.y) > 1) kept.push(point); });
      return kept;
    });
    const alpha = this.maskContext.getImageData(0, 0, this.width, this.height).data;
    const cell = Math.max(4, Math.ceil(Math.max(this.width, this.height)/220));
    this.field = buildWaterField(this.width, this.height, alpha, paths, cell);
    this.prepareSurface();
    const count = this.field.seeds.length ? Math.min(4200, Math.max(180, Math.round(this.field.seeds.length*cell*cell*.013))) : 0;
    this.particles = Array.from({ length: count }, () => { const particle = this.spawn(); particle.age = this.random()*particle.life; return particle; });
    // Predeveloped texture also gives paused/reduced-motion snapshots a water surface.
    for (let i = 0; i < 15; i++) this.advance(1/30);
    this.mapOpacity(.08);
    this.canvas.dataset.waterCells = String(this.field.seeds.length); this.canvas.dataset.level = String(this.level);
    this.composite();
  }
  private prepareSurface() {
    const field = this.field!, texture = document.createElement("canvas");
    texture.width = field.columns; texture.height = field.rows;
    const context = texture.getContext("2d")!, image = context.createImageData(field.columns, field.rows);
    for (let row = 0; row < field.rows; row++) for (let col = 0; col < field.columns; col++) {
      const index = row*field.columns+col, offset = index*4;
      if (!field.wet[index]) continue;
      const x = col*field.cell, y = row*field.cell;
      const noise = Math.sin(x*.017 + Math.sin(y*.029)*1.7)*.45 + Math.sin(y*.051 + x*.023)*.2 + Math.sin(x*.17-y*.13)*.12;
      const core = Math.exp(-field.riverDistance[index]/55), bank = Math.min(1, field.shore[index]/12);
      image.data[offset] = 22 + (1-core)*20 + noise*8;
      image.data[offset+1] = 83 + (1-core)*26 + noise*15;
      image.data[offset+2] = 145 + (1-core)*12 + noise*18;
      image.data[offset+3] = 255 * (.44 + core*.28) * (.22+.78*bank) * field.wet[index];
    }
    context.putImageData(image, 0, 0);
    this.surface.width = this.width; this.surface.height = this.height;
    this.surfaceContext.imageSmoothingEnabled = true;
    this.surfaceContext.drawImage(texture, 0, 0, field.columns*field.cell, field.rows*field.cell);
    this.surfaceContext.globalCompositeOperation = "destination-in"; this.surfaceContext.drawImage(this.mask, 0, 0); this.surfaceContext.globalCompositeOperation = "source-over";
    texture.width = 1; texture.height = 1;
  }
  private advance(delta: number) {
    const field = this.field;
    if (!field?.seeds.length) return;
    const ctx = this.trailContext;
    ctx.globalCompositeOperation = "destination-in"; ctx.fillStyle = `rgba(0,0,0,${Math.exp(-delta*4.3)})`; ctx.fillRect(0, 0, this.width, this.height); ctx.globalCompositeOperation = "source-over";
    ctx.lineCap = "round";
    const paths = palette.map(() => new Path2D());
    for (const particle of this.particles) {
      const flow = sampleWaterField(field, particle.x, particle.y);
      if (particle.age > particle.life || flow.wet < .45) { this.spawn(particle); continue; }
      const wave = .14*Math.sin(particle.x*.024 + particle.y*.015 + this.phase*.75) + .065*Math.sin(particle.y*.055-this.phase*.45);
      const speed = particle.speed * (.50 + .5*Math.min(1, flow.shore/22)) * (.78+.22*Math.exp(-flow.distance/65));
      const dx = flow.vx - flow.vy*wave, dy = flow.vy + flow.vx*wave;
      const midpoint = sampleWaterField(field, particle.x+dx*speed*delta*.5, particle.y+dy*speed*delta*.5);
      const nx = particle.x + (midpoint.vx-midpoint.vy*wave)*speed*delta, ny = particle.y + (midpoint.vy+midpoint.vx*wave)*speed*delta;
      if (midpoint.wet < .35 || !sampleWaterField(field, nx, ny).wet) { this.spawn(particle); continue; }
      const fade = Math.sin(Math.min(1, particle.age/particle.life)*Math.PI), bucket = Math.min(palette.length-1, Math.floor(fade*(.35+particle.brightness*.65)*palette.length));
      paths[bucket].moveTo(particle.x, particle.y); paths[bucket].lineTo(nx, ny);
      particle.x = nx; particle.y = ny; particle.age += delta;
    }
    paths.forEach((path, index) => { ctx.strokeStyle = palette[index]; ctx.lineWidth = index > 3 ? .72 : .5; ctx.stroke(path); });
    ctx.globalCompositeOperation = "destination-in"; ctx.drawImage(this.mask, 0, 0, this.width, this.height); ctx.globalCompositeOperation = "source-over";
  }
  private composite() {
    this.output.clearRect(0, 0, this.width, this.height);
    if (this.field) { this.output.drawImage(this.surface, 0, 0); if (this.currents) this.output.drawImage(this.trails, 0, 0, this.width, this.height); }
    this.canvas.dataset.streaks = String(this.currents ? this.particles.length : 0); this.canvas.dataset.phase = this.phase.toFixed(3);
  }
  dispose() {
    this.disposed = true; this.running = false; cancelAnimationFrame(this.frame);
    this.map.off("movestart", this.onMoveStart); this.map.off("moveend", this.onMoveEnd); this.map.off("resize", this.onMoveEnd);
    this.mapOpacity(.48); this.output.clearRect(0, 0, this.width, this.height);
    [this.mask, this.surface, this.trails].forEach((canvas) => { canvas.width = 1; canvas.height = 1; }); this.particles = []; this.field = null;
  }
}
