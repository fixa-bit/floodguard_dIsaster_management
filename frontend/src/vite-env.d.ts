/// <reference types="vite/client" />

declare module "*.geojson?compressed" {
  const url: string;
  export default url;
}
