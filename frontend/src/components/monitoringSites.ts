import type { FeatureCollection, Point } from "geojson";

export const monitoringCategories = [
  { id: "barrages", label: "Major barrages & headworks", priority: "Critical", color: "#ff526d", shape: "square" },
  { id: "upstream", label: "Upstream river stations", priority: "High", color: "#ffc857", shape: "triangle" },
  { id: "dams", label: "Major dams & reservoirs", priority: "High", color: "#38cbea", shape: "dam" },
  { id: "confluences", label: "Confluence watch locations", priority: "Medium", color: "#d4a2ff", shape: "diamond" },
] as const;
export type MonitoringCategory = typeof monitoringCategories[number]["id"];
export interface MonitoringSite {
  id: string; name: string; category: MonitoringCategory; river: string;
  stationId: string | null; source: string; coordinateQuality: string;
}
const ffd = "https://ffd.pmd.gov.pk/river-state?zoom=6";
type SiteRow = [string, string, MonitoringCategory, string, number, number, string?, string?];
// FFD points retain the coordinates in app/gis/river_stations.py, not the older water-body approximations.
const rows: SiteRow[] = [
  ["CHASHMA", "Chashma Barrage", "barrages", "Indus", 71.3794, 32.4359],
  ["TAUNSA", "Taunsa Barrage", "barrages", "Indus", 70.836721, 30.518528],
  ["GUDDU", "Guddu Barrage", "barrages", "Indus", 69.7114, 28.4201],
  ["SUKKUR", "Sukkur Barrage", "barrages", "Indus", 68.8462, 27.679],
  ["KOTRI", "Kotri Barrage", "barrages", "Indus", 68.3151, 25.4428],
  ["RASUL", "Rasul Barrage", "barrages", "Jhelum", 73.517, 32.683],
  ["BALLOKI", "Balloki Headworks", "barrages", "Ravi", 73.8596, 31.2222],
  ["SIDHNAI", "Sidhnai Barrage", "barrages", "Ravi", 72.1582, 30.5723],
  ["MARALA", "Marala Headworks", "barrages", "Chenab", 74.41125, 32.660583],
  ["KHANKI", "Khanki Headworks", "barrages", "Chenab", 73.9685, 32.4088],
  ["QADIRABAD", "Qadirabad Barrage", "barrages", "Chenab", 73.6851, 32.3209],
  ["TRIMMU", "Trimmu Barrage", "barrages", "Chenab", 72.146, 31.1448],
  ["PANJNAD", "Panjnad Headworks", "barrages", "Panjnad", 71.0202, 29.3464],
  ["SULEMANKI", "Sulemanki Headworks", "barrages", "Sutlej", 73.8663, 30.3777],
  ["ISLAM", "Islam Headworks", "barrages", "Sutlej", 72.5485, 29.8263],
  ["KALABAGH", "Kalabagh River Station", "upstream", "Indus", 71.5219, 32.9187],
  ["NOWSHERA", "Nowshera River Station", "upstream", "Kabul", 71.975, 34.015],
  ["JASSAR", "Jassar River Station", "upstream", "Ravi", 74.992018, 32.049654],
  ["SHAHDARA", "Shahdara River Station", "upstream", "Ravi", 74.2956, 31.6085],
  ["GANDA_SINGH_WALA", "Ganda Singh Wala River Station", "upstream", "Sutlej", 74.545256, 30.993429],
  ["CHAKDARA", "Chakdara Stream Gauge", "upstream", "Swat", 72.025, 34.644444,
    "https://www.pwri.go.jp/icharm/training/master/img/2017/synopses/muhamad_gul.pdf", "Published WAPDA gauge reference (2017); current feed not connected"],
  ["TARBELA", "Tarbela Dam / Reservoir", "dams", "Indus", 72.7338, 34.1059],
  ["MANGLA", "Mangla Dam / Reservoir", "dams", "Jhelum", 73.645, 33.142],
  ["WARSAK", "Warsak Dam / Reservoir", "dams", "Kabul", 71.37, 34.16,
    "https://wapda.gov.pk/warsak-dam/", "Existing GIS reference; approximate dam location"],
  ["KABUL_INDUS", "Kabul - Indus / Attock", "confluences", "Kabul / Indus", 72.23222, 33.91667,
    "https://en.wikipedia.org/wiki/Kabul_River", "Approximate confluence reach; not a surveyed gauge"],
  ["JHELUM_CHENAB", "Jhelum - Chenab / Trimmu reach", "confluences", "Jhelum / Chenab", 72.149277, 31.185343,
    "https://fr.wikipedia.org/wiki/Jhelum_(rivi%C3%A8re)", "Approximate confluence reach; not a surveyed gauge"],
  ["SUTLEJ_CHENAB", "Sutlej - Chenab / Panjnad reach", "confluences", "Sutlej / Chenab", 71.02816, 29.34926,
    "https://de.wikipedia.org/wiki/Panjnad", "Approximate confluence reach; not a surveyed gauge"],
  ["PANJNAD_INDUS", "Panjnad - Indus / Mithankot reach", "confluences", "Panjnad / Indus", 70.69874, 29.10868,
    "https://de.wikipedia.org/wiki/Panjnad", "Approximate confluence reach; channel position may change"],
];
export const monitoringSites: FeatureCollection<Point, MonitoringSite> = {
  type: "FeatureCollection",
  features: rows.map(([id, name, category, river, longitude, latitude, source, coordinateQuality]) => ({
    type: "Feature", id, geometry: { type: "Point", coordinates: [longitude, latitude] },
    properties: { id, name, category, river, stationId: source ? null : id, source: source ?? ffd,
      coordinateQuality: coordinateQuality ?? "Existing FFD station reference; not survey-certified" },
  })),
};
