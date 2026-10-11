import type { FeatureCollection } from "geojson";

interface DataSource {
  setData(data: FeatureCollection): unknown;
  serialize(): { data?: unknown };
}

const lastData = new WeakMap<DataSource, unknown>();
const updateCounts = new WeakMap<DataSource, number>();

// Keep immutable collections out of the worker queue when unrelated feeds refresh.
export function updateMapSource(source: DataSource | undefined, data: FeatureCollection): boolean {
  if (!source) return false;
  if (!lastData.has(source)) lastData.set(source, source.serialize().data);
  if (lastData.get(source) === data) return false;
  source.setData(data);
  lastData.set(source, data);
  updateCounts.set(source, (updateCounts.get(source) ?? 0) + 1);
  return true;
}

export function sourceUpdateCount(source: DataSource | undefined): number {
  return source ? updateCounts.get(source) ?? 0 : 0;
}
