export function mapTestUrl(url) {
  const target = new URL(url);
  target.searchParams.set("mapDiagnostics", "1");
  return target.href;
}
