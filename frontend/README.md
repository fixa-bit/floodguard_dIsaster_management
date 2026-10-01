# FloodGuard Authority Dashboard

React and TypeScript command dashboard for the existing FloodGuard AI FastAPI API.

## Setup

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The dashboard is available at `http://localhost:3000`. The backend should be
running at `http://127.0.0.1:8000` with this origin allowed by `CORS_ORIGINS`.

## Configuration

- `VITE_API_BASE_URL`: API root, defaults to `http://127.0.0.1:8000/api/v1`.
- `VITE_REFRESH_INTERVAL_MS`: dashboard polling period, defaults to `30000`.
- `VITE_MAP_STYLE_URL`: optional MapLibre style URL. When empty, the bundled
  OpenStreetMap raster configuration is used.

## Validation

```powershell
npm run build
npm run validate:ui
```

The UI validation expects both the backend and Vite development server to be
running. It checks national GIS rendering, live data loading, location
switching, simulation Start/Advance/Reset, desktop and mobile overflow, and
captures screenshots.

