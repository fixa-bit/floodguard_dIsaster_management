// Removes single-pixel spikes from a Terrarium elevation tile. The public
// elevation tiles carry a few bad pixels (near Tarbela, points thousands of
// metres above or below the ground around them) that the 3D terrain draws as
// needles. A pixel far from the median of its neighbours is replaced by the
// median of the good pixels around it. Clean tiles are returned unchanged.

const decodeOptions: ImageBitmapOptions = { colorSpaceConversion: "none", premultiplyAlpha: "none" };

const height = (pixels: Uint8ClampedArray, index: number) => pixels[index * 4] * 256 + pixels[index * 4 + 1] + pixels[index * 4 + 2] / 256 - 32768;

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
  const { width, height: rows } = bitmap;
  const canvas = new OffscreenCanvas(width, rows), context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) { bitmap.close(); return bytes; }
  context.drawImage(bitmap, 0, 0);
  bitmap.close();
  const image = context.getImageData(0, 0, width, rows), pixels = image.data;
  const count = width * rows, elevation = new Float32Array(count);
  for (let index = 0; index < count; index++) elevation[index] = height(pixels, index);
  // A spike stands this far from its neighbours' median: well beyond any real
  // cliff at this pixel size (a tile pixel spans about 40000 km / 2^(z+8)).
  const pixelMetres = 40_075_000 / 2 ** (z + 8);
  const limit = Math.max(400, 2 * pixelMetres);
  const at = (x: number, y: number) => elevation[Math.min(rows - 1, Math.max(0, y)) * width + Math.min(width - 1, Math.max(0, x))];
  const spiky = new Uint8Array(count);
  let found = 0;
  for (let pass = 0; pass < 2; pass++) {
    for (let y = 0; y < rows; y++) for (let x = 0; x < width; x++) {
      const index = y * width + x;
      if (spiky[index]) continue;
      const value = elevation[index];
      // Cheap test first: most pixels sit close to the mean of their four neighbours.
      if (Math.abs(value - (at(x - 1, y) + at(x + 1, y) + at(x, y - 1) + at(x, y + 1)) / 4) < limit / 2) continue;
      const around: number[] = [];
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const nx = x + dx, ny = y + dy;
        if ((dx || dy) && nx >= 0 && ny >= 0 && nx < width && ny < rows && !spiky[ny * width + nx]) around.push(elevation[ny * width + nx]);
      }
      if (around.length >= 3 && Math.abs(value - median(around)) > limit) { spiky[index] = 1; found++; }
    }
  }
  if (!found) return bytes;
  for (let y = 0; y < rows; y++) for (let x = 0; x < width; x++) {
    const index = y * width + x;
    if (!spiky[index]) continue;
    const good: number[] = [];
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
      const nx = x + dx, ny = y + dy;
      if (nx >= 0 && ny >= 0 && nx < width && ny < rows && !spiky[ny * width + nx]) good.push(elevation[ny * width + nx]);
    }
    if (!good.length) continue;
    const encoded = Math.round((median(good) + 32768) * 256);
    pixels[index * 4] = (encoded >> 16) & 255;
    pixels[index * 4 + 1] = (encoded >> 8) & 255;
    pixels[index * 4 + 2] = encoded & 255;
    pixels[index * 4 + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  try { return await (await canvas.convertToBlob({ type: "image/png" })).arrayBuffer(); } catch { return bytes; }
}
