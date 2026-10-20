import type { Map as MapLibreMap } from "maplibre-gl";
import { flowFrame, type TerrainFlowData } from "./ndmaTerrainFlowData";

type Particle = { x: number; y: number; age: number };
/** All particle directions and relative speeds come from the saved model fluxes. */
export class TerrainFlowRenderer {
  private ctx: CanvasRenderingContext2D;
  private water = document.createElement("canvas");
  private trails = document.createElement("canvas");
  private particles: Particle[] = [];
  private wet: number[] = [];
  private frame: ReturnType<typeof flowFrame>;
  private running = false;
  private currents = true;
  private raf = 0;
  private previous = 0;
  private disposed = false;
  private count = 0;
  constructor(private canvas: HTMLCanvasElement, private map: MapLibreMap, private data: TerrainFlowData, private buffer: ArrayBuffer) {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Water animation requires Canvas 2D");
    this.ctx = ctx; this.frame = flowFrame(data, buffer, 0);
    this.water.width = data.cols; this.water.height = data.rows;
    map.on("move", this.redraw); map.on("resize", this.redraw); map.on("moveend",this.developSnapshot);
    this.setFrame(0);
  }
  setFrame(index: number) {
    this.frame = flowFrame(this.data, this.buffer, index);
    const context = this.water.getContext("2d")!, pixels = context.createImageData(this.data.cols, this.data.rows);
    this.wet = [];
    this.frame.depth.forEach((value, i) => {
      const depth = value*this.data.depth_unit_m;
      if (depth < this.data.wet_threshold_m) return;
      const shade = Math.min(1, depth/this.data.depth_color_max_m), p = i*4;
      const light = 5*Math.sin(i%this.data.cols*.7+Math.floor(i/this.data.cols)*.3);
      pixels.data[p] = 48-25*shade+light; pixels.data[p+1] = 159-58*shade+light;
      pixels.data[p+2] = 210-35*shade+light; pixels.data[p+3] = 155+65*shade;
      this.wet.push(i);
    });
    context.putImageData(pixels, 0, 0);
    this.particles = Array.from({length: this.wet.length ? Math.min(1800, Math.max(250, this.wet.length*2)) : 0}, () => this.spawn());
    this.developSnapshot();
    this.canvas.dataset.frame = String(index); this.canvas.dataset.wetCells = String(this.wet.length);
  }
  setCurrents(value: boolean) { this.currents = value; this.redraw(false); }
  setRunning(value: boolean) {
    this.running = value; cancelAnimationFrame(this.raf); this.previous = 0;
    if (value) this.raf = requestAnimationFrame(this.tick);
  }
  private spawn(): Particle {
    const index = this.wet[Math.floor(Math.random()*this.wet.length)] ?? 0;
    return {x: index%this.data.cols+.15+Math.random()*.7, y: Math.floor(index/this.data.cols)+.15+Math.random()*.7, age: Math.random()*3};
  }
  private project(x: number, y: number) {
    const [w, s, e, n] = this.data.bounds;
    const top = Math.log(Math.tan(Math.PI/4+n*Math.PI/360)), bottom = Math.log(Math.tan(Math.PI/4+s*Math.PI/360));
    const latitude = Math.atan(Math.sinh(top+y/this.data.rows*(bottom-top)))*180/Math.PI;
    return this.map.project([w+x/this.data.cols*(e-w), latitude]);
  }
  private rect() {
    const a = this.project(0, 0), b = this.project(this.data.cols, this.data.rows);
    return { x: a.x, y: a.y, w: b.x-a.x, h: b.y-a.y };
  }
  private velocity(x: number, y: number) {
    const {cols, rows, wet_threshold_m, depth_unit_m, velocity_unit_ms} = this.data;
    if (x < 0 || y < 0 || x >= cols || y >= rows) return null;
    const index = Math.floor(y)*cols+Math.floor(x);
    if (this.frame.depth[index]*depth_unit_m < wet_threshold_m) return null;
    // Wet-weighted bilinear sampling smooths the saved cell velocities without inventing a direction field.
    const fx = Math.max(0, Math.min(cols-1, x-.5)), fy = Math.max(0, Math.min(rows-1, y-.5));
    const x0 = Math.floor(fx), y0 = Math.floor(fy), tx = fx-x0, ty = fy-y0;
    let vx = 0, vy = 0, sum = 0;
    for (const [cx, cy, weight] of [[x0,y0,(1-tx)*(1-ty)], [Math.min(cols-1,x0+1),y0,tx*(1-ty)], [x0,Math.min(rows-1,y0+1),(1-tx)*ty], [Math.min(cols-1,x0+1),Math.min(rows-1,y0+1),tx*ty]]) {
      const i = cy*cols+cx;
      if (this.frame.depth[i]*depth_unit_m < wet_threshold_m) continue;
      vx += this.frame.vx[i]*velocity_unit_ms*weight; vy += this.frame.vy[i]*velocity_unit_ms*weight; sum += weight;
    }
    return {vx: vx/(sum||1), vy: vy/(sum||1)};
  }
  private tick = (now: number) => {
    if (this.disposed || !this.running) return;
    if (!this.previous) this.previous = now;
    const dt = Math.min(.05, (now-this.previous)/1000);
    if (now-this.previous >= 1000/30) {
      this.previous = now;
      if (this.currents && this.wet.length) this.advance(dt);
      this.redraw(false); this.canvas.dataset.frames = String(++this.count);
    }
    this.raf = requestAnimationFrame(this.tick);
  };
  private advance(dt: number) {
        const ctx = this.trails.getContext("2d")!, r = this.rect();
        ctx.globalCompositeOperation = "destination-in"; ctx.fillStyle = `rgba(0,0,0,${Math.exp(-dt*1.4)})`; ctx.fillRect(0,0,this.trails.width,this.trails.height);
        ctx.globalCompositeOperation = "source-over"; ctx.strokeStyle = "rgba(206,244,255,.58)"; ctx.lineWidth = .8; ctx.beginPath();
        this.particles.forEach((particle, i) => {
          const velocity = this.velocity(particle.x, particle.y);
          if (!velocity || particle.age > 5) { this.particles[i] = this.spawn(); return; }
          const nx = particle.x+velocity.vx*dt*60/this.data.dx_m, ny = particle.y+velocity.vy*dt*60/this.data.dy_m;
          if (!this.velocity(nx, ny)) { this.particles[i] = this.spawn(); return; }
          const a = this.project(particle.x, particle.y), b = this.project(nx, ny);
          ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y);
          particle.x = nx; particle.y = ny; particle.age += dt;
        });
        ctx.stroke();
        // Clip with an opaque wet mask, so repeated clipping does not erase low-depth trails.
        ctx.globalCompositeOperation = "destination-in";
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(this.mask(), r.x,r.y,r.w,r.h); ctx.globalCompositeOperation = "source-over";
  }
  private wetMask = document.createElement("canvas");
  private mask() { return this.wetMask; }
  private developSnapshot = () => {
    this.redraw();
    // Develop the same computed-velocity trails for paused and reduced-motion snapshots.
    if (this.wet.length) for (let i=0;i<24;i++) this.advance(1/30);
    this.redraw(false);
  };
  private redraw = (clear: unknown = true) => {
    if (this.disposed) return;
    const width = this.map.getContainer().clientWidth, height = this.map.getContainer().clientHeight;
    if (!width || !height) return;
    if (this.canvas.width !== width || this.canvas.height !== height || clear !== false) {
      this.canvas.width = width; this.canvas.height = height;
      this.trails.width = width; this.trails.height = height;
      this.wetMask.width = this.data.cols; this.wetMask.height = this.data.rows;
      const ctx = this.wetMask.getContext("2d")!, pixels = ctx.createImageData(this.data.cols,this.data.rows);
      this.wet.forEach(i => { pixels.data[i*4+3] = 255; }); ctx.putImageData(pixels,0,0);
    }
    const r = this.rect();
    this.ctx.clearRect(0,0,width,height); this.ctx.imageSmoothingEnabled = false;
    this.ctx.drawImage(this.water,r.x,r.y,r.w,r.h);
    if (this.currents) this.ctx.drawImage(this.trails,0,0);
  };
  dispose() {
    this.disposed = true; cancelAnimationFrame(this.raf);
    this.map.off("move",this.redraw); this.map.off("resize",this.redraw); this.map.off("moveend",this.developSnapshot);
    this.particles = []; [this.water,this.trails,this.wetMask].forEach(c => {c.width=1;c.height=1;});
  }
}
