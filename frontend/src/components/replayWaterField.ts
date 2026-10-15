// A view-local artistic vector field. No velocities, depths, or hydraulic claims.
export type ScreenPoint = { x: number; y: number };
export type WaterField = {
  width: number; height: number; cell: number; columns: number; rows: number;
  wet: Float32Array; vx: Float32Array; vy: Float32Array; shore: Float32Array;
  riverDistance: Float32Array; seeds: number[];
};

export function buildWaterField(width: number, height: number, alpha: Uint8ClampedArray, paths: ScreenPoint[][], cell = 5): WaterField {
  const columns = Math.ceil(width / cell), rows = Math.ceil(height / cell), count = columns * rows;
  const wet = new Float32Array(count), vx = new Float32Array(count), vy = new Float32Array(count);
  const shore = new Float32Array(count), riverDistance = new Float32Array(count), seeds: number[] = [];
  const segments: { ax: number; ay: number; dx: number; dy: number; norm: number; tx: number; ty: number }[] = [];
  for (const path of paths) for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i], dx = b.x - a.x, dy = b.y - a.y, norm = dx*dx + dy*dy;
    if (norm < .01) continue;
    const length = Math.sqrt(norm);
    segments.push({ ax: a.x, ay: a.y, dx, dy, norm, tx: dx/length, ty: dy/length });
  }
  for (let row = 0; row < rows; row++) for (let col = 0; col < columns; col++) {
    const index = row * columns + col, x = Math.min(width-1, (col+.5)*cell), y = Math.min(height-1, (row+.5)*cell);
    const pixel = (Math.floor(y) * width + Math.floor(x)) * 4;
    wet[index] = (alpha[pixel + 3] ?? 0) / 255;
    shore[index] = wet[index] > .1 ? 10000 : 0;
    if (wet[index] < .1) continue;
    const nearest = [{ d: Infinity, x: 0, y: 1 }, { d: Infinity, x: 0, y: 1 }, { d: Infinity, x: 0, y: 1 }];
    for (const segment of segments) {
      const t = Math.max(0, Math.min(1, ((x-segment.ax)*segment.dx + (y-segment.ay)*segment.dy) / segment.norm));
      const dx = x-segment.ax-t*segment.dx, dy = y-segment.ay-t*segment.dy, d = dx*dx+dy*dy;
      if (d >= nearest[2].d) continue;
      const position = d < nearest[0].d ? 0 : d < nearest[1].d ? 1 : 2;
      for (let j = 2; j > position; j--) nearest[j] = nearest[j-1];
      nearest[position] = { d, x: segment.tx, y: segment.ty };
    }
    let dx = 0, dy = 0;
    for (const item of nearest) {
      if (!Number.isFinite(item.d)) continue;
      const direction = item.x*nearest[0].x + item.y*nearest[0].y < 0 ? -1 : 1;
      const weight = 1 / (item.d + 30);
      dx += item.x * weight * direction; dy += item.y * weight * direction;
    }
    const norm = Math.hypot(dx, dy) || 1;
    vx[index] = dx/norm; vy[index] = dy/norm; riverDistance[index] = Number.isFinite(nearest[0].d) ? Math.sqrt(nearest[0].d) : 1e6;
    if (segments.length && wet[index] > .7) seeds.push(index);
  }
  // Chamfer distance to the dry bank, used only for opacity and artistic speed.
  for (let row = 0; row < rows; row++) for (let col = 0; col < columns; col++) {
    const i = row*columns+col;
    if (col === 0 || row === 0 || col === columns-1 || row === rows-1) shore[i] = Math.min(shore[i], cell);
    if (col) shore[i] = Math.min(shore[i], shore[i-1]+cell);
    if (row) shore[i] = Math.min(shore[i], shore[i-columns]+cell);
    if (row && col) shore[i] = Math.min(shore[i], shore[i-columns-1]+cell*Math.SQRT2);
    if (row && col < columns-1) shore[i] = Math.min(shore[i], shore[i-columns+1]+cell*Math.SQRT2);
  }
  for (let row = rows-1; row >= 0; row--) for (let col = columns-1; col >= 0; col--) {
    const i = row*columns+col;
    if (col < columns-1) shore[i] = Math.min(shore[i], shore[i+1]+cell);
    if (row < rows-1) shore[i] = Math.min(shore[i], shore[i+columns]+cell);
    if (row < rows-1 && col < columns-1) shore[i] = Math.min(shore[i], shore[i+columns+1]+cell*Math.SQRT2);
    if (row < rows-1 && col) shore[i] = Math.min(shore[i], shore[i+columns-1]+cell*Math.SQRT2);
  }
  return { width, height, cell, columns, rows, wet, vx, vy, shore, riverDistance, seeds };
}

export function sampleWaterField(field: WaterField, x: number, y: number) {
  if (x < 0 || y < 0 || x >= field.width || y >= field.height) return { wet: 0, vx: 0, vy: 0, shore: 0, distance: 0 };
  const fx = Math.max(0, Math.min(field.columns-1.00001, x/field.cell-.5));
  const fy = Math.max(0, Math.min(field.rows-1.00001, y/field.cell-.5));
  const col = Math.floor(fx), row = Math.floor(fy), dx = fx-col, dy = fy-row;
  const indices = [row*field.columns+col, row*field.columns+col+1, (row+1)*field.columns+col, (row+1)*field.columns+col+1];
  const weights = [(1-dx)*(1-dy), dx*(1-dy), (1-dx)*dy, dx*dy];
  let wet = 0, vx = 0, vy = 0, shore = 0, distance = 0;
  indices.forEach((index, i) => {
    const weight = weights[i] * (field.wet[index] ?? 0);
    wet += weight; vx += (field.vx[index] ?? 0)*weight; vy += (field.vy[index] ?? 0)*weight;
    shore += (field.shore[index] ?? 0)*weight; distance += (field.riverDistance[index] ?? 0)*weight;
  });
  const norm = Math.hypot(vx, vy) || 1;
  return { wet, vx: vx/norm, vy: vy/norm, shore: shore/(wet||1), distance: distance/(wet||1) };
}
