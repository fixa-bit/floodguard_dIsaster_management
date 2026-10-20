import { createRoot } from "react-dom/client";

import App from "./App";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";
import "./portal-tour.css";

createRoot(document.getElementById("root")!).render(<App />);
