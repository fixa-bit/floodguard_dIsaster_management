import { useEffect, useMemo, useRef, type RefObject } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { FloodExposurePreview } from "./outlookFloodExposureData";
import { currentRoutes, waterPolygons } from "./stormReplayData";
import { ReplayWaterRenderer } from "./ReplayWaterRenderer";

export function useReplayCurrents({ map, canvas, data, level, enabled, animate }: {
  map: MapLibreMap | null; canvas: RefObject<HTMLCanvasElement | null>;
  data: FloodExposurePreview | null; level: number; enabled: boolean; animate: boolean;
}) {
  const routes = useMemo(() => data?.supported ? currentRoutes(data) : [], [data]);
  const polygons = useMemo(() => waterPolygons(data, level), [data, level]);
  const renderer = useRef<ReplayWaterRenderer | null>(null);
  useEffect(() => {
    if (!map || !canvas.current) return;
    try { renderer.current = new ReplayWaterRenderer(canvas.current, map); }
    catch { canvas.current.dataset.renderer = "map-fallback"; }
    return () => { renderer.current?.dispose(); renderer.current = null; };
  }, [map, canvas]);
  useEffect(() => { renderer.current?.setScene(routes, polygons, level); }, [map, routes, polygons, level]);
  useEffect(() => { renderer.current?.setCurrents(enabled); }, [map, enabled]);
  useEffect(() => { renderer.current?.setRunning(animate && enabled); }, [map, animate, enabled]);
}
