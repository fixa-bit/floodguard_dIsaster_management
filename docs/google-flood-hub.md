# Google Flood Hub integration

The left navigation also has an **External maps > Google Flood Hub** link. It
opens the full official Flood Hub website in a new tab at the reference map view,
without requiring API access. Google currently sends `X-Frame-Options: DENY`,
so its website cannot be displayed inside this dashboard with an iframe.

The map's Google Flood Hub toggle displays river forecast gauges from the official
Google Flood Forecasting API. It uses the existing satellite basemap and renders
white-bordered circles: Extreme (dark red), Danger (red), Warning (orange),
Normal (green), and No data (gray). A gauge without a forecast stays gray.

## Connect live data

1. Request access at https://developers.google.com/flood-forecasting#api_access.
2. After approval, enable Flood Forecasting API in the approved Google Cloud project.
3. Set `GOOGLE_FLOOD_API_KEY` in the backend `.env` or service environment.
   Do not put the key in frontend environment variables or source control.
4. Restart the backend and enable Google Flood Hub under Map layers.

`GOOGLE_FLOOD_REGION_CODES=PK` fetches Pakistan. Set `PK,IN` to also include
India's gauges as in the reference screenshot. Coverage follows Google's API
results, not a locally fabricated gauge list. Only quality-verified gauges are
requested. This integration covers riverine markers; flash flood polygons and
forecast hydrographs are not included.

`GET /api/v1/gis/google-flood-hub` returns a GeoJSON point collection and metadata.
The backend follows pagination, combines gauge metadata with latest statuses,
and caches successful results for `GOOGLE_FLOOD_CACHE_SECONDS` (default 600).
The browser checks every minute while the layer is enabled.
Each marker shows its issued time and forecast interval. If a refresh fails,
previous results are marked stale. Without approved credentials, the layer shows
a connection notice and no markers. No simulated forecasts are substituted.

Data attribution: Google Flood Forecasting API, CC BY 4.0.
API reference: https://developers.google.com/flood-forecasting/rest.
