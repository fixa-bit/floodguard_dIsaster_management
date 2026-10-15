import { useEffect, useState } from "react";
import type { ErrorEvent as MapLibreErrorEvent, Map as MapLibreMap } from "maplibre-gl";
import { loadMapAsset } from "./mapAssets";

export type ReplayTerrain = {
  id: string; bounds: [number, number, number, number]; sample_spacing_m_approx: number;
  elevation_min_m: number; elevation_max_m: number; source: string; source_url: string;
  hillshade_exaggeration: number; hydraulic_reference: { title: string; url: string; status: string; retrieval: string };
};
export const replayTerrainBase = `${import.meta.env.BASE_URL}simulation-terrain/`;

export function useReplayTerrain(map: MapLibreMap | null, ready: boolean, selection: string, enabled: boolean) {
  const [metadata, setMetadata] = useState<ReplayTerrain | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (selection !== "jhang") return;
    let disposed = false;
    setError(false);
    loadMapAsset<ReplayTerrain>(`${replayTerrainBase}jhang-metadata.json`).then((result) => { if (!disposed) setMetadata(result); }).catch(() => { if (!disposed) setError(true); });
    return () => { disposed = true; };
  }, [selection]);
  const data = selection === "jhang" ? metadata : null;
  useEffect(() => {
    if (!map || !ready) return;
    const onError = (event: MapLibreErrorEvent & { sourceId?: string }) => {
      if (event.sourceId === "replay-real-terrain" || event.error?.message.includes("replay-real-terrain") || event.error?.message.includes("simulation-terrain/")) {
        setError(true);
        if (map.getLayer("replay-real-terrain")) map.setLayoutProperty("replay-real-terrain", "visibility", "none");
        map.getContainer().dataset.realTerrain = "false";
      }
    };
    map.on("error", onError);
    return () => { map.off("error", onError); };
  }, [map, ready]);
  useEffect(() => {
    if (!map || !ready) return;
    if (data && enabled && !map.getSource("replay-real-terrain")) {
      const [w, s, e, n] = data.bounds;
      map.addSource("replay-real-terrain", { type: "image", url: `${replayTerrainBase}jhang-hillshade.png`, coordinates: [[w, n], [e, n], [e, s], [w, s]] });
      if (map.getSource("replay-real-terrain")) map.addLayer({ id: "replay-real-terrain", type: "raster", source: "replay-real-terrain", paint: { "raster-opacity": .22, "raster-fade-duration": 0 } }, "replay-population");
    }
    if (map.getLayer("replay-real-terrain")) map.setLayoutProperty("replay-real-terrain", "visibility", data && enabled ? "visible" : "none");
    map.getContainer().dataset.realTerrain = String(Boolean(data && enabled));
  }, [map, ready, data, enabled]);
  return { data, error };
}
