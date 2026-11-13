// Removes spikes from a Terrarium elevation tile. The public elevation tiles
// carry bad points (around Tarbela, small clusters of pixels hundreds to
// thousands of metres above or below the ground around them) that the 3D
// terrain draws as needles. Each point is compared with the ring of ground two
// pixels out, so a cluster of bad pixels cannot hide behind its own members; a
// spike's flanks are cleared with it. Clean tiles are returned unchanged.

const decodeOptions: ImageBitmapOptions = { colorSpaceConversion: "none", premultiplyAlpha: "none" };

function median(values: number[]) {
  values.sort((a, b) => a - b);
  const middle = values.length >> 1;
  return values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
}

/**
 * `bytes` is a Terrarium PNG at zoom `z`. Resolves to the same bytes when the
 * tile has no spikes, else to a cleaned PNG.
 */
export async function despikeTerrarium(bytes: ArrayBuffer, z: number): Promise<ArrayBuffer> {
  if (typeof OffscreenCanvas === "undefined") return bytes;
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }), decodeOptions); } catch { return bytes; }
  const { width, height } = bitmap;
  const canvas = new OffscreenCanvas(width, height), context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) { bitmap.close(); return bytes; }
  context.drawImage(bitmap, 0, 0);
  bitmap.close();
  const image = context.getImageData(0, 0, width, height), pixels = image.data;
  const count = width * height, elevation = new Float32Array(count);
  for (let index = 0; index < count; index++) elevation[index] = pixels[index * 4] * 256 + pixels[index * 4 + 1] + pixels[index * 4 + 2] / 256 - 32768;

  // A spike stands this far above or below the ground two pixels away: more
  // than a near-vertical wall at this pixel size (about 40000 km / 2^(z+8)).
  // Even Nanga Parbat's faces stay well inside it.
  const limit = Math.max(250, 4 * 40_075_000 / 2 ** (z + 8));
  const at = (x: number, y: number) => elevation[Math.min(height - 1, Math.max(0, y)) * width + Math.min(width - 1, Math.max(0, x))];
  /** Median of the 16 pixels exactly two steps away. */
  const ring = (x: number, y: number) => {
    const values: number[] = [];
    for (let d = -2; d <= 2; d++) values.push(at(x + d, y - 2), at(x + d, y + 2));
    for (let d = -1; d <= 1; d++) values.push(at(x - 2, y + d), at(x + 2, y + d));
    return median(values);
  };
  const standsOut = (x: number, y: number, by: number) => {
    const value = elevation[y * width + x];
    // Cheap test first: most pixels sit close to the mean of eight ring points.
    const rough = (at(x - 2, y) + at(x + 2, y) + at(x, y - 2) + at(x, y + 2) + at(x - 2, y - 2) + at(x + 2, y - 2) + at(x - 2, y + 2) + at(x + 2, y + 2)) / 8;
    return Math.abs(value - rough) > by / 2 && Math.abs(value - ring(x, y)) > by;
  };
  const spikes = () => {
    const found: number[] = [];
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (standsOut(x, y, limit)) found.push(y * width + x);
    return found;
  };

  let bad = spikes();
  if (!bad.length) return bytes;
  const near = new Uint8Array(count), flagged = new Uint8Array(count);
  for (let pass = 0; pass < 3 && bad.length; pass++) {
    flagged.fill(0);
    for (const index of bad) {
      flagged[index] = 1;
      const x = index % width, y = (index - x) / width;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < width && ny < height) near[ny * width + nx] = 1;
      }
    }
    // A spike's flanks: points beside it that still stand out by a third as much.
    for (let index = 0; index < count; index++) {
      if (!near[index] || flagged[index]) continue;
      const x = index % width;
      if (standsOut(x, (index - x) / width, limit / 3)) flagged[index] = 1;
    }
    for (let index = 0; index < count; index++) {
      if (!flagged[index]) continue;
      const x = index % width, y = (index - x) / width, good: number[] = [];
      for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) {
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < width && ny < height && !flagged[ny * width + nx]) good.push(elevation[ny * width + nx]);
      }
      if (good.length) elevation[index] = median(good);
    }
    bad = spikes();
  }

  for (let index = 0; index < count; index++) {
    const encoded = Math.round((elevation[index] + 32768) * 256);
    pixels[index * 4] = (encoded >> 16) & 255;
    pixels[index * 4 + 1] = (encoded >> 8) & 255;
    pixels[index * 4 + 2] = encoded & 255;
    pixels[index * 4 + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  try { return await (await canvas.convertToBlob({ type: "image/png" })).arrayBuffer(); } catch { return bytes; }
}
