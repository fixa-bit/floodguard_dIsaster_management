import { CloudRain, Droplets, Gauge, Thermometer, Waves, Wind } from "lucide-react";

import type { RiverResponse, WeatherResponse } from "../types/api";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

function value(number: number | null | undefined, suffix: string, digits = 1) {
  return number === null || number === undefined ? "Unavailable" : `${number.toFixed(digits)} ${suffix}`;
}

export function EnvironmentalPanel({ weather, river }: { weather: WeatherResponse | null; river: RiverResponse | null }) {
  const observedLevel = river?.observed_level_value != null
    ? `${river.observed_level_value.toFixed(2)} ${river.observed_level_unit ?? ""}`.trim()
    : value(river?.river_level_m, "m", 2);

  return (
    <Panel title="Environmental Conditions" icon={CloudRain} action={river ? <StatusBadge value={river.status} subtle /> : undefined}>
      {!weather && !river ? <div className="empty-state">Environmental data is unavailable.</div> : (
        <>
          <div className="metric-grid">
            <div><CloudRain /><span>Rainfall / 24h</span><strong>{value(weather?.rainfall_last_24h_mm, "mm")}</strong><small>Current {value(weather?.rainfall_current_mm, "mm")}</small></div>
            <div><Wind /><span>Forecast / 24h</span><strong>{value(weather?.forecast_rainfall_next_24h_mm, "mm")}</strong><small>Next 6h {value(weather?.forecast_rainfall_next_6h_mm, "mm")}</small></div>
            <div><Thermometer /><span>Temperature</span><strong>{value(weather?.temperature_c, "C")}</strong><small>Humidity {value(weather?.humidity_percent, "%", 0)}</small></div>
            <div><Droplets /><span>Soil moisture</span><strong>{value(weather?.soil_moisture_percent, "%")}</strong><small>Surface layer 0-7 cm</small></div>
            <div><Waves /><span>River discharge</span><strong>{value(river?.discharge_cumecs, "m3/s", 2)}</strong><small>Next day {value(river?.forecast_discharge_next_24h_cumecs, "m3/s", 2)}</small></div>
            <div><Gauge /><span>Observed level</span><strong>{observedLevel}</strong><small>{river?.official_recording_time ?? river?.river_name ?? "River unavailable"}</small></div>
          </div>
          {river && river.river_level_m === null && (
            <div className="data-notice"><Gauge size={17} /><div><strong>Observed level is not published for this station.</strong><span>{river.data_note ?? `Source: ${river.station_name}`}</span></div></div>
          )}
        </>
      )}
    </Panel>
  );
}
