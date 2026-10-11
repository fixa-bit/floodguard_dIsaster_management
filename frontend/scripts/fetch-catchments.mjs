import { readFile, writeFile } from "node:fs/promises";
import { area } from "@turf/area";
import { bbox } from "@turf/bbox";
import { booleanIntersects } from "@turf/boolean-intersects";

const service = "https://services3.arcgis.com/AdYB7LvDmN7hzWUb/arcgis/rest/services/Hydrobasins/FeatureServer/2";
const query = new URLSearchParams({
  f: "geojson", where: "1=1", outFields: "basinid", outSR: "4326",
  geometry: "60.5,23.4,77.5,37.5", geometryType: "esriGeometryEnvelope",
  inSR: "4326", spatialRel: "esriSpatialRelIntersects", returnGeometry: "true",
  maxAllowableOffset: "0.005", geometryPrecision: "5", resultRecordCount: "2000",
});
const response = await fetch(`${service}/query?${query}`, { signal: AbortSignal.timeout(60000) });
if (!response.ok) throw new Error(`Catchment download failed: ${response.status}`);
const downloaded = await response.json();
if (downloaded.error || downloaded.exceededTransferLimit || !downloaded.features?.length) {
  throw new Error(`Catchment download incomplete: ${JSON.stringify(downloaded.error ?? downloaded.properties ?? {})}`);
}
const pakistan = JSON.parse(await readFile(new URL("../src/data/pakistan/pakistan_admin1.geojson", import.meta.url), "utf8"));
const features = downloaded.features
  .filter((feature) => pakistan.features.some((region) => booleanIntersects(feature, region)))
  .map((feature) => {
    const id = String(feature.properties.basinid);
    if (!/^\d+$/.test(id)) throw new Error(`Invalid basin ID: ${id}`);
    return {
      type: "Feature", id, bbox: bbox(feature),
      properties: {
        basin_id: id, name: `Sub-basin ${id}`, area_km2: Math.round(area(feature) / 1e6),
        source: "HydroBASINS", level: 5,
      },
      geometry: feature.geometry,
    };
  }).sort((a, b) => a.id.localeCompare(b.id));
if (features.length < 10 || new Set(features.map((feature) => feature.id)).size !== features.length) {
  throw new Error("Catchment extract failed validation");
}
const collection = {
  type: "FeatureCollection",
  metadata: {
    name: "HydroBASINS catchments intersecting Pakistan operational areas",
    source: "HydroBASINS / HydroSHEDS", source_url: "https://www.hydrosheds.org/products/hydrobasins",
    service_url: service, retrieved_at: new Date().toISOString(), level: 5,
    boundary_type: "hydrological_sub_basin", simplification_degrees: 0.005,
    note: "Full transboundary sub-basins intersecting the portal's operational ADM1 areas. Geometry simplified for display; area is approximate. These are sub-basins, not station-specific upstream watersheds.",
    attribution: "Lehner, B., Grill, G. (2013): Global river hydrography and network routing. Hydrological Processes, 27(15): 2171-2186. https://doi.org/10.1002/hyp.9740",
  },
  features,
};
await writeFile(new URL("../src/data/pakistan/catchment_areas.geojson", import.meta.url), `${JSON.stringify(collection)}\n`);
console.log(`Downloaded ${features.length} HydroBASINS level-5 catchments (${JSON.stringify(collection).length} bytes)`);
