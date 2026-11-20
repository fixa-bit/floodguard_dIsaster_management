import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

export const DAY = 86_400_000;
export const toT = (isoDate: string) => Date.parse(isoDate.length > 10 ? isoDate : `${isoDate}T00:00:00Z`);
export const utcDay = (t: number) => Math.floor(t / DAY) * DAY;
export const fmtFlow = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? "—" : Math.round(value).toLocaleString("en-US");
export const fmtDate = (t: number, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }) => new Intl.DateTimeFormat("en-GB", { ...opts, timeZone: "UTC" }).format(new Date(t));

export interface ChartPoint { t: number; v?: number | null; lo?: number | null; hi?: number | null }
export interface ChartSeries {
  id: string;
  kind: "line" | "band" | "dots";
  points: ChartPoint[];
  className: string;
  /** Draw small dots on every point of a line (for sparse daily readings). */
  markers?: boolean;
  /** Per-series inline style, e.g. CSS variables for colour and dash pattern. */
  style?: React.CSSProperties;
}

export function niceMax(value: number) {
  if (!(value > 0)) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  const f = value / exp;
  const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((n) => f <= n) ?? 10;
  return step * exp;
}

export function useWidth<T extends HTMLElement>(fallback = 800) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => setWidth(Math.max(280, node.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function segments(points: ChartPoint[], ok: (p: ChartPoint) => boolean) {
  const out: ChartPoint[][] = [];
  let current: ChartPoint[] = [];
  for (const p of points) {
    if (ok(p)) current.push(p);
    else if (current.length) { out.push(current); current = []; }
  }
  if (current.length) out.push(current);
  return out;
}

interface TimeChartProps {
  ariaLabel: string;
  height: number;
  start: number;
  end: number;
  series: ChartSeries[];
  markers?: Array<{ t: number; label: string; className?: string }>;
  hlines?: Array<{ v: number; label: string; className?: string }>;
  ticks?: "week" | "month" | "month-name";
  yFloor?: number;
  tooltip: (t: number) => ReactNode | null;
  compact?: boolean;
}

/** One-axis time chart: bands, lines and dot+whisker estimates, with a crosshair tooltip. */
export function TimeChart({ ariaLabel, height, start, end, series, markers = [], hlines = [], ticks = "month", yFloor = 10, tooltip, compact }: TimeChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = compact ? { l: 44, r: 10, t: 12, b: 24 } : { l: 56, r: 16, t: 18, b: 30 };
  const w = width - m.l - m.r;
  const h = height - m.t - m.b;

  const yMax = useMemo(() => {
    let max = yFloor;
    for (const s of series) for (const p of s.points) {
      if (p.t < start || p.t > end) continue;
      for (const v of [p.v, p.hi]) if (v != null && Number.isFinite(v)) max = Math.max(max, v);
    }
    for (const line of hlines) max = Math.max(max, line.v);
    return niceMax(max * 1.06);
  }, [series, hlines, start, end, yFloor]);

  const x = (t: number) => m.l + ((t - start) / (end - start)) * w;
  const y = (v: number) => m.t + h - (v / yMax) * h;
  const inView = (p: ChartPoint) => p.t >= start && p.t <= end;

  const xTicks = useMemo(() => {
    const out: number[] = [];
    if (ticks === "week") {
      for (let t = utcDay(start) + DAY; t <= end; t += DAY) if (new Date(t).getUTCDay() === 1) out.push(t);
    } else {
      const d = new Date(start);
      let cursor = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
      while (cursor <= end) { out.push(cursor); const c = new Date(cursor); cursor = Date.UTC(c.getUTCFullYear(), c.getUTCMonth() + 1, 1); }
    }
    const every = Math.max(1, Math.ceil(out.length / Math.max(2, Math.floor(w / 78))));
    return out.filter((_, i) => i % every === 0);
  }, [start, end, ticks, w]);

  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    setHover(utcDay(start + ratio * (end - start) + DAY / 2));
  };
  const tip = hover == null ? null : tooltip(hover);
  const hoverRatio = hover == null ? 0 : (x(hover) / width);

  return <div className="ro-chart" ref={ref} style={{ height }}>
    <svg width={width} height={height} role="img" aria-label={ariaLabel}>
      {Array.from({ length: 5 }, (_, i) => yMax * i / 4).map((v) => <g key={v}>
        <line className="ro-grid" x1={m.l} x2={width - m.r} y1={y(v)} y2={y(v)} />
        <text className="ro-tick" x={m.l - 8} y={y(v) + 4} textAnchor="end">{v >= 10_000 ? `${Math.round(v / 1000)}k` : fmtFlow(v)}</text>
      </g>)}
      {xTicks.map((t) => <text key={t} className="ro-tick" x={x(t)} y={height - 8} textAnchor="middle">
        {ticks === "month-name" ? fmtDate(t, { month: "short" }) : ticks === "month" ? (new Date(t).getUTCMonth() === 0 || t === xTicks[0] ? fmtDate(t, { month: "short", year: "numeric" }) : fmtDate(t, { month: "short" })) : fmtDate(t)}
      </text>)}
      {series.filter((s) => s.kind === "band").map((s) => segments(s.points.filter(inView), (p) => p.lo != null && p.hi != null).map((seg, i) => {
        const upper = seg.map((p) => `${x(p.t)},${y(p.hi as number)}`);
        const lower = seg.map((p) => `${x(p.t)},${y(p.lo as number)}`).reverse();
        return <polygon key={`${s.id}-${i}`} className={s.className} points={[...upper, ...lower].join(" ")} />;
      }))}
      {hlines.map((line) => <g key={line.label} className={line.className ?? "ro-hline"}>
        <line x1={m.l} x2={width - m.r} y1={y(line.v)} y2={y(line.v)} />
        <text x={width - m.r - 4} y={y(line.v) - 6} textAnchor="end">{line.label}</text>
      </g>)}
      {markers.map((mk) => mk.t >= start && mk.t <= end && <g key={mk.label} className={mk.className ?? "ro-marker"}>
        <line x1={x(mk.t)} x2={x(mk.t)} y1={m.t - 4} y2={m.t + h} />
        <text x={x(mk.t) + 5} y={m.t + 8}>{mk.label}</text>
      </g>)}
      {series.filter((s) => s.kind === "line").map((s) => <g key={s.id} className={s.className} style={s.style}>
        {segments(s.points.filter(inView), (p) => p.v != null && Number.isFinite(p.v)).map((seg, i) => seg.length === 1
          ? <circle key={i} cx={x(seg[0].t)} cy={y(seg[0].v as number)} r={3} />
          : <path key={i} d={seg.map((p, j) => `${j ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v as number).toFixed(1)}`).join("")} />)}
        {s.markers && s.points.filter(inView).map((p) => p.v != null && <circle key={p.t} className="ro-line-dot" cx={x(p.t)} cy={y(p.v)} r={2.6} />)}
      </g>)}
      {series.filter((s) => s.kind === "dots").map((s) => <g key={s.id} className={s.className}>
        {s.points.filter(inView).map((p) => p.v != null && <g key={p.t}>
          {p.lo != null && p.hi != null && p.hi > p.lo && <line className="ro-whisker" x1={x(p.t)} x2={x(p.t)} y1={y(p.hi)} y2={y(p.lo)} />}
          <circle cx={x(p.t)} cy={y(p.v)} r={5.5} />
        </g>)}
      </g>)}
      {hover != null && <line className="ro-crosshair" x1={x(hover)} x2={x(hover)} y1={m.t} y2={m.t + h} />}
      <rect className="ro-hit" x={m.l} y={m.t} width={Math.max(0, w)} height={Math.max(0, h)} onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
    </svg>
    {tip && <div className={`ro-tooltip${hoverRatio > 0.62 ? " flip" : ""}`} style={{ left: `${hoverRatio * 100}%` }}>{tip}</div>}
  </div>;
}

/** Bars with GCM-range whiskers and a dashed reference line; per-bar hover. */
export function OddsBars({ rows, baseline, className, ariaLabel }: {
  rows: Array<{ label: string; value: number | null; low: number | null; high: number | null }>;
  baseline: number | null;
  className: string;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = 230;
  const m = { l: 44, r: 12, t: 16, b: 28 };
  const w = width - m.l - m.r;
  const h = height - m.t - m.b;
  const max = Math.min(1, niceMax(Math.max(baseline ?? 0, ...rows.map((r) => r.high ?? r.value ?? 0)) * 1.05));
  const y = (v: number) => m.t + h - (v / max) * h;
  const band = w / Math.max(1, rows.length);
  const bw = Math.min(26, band * 0.56);
  const item = hover == null ? null : rows[hover];
  return <div className="ro-chart" ref={ref} style={{ height }}>
    <svg width={width} height={height} role="img" aria-label={ariaLabel}>
      {Array.from({ length: 5 }, (_, i) => max * i / 4).map((v) => <g key={v}>
        <line className="ro-grid" x1={m.l} x2={width - m.r} y1={y(v)} y2={y(v)} />
        <text className="ro-tick" x={m.l - 8} y={y(v) + 4} textAnchor="end">{Math.round(v * 100)}%</text>
      </g>)}
      {rows.map((r, i) => {
        const cx = m.l + band * i + band / 2;
        return <g key={r.label} className={`${className}${hover === i ? " active" : ""}`}>
          {r.value != null && <path d={`M${cx - bw / 2},${y(0)} V${y(r.value) + 4} q0,-4 4,-4 H${cx + bw / 2 - 4} q4,0 4,4 V${y(0)} Z`} />}
          {r.low != null && r.high != null && <line className="ro-whisker" x1={cx} x2={cx} y1={y(r.high)} y2={y(r.low)} />}
          {(i % Math.ceil(rows.length / Math.max(2, Math.floor(w / 46))) === 0) && <text className="ro-tick" x={cx} y={height - 8} textAnchor="middle">{r.label}</text>}
          <rect className="ro-hit" x={cx - band / 2} y={m.t} width={band} height={h} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)} />
        </g>;
      })}
      {baseline != null && <g className="ro-hline baseline">
        <line x1={m.l} x2={width - m.r} y1={y(baseline)} y2={y(baseline)} />
      </g>}
    </svg>
    {item && hover != null && <div className={`ro-tooltip${(hover + 0.5) / rows.length > 0.62 ? " flip" : ""}`} style={{ left: `${((m.l + band * hover + band / 2) / width) * 100}%` }}>
      <strong>{item.label}</strong>
      <span>Median of 8 climate models: <b>{item.value == null ? "—" : `${Math.round(item.value * 100)}%`}</b></span>
      <span>Model range: {item.low == null ? "—" : `${Math.round(item.low * 100)}–${Math.round((item.high ?? 0) * 100)}%`}</span>
    </div>}
  </div>;
}
