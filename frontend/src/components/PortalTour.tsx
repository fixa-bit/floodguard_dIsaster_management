import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Compass, ExternalLink, X } from "lucide-react";
import type { ViewId } from "./AppShell";

type TourStep = {
  title: string;
  view?: ViewId;
  target?: string;
  activateTarget?: string;
  openOnly?: boolean;
  controlTarget?: string;
  description: string;
  highlights: string[];
  showControl?: string;
  link?: { label: string; href: string };
};

const floodHubUrl = "https://sites.research.google/floods/l/30.36468142775536/76.22165549983335/6.182499999999997";

const mapLayerTourItems = [
  ["Pakistan boundary", "boundary", "Static reference"],
  ["Glaciers & upstream drainage", "glaciers", "Static reference"],
  ["Boundary alignment test", "borderTest", "Static reference"],
  ["District names & boundaries", "districts", "Static reference"],
  ["Catchment areas", "catchments", "Static reference"],
  ["Rivers, lakes & dams", "water", "Static reference"],
  ["Risk locations", "stations", "Static reference"],
  ["Major barrages & headworks", "monitoring-barrages", "Priority monitoring point"],
  ["Upstream river stations", "monitoring-upstream", "Priority monitoring point"],
  ["Major dams & reservoirs", "monitoring-dams", "Priority monitoring point"],
  ["Confluence watch locations", "monitoring-confluences", "Priority monitoring point"],
  ["District screening", "risk", "Operational overlay"],
  ["River status & model forecasts", "waterForecasts", "Operational overlay"],
  ["River monitoring", "gauges", "Operational overlay"],
  ["Google Flood Hub", "floodHub", "Operational overlay"],
  ["Incidents", "incidents", "Operational overlay"],
  ["Citizen reports", "reports", "Operational overlay"],
  ["Response resources", "resources", "Operational overlay"],
  ["Rainfall heatmap", "rainfall", "Weather overlay"],
] as const;

const mapLayerTourSteps: TourStep[] = mapLayerTourItems.map(([label, id, category]) => ({
  title: `Map layer · ${label}`,
  view: "overview",
  target: `[data-tour-target='gis-layer-${id}']`,
  description: `${category}: use this real checkbox to show or hide ${label.toLowerCase()} on the Overview map. The tour only points it out; it leaves the layer setting unchanged.`,
  highlights: ["The highlight follows this individual option", "Layer visibility remains under your control"],
}));

const tourSteps: TourStep[] = [
  {
    title: "Welcome to FloodGuard AI",
    view: "overview",
    description: "This tour introduces the portal's main workspaces. Use Next to move between them, or close the tour whenever you want to explore on your own.",
    highlights: ["Operational monitoring and map views", "Risk screening and longer-range planning", "Alerts, incidents, reports, and simulation tools"],
  },
  {
    title: "Operational Overview",
    view: "overview",
    description: "The command overview brings the national map and current operational summary together for the selected area.",
    highlights: ["Review risk, river, weather, and response layers", "Select a location from the map or location control", "Use the summary panels and activity ticker for a quick status check"],
  },
  {
    title: "Open Overview map layers",
    view: "overview",
    target: "[data-tour-target='gis-map-layers-toggle']",
    openOnly: true,
    description: "Open the Overview map's real layer panel. The next stops point to each option individually without changing its current setting.",
    highlights: ["Use Next to move through the static, monitoring, and live overlay controls"],
  },
  ...mapLayerTourSteps,
  {
    title: "Choose an operational area",
    view: "overview",
    target: "[data-tour-target='tour-location-control']",
    controlTarget: "[data-tour-target='tour-location-select']",
    showControl: "Show location choices",
    description: "Open the portal's real location selector to see the areas available in this build.",
    highlights: ["Changing the area updates the operational map and summaries"],
  },
  {
    title: "GIS Operations",
    view: "gis",
    target: "[data-tour-target='page-title']",
    description: "Explore the operational map and turn individual information layers on or off to inspect geography and current conditions.",
    highlights: ["Inspect stations, incidents, reports, and response resources", "Use population analysis and map controls", "Select a station or district to see its available details"],
  },
  {
    title: "Rainfall Heatmap",
    view: "rainfall",
    target: "[data-tour-target='page-title']",
    description: "The rainfall view focuses the national map on observed and forecast rainfall context.",
    highlights: ["Choose a rainfall time window", "Read the map legend and source notes", "Compare rainfall with river and risk layers where available"],
  },
  {
    title: "Predictive Risk Views · Near-Term Screening",
    view: "predictive",
    target: "[data-tour-target='risk-near-term']",
    description: "Near-term screening groups the current dashboard signals into riverine, flash-flood, urban, seasonal, and upstream views.",
    highlights: ["Read each score with its scope and model notes", "Change the target on forecast graphs", "Open Inputs & model to see datasets, features, limitations, and future scope"],
  },
  {
    title: "Predictive Risk Views · 10-Year Outlook",
    view: "predictive",
    target: "[data-tour-target='risk-ten-year']",
    description: "The 10-Year Outlook is a planning prototype for comparing hypothetical future conditions. Its maps and scenarios are exploratory, not an operational forecast.",
    highlights: ["Compare lower and higher planning scenarios", "Use the year control to explore the illustrative outlook", "Review the assumptions and limitations shown in the outlook"],
  },
  {
    title: "Upstream Source Flood Watch",
    view: "upstream",
    target: "[data-tour-target='page-title']",
    description: "Follow selected upstream river locations and compare available discharge forecasts, model summaries, rainfall context, and recent trends.",
    highlights: ["Choose a watch location", "Compare GloFAS and GEOGloWS forecast series", "Check the source notes and data availability alongside the charts"],
  },
  {
    title: "River Monitoring",
    view: "monitoring",
    target: "[data-tour-target='page-title']",
    description: "Review river station readings and the status information available for monitored barrages, headworks, and other locations.",
    highlights: ["Filter or select a monitoring station", "Open station details and forecast history when available", "Treat source and update status as part of reading each value"],
  },
  {
    title: "Alerts",
    view: "alerts",
    target: "[data-tour-target='page-title']",
    description: "Review threshold alerts, including records created by the simulation workflow. Simulated records are labeled so they can be distinguished from operational alerts.",
    highlights: ["Check severity, station, source, and recorded time", "Review a simulated alert before approving it", "Approved alerts can be carried into incident management"],
  },
  {
    title: "Incident Management",
    view: "incidents",
    target: "[data-tour-target='page-title']",
    description: "Track active and historical incidents and open the relevant record for its available status and response details.",
    highlights: ["Review incident state and location", "Distinguish simulation-origin incidents where marked", "Use incident records to follow reviewed events"],
  },
  {
    title: "Citizen Reports",
    view: "reports",
    target: "[data-tour-target='page-title']",
    description: "Collect and review field observations submitted by citizens. Reports provide context and still require authority verification.",
    highlights: ["Review report location, description, and attached information", "Mark important reports or close reviewed items", "Use map context to compare reports with nearby operational data"],
  },
  {
    title: "System Activity",
    view: "activity",
    target: "[data-tour-target='page-title']",
    description: "The activity stream records notable monitoring changes, automated decisions, and response events available to the portal.",
    highlights: ["Scan recent events and timestamps", "Use the activity context to understand changes", "Return to Overview for the current command picture"],
  },
  {
    title: "Choose a monitoring station",
    view: "simulation",
    target: "[data-tour-target='tour-sim-station']",
    showControl: "Show station choices",
    description: "This opens the actual station dropdown used by the simulation form.",
    highlights: ["Station options depend on the monitoring data loaded for this portal"],
  },
  {
    title: "Simulation · Monitoring Scenario",
    view: "simulation",
    target: "[data-tour-target='simulation-monitoring']",
    description: "Create a test reading sequence for a station and play it against saved or custom thresholds. This workflow is marked as simulated.",
    highlights: ["Choose a station, measurement, unit, and time", "Use sliders and profiles to shape the test readings", "Threshold crossings create simulated alerts for review"],
  },
  {
    title: "Simulation · Flood Spread & Population",
    view: "simulation",
    target: "[data-tour-target='simulation-spread']",
    description: "Explore an illustrative flood-spread visualization and its estimated population context for a selected preview area.",
    highlights: ["Adjust the example flood level", "Compare baseline population and hypothetical spread", "These previews are not a calibrated hydraulic forecast"],
  },
  {
    title: "Flood spread map layers",
    view: "simulation",
    activateTarget: "[data-tour-target='simulation-spread']",
    target: "[data-tour-target='simulation-spread-layers']",
    description: "These are the working map-layer buttons for the flood-spread view. Click them to show or hide the example water footprint and population map.",
    highlights: ["The map updates directly when either layer is toggled"],
  },
  {
    title: "Simulation · Storm Replay",
    view: "simulation",
    target: "[data-tour-target='simulation-replay']",
    description: "Storm Replay keeps the original district example and the separate Jhang terrain study available as two modes.",
    highlights: ["The district replay retains the original hypothetical scenario", "The Jhang prototype uses terrain-connected sensitivity stages", "Use each mode's Inputs & Method notes to understand its limits"],
  },
  {
    title: "District Storm Replay",
    view: "simulation",
    target: "[data-tour-target='district-replay']",
    description: "The district replay presents its example storm scene and controls in a self-contained workspace.",
    highlights: ["Explore the replay controls and map", "Its scenario is illustrative", "The Jhang terrain prototype is available beside it"],
  },
  {
    title: "Storm replay map layers",
    view: "simulation",
    activateTarget: "[data-tour-target='district-replay']",
    target: "[data-tour-target='district-replay-layers']",
    description: "Try the actual Satellite, Population, Currents, and Terrain controls on the district replay map.",
    highlights: ["Terrain is available where local elevation data exists"],
  },
  {
    title: "Jhang Terrain Prototype",
    view: "simulation",
    target: "[data-tour-target='terrain-prototype']",
    description: "This small-area study shows a continuous assumed-rise control and progressively revealed connected terrain. It is a learning prototype, not a flood warning or hydraulic model.",
    highlights: ["Use Play spread or the 0–3 m slider", "Toggle terrain, population, and floodplain layers", "Mapped stream coverage is limited; read the on-screen assumptions"],
  },
  {
    title: "Jhang terrain map layers",
    view: "simulation",
    activateTarget: "[data-tour-target='terrain-prototype']",
    target: "[data-tour-target='jhang-terrain-layers']",
    description: "These real layer controls change the Jhang terrain view. Click Satellite, Terrain relief, Population, Floodplain spread, Connection paths, or Water animation to explore the map.",
    highlights: ["The floodplain layer is a terrain-guided prototype and remains clearly labeled as experimental"],
  },
  {
    title: "Google Flood Hub",
    view: "gis",
    target: "[data-tour-target='page-title']",
    description: "The sidebar also links to the external Google Flood Hub map. It opens separately, so you can return to FloodGuard without losing this tour.",
    highlights: ["Use the sidebar's External maps section", "External coverage and update timing are controlled by that service"],
    link: { label: "Open Google Flood Hub", href: floodHubUrl },
  },
];

export function PortalTour({ open, onClose, onNavigate }: {
  open: boolean;
  onClose: () => void;
  onNavigate: (view: ViewId) => void;
}) {
  const [index, setIndex] = useState(0);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const drag = useRef<{ pointerId: number; offsetX: number; offsetY: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.stopPropagation(); onClose(); }
      if (event.key === "ArrowRight" && !(event.target instanceof HTMLSelectElement)) { event.preventDefault(); setIndex((current) => Math.min(tourSteps.length - 1, current + 1)); }
      if (event.key === "ArrowLeft" && !(event.target instanceof HTMLSelectElement)) { event.preventDefault(); setIndex((current) => Math.max(0, current - 1)); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const active = tourSteps[index];
    if (active.view) onNavigate(active.view);
    if (active.activateTarget) document.querySelector<HTMLButtonElement>(active.activateTarget)?.click();
    window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    heading.current?.focus();
    if (!active.target) return;
    let attempts = 0;
    let highlighted: HTMLElement | null = null;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const showTarget = () => {
      const target = document.querySelector<HTMLElement>(active.target!);
      if (target) {
        highlighted = target;
        target.classList.add("portal-tour-focus");
        target.scrollIntoView({ block: "center", behavior: reducedMotion ? "auto" : "smooth" });
        target.focus({ preventScroll: true });
        if (target instanceof HTMLButtonElement && (!active.openOnly || target.getAttribute("aria-expanded") !== "true")) target.click();
        window.clearInterval(waitForTarget);
      } else if (++attempts >= 120) window.clearInterval(waitForTarget);
    };
    const waitForTarget = window.setInterval(showTarget, 100);
    showTarget();
    return () => {
      window.clearInterval(waitForTarget);
      highlighted?.classList.remove("portal-tour-focus");
    };
  }, [open, onNavigate, index]);

  if (!open) return null;
  const progress = ((index + 1) / tourSteps.length) * 100;
  const step = tourSteps[index];
  function goTo(next: number) {
    setIndex(next);
  }
  function showControl() {
    const target = step.controlTarget ? document.querySelector(step.controlTarget) : step.target ? document.querySelector(step.target) : null;
    if (!(target instanceof HTMLSelectElement)) return;
    target.focus({ preventScroll: true });
    try {
      if (typeof target.showPicker === "function") target.showPicker();
      else target.click();
    } catch {
      target.click();
    }
  }
  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as HTMLElement).closest("button, a, input, select")) return;
    const rect = dialog.current?.getBoundingClientRect();
    if (!rect) return;
    drag.current = { pointerId: event.pointerId, offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }
  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const rect = dialog.current?.getBoundingClientRect();
    if (!rect) return;
    const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
    const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
    setPosition({
      left: Math.max(8, Math.min(maxLeft, event.clientX - drag.current.offsetX)),
      top: Math.max(8, Math.min(maxTop, event.clientY - drag.current.offsetY)),
    });
  }
  function endDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }
  function moveWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>) {
    const deltas: Record<string, [number, number]> = { ArrowLeft: [-24, 0], ArrowRight: [24, 0], ArrowUp: [0, -24], ArrowDown: [0, 24] };
    const delta = deltas[event.key];
    if (!delta) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = dialog.current?.getBoundingClientRect();
    if (!rect) return;
    const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
    const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
    setPosition({
      left: Math.max(8, Math.min(maxLeft, rect.left + delta[0])),
      top: Math.max(8, Math.min(maxTop, rect.top + delta[1])),
    });
  }
  const dialogStyle: CSSProperties | undefined = position
    ? { left: position.left, top: position.top, right: "auto", bottom: "auto" }
    : undefined;

  return <div className="portal-tour-backdrop">
    <section ref={dialog} style={dialogStyle} className="portal-tour-dialog" role="region" aria-label="Portal tour" aria-labelledby="portal-tour-title" aria-describedby="portal-tour-description">
      <div className="portal-tour-topline portal-tour-drag-handle" role="group" aria-label="Move tour window; use arrow keys when focused" tabIndex={0} onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onKeyDown={moveWithKeyboard}><span><Compass size={16} /> FLOODGUARD PORTAL TOUR</span><button type="button" className="portal-tour-close" aria-label="Close portal tour" onClick={onClose}><X size={19} /></button></div>
      <div className="portal-tour-progress" role="progressbar" aria-label="Tour progress" aria-valuemin={1} aria-valuemax={tourSteps.length} aria-valuenow={index + 1}><i style={{ width: `${progress}%` }} /></div>
      <div className="portal-tour-count">STEP {String(index + 1).padStart(2, "0")} <span>OF {String(tourSteps.length).padStart(2, "0")}</span></div>
      <h2 id="portal-tour-title" ref={heading} tabIndex={-1}>{step.title}</h2>
      <p id="portal-tour-description">{step.description}</p>
      <ul>{step.highlights.map((item) => <li key={item}>{item}</li>)}</ul>
      {step.showControl && <button type="button" className="portal-tour-show-options" onClick={showControl}><ChevronDown size={15} />{step.showControl}</button>}
      {step.link && <a className="portal-tour-external" href={step.link.href} target="_blank" rel="noopener noreferrer">{step.link.label}<ExternalLink size={15} /></a>}
      <footer>
        <button type="button" className="portal-tour-skip" onClick={onClose}>Close tour</button>
        <div><button type="button" className="portal-tour-step" disabled={index === 0} onClick={() => goTo(index - 1)}><ChevronLeft size={16} /> Back</button><button type="button" className="portal-tour-next" onClick={() => index === tourSteps.length - 1 ? onClose() : goTo(index + 1)}>{index === tourSteps.length - 1 ? "Finish" : "Next"}{index < tourSteps.length - 1 && <ChevronRight size={16} />}</button></div>
      </footer>
    </section>
  </div>;
}
