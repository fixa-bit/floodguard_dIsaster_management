// Runs the elevation spike filter off the main thread, so cleaning the tour's
// thousands of terrain tiles never stalls the camera.
import { despikeTerrarium } from "./terrariumDespike";

self.onmessage = async (event: MessageEvent<{ id: number; bytes: ArrayBuffer; zoom: number }>) => {
  const { id, bytes, zoom } = event.data;
  let cleaned = bytes;
  try { cleaned = await despikeTerrarium(bytes, zoom); } catch { /* keep the tile as it is */ }
  (self as unknown as Worker).postMessage({ id, bytes: cleaned }, [cleaned]);
};
