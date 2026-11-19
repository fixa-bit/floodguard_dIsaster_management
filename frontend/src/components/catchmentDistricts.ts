import { area } from "@turf/area";
import { bbox } from "@turf/bbox";
import { intersect } from "@turf/intersect";
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";

export interface CatchmentDistrict { name: string; province: string; overlapKm2: number; share: number }

/**
 * The districts a catchment covers, largest overlap first. A district counts when at least 5% of
 * it, or 250 km², lies inside the catchment (slivers along a shared border are left out).
 */
export function districtsInCatchment(catchment: Feature | undefined, districts: FeatureCollection): CatchmentDistrict[] {
  if (!catchment || (catchment.geometry?.type !== "Polygon" && catchment.geometry?.type !== "MultiPolygon")) return [];
  const shape = catchment as Feature<Polygon | MultiPolygon>;
  const [w, s, e, n] = bbox(shape);
  const found: CatchmentDistrict[] = [];
  for (const district of districts.features) {
    const name = String(district.properties?.district_name ?? "").trim();
    if (!name || (district.geometry?.type !== "Polygon" && district.geometry?.type !== "MultiPolygon")) continue;
    const [dw, ds, de, dn] = bbox(district);
    if (dw > e || de < w || ds > n || dn < s) continue;
    let overlap: Feature<Polygon | MultiPolygon> | null = null;
    try {
      overlap = intersect({ type: "FeatureCollection", features: [shape, district as Feature<Polygon | MultiPolygon>] });
    } catch { continue; }
    if (!overlap) continue;
    const overlapKm2 = area(overlap) / 1e6, share = overlapKm2 / Math.max(1, area(district) / 1e6);
    if (share >= 0.05 || overlapKm2 >= 250) found.push({ name, province: String(district.properties?.province ?? ""), overlapKm2, share });
  }
  return found.sort((a, b) => b.overlapKm2 - a.overlapKm2);
}
