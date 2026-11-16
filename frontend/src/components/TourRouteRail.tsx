import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import "../tour-route-rail.css";

export interface TourRailStation { id: string; name: string; catchmentId?: string; catchmentName?: string }

const expandedKey = "floodguard-tour-rail-expanded";
const readExpanded = () => { try { return localStorage.getItem(expandedKey) === "1"; } catch { return false; } };

/**
 * The monitoring tour's route, small, at the side of the map. Collapsed (the
 * default) it shows only the previous, current and next station; expanded,
 * every station in the order the tour visits them, grouped under their
 * catchments, the current one largest and its two neighbours either side a
 * little larger than the rest. Stations already seen are filled in, the current
 * one glows (a pulsing ring while the camera is still flying to it), and the
 * current catchment's name lights up while its establishing shot is on screen.
 * Only the heading takes the pointer (to expand or collapse), so the map
 * underneath stays draggable.
 */
export function TourRouteRail({ stations, currentId, arrived, showingCatchment }: {
  stations: TourRailStation[]; currentId: string | null; arrived: boolean; showingCatchment: boolean;
}) {
  const [expanded, setExpanded] = useState(readExpanded);
  const toggle = () => setExpanded((open) => {
    try { localStorage.setItem(expandedKey, open ? "0" : "1"); } catch { /* storage blocked: the choice lasts this session */ }
    return !open;
  });
  const listRef = useRef<HTMLOListElement>(null);
  const count = stations.length;
  const currentIndex = stations.findIndex((station) => station.id === currentId);
  // Consecutive stations of one catchment form a group (the tour visits them together).
  const groups = useMemo(() => stations.reduce<Array<{ key: string; name?: string; stations: Array<TourRailStation & { index: number }> }>>((all, station, index) => {
    const last = all.at(-1);
    if (last && station.catchmentId && last.key.startsWith(`${station.catchmentId}:`)) last.stations.push({ ...station, index });
    else all.push({ key: `${station.catchmentId ?? station.id}:${index}`, name: station.catchmentName, stations: [{ ...station, index }] });
    return all;
  }, []), [stations]);

  // Keep the current station in view when the expanded list is taller than the space.
  useEffect(() => {
    const list = listRef.current, row = list?.querySelector<HTMLElement>("[data-current]");
    if (!expanded || !list || !row || list.scrollHeight <= list.clientHeight) return;
    list.scrollTo({ top: Math.max(0, row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2), behavior: "smooth" });
  }, [currentId, expanded]);

  if (!count) return null;
  const state = (index: number) => currentIndex < 0 ? "upcoming" : index < currentIndex ? "done" : index === currentIndex ? (arrived ? "here" : "approaching") : "upcoming";
  // Steps from the current station along the tour, either way round the loop.
  const distance = (index: number) => {
    if (currentIndex < 0) return 9;
    const apart = Math.abs(index - currentIndex);
    return Math.min(apart, count - apart);
  };
  const stop = (station: TourRailStation & { index: number }, role?: "prev" | "next") => (
    <li key={`${station.id}-${role ?? ""}`} className="tour-route-stop" data-state={state(station.index)} data-near={Math.min(3, distance(station.index))}
      data-role={role} data-current={station.index === currentIndex || undefined} aria-current={station.index === currentIndex ? "location" : undefined}>
      <i aria-hidden="true" />
      <span>{station.name}</span>
    </li>
  );
  const nearby: Array<TourRailStation & { index: number; role?: "prev" | "next" }> = currentIndex < 0 ? stations.slice(0, 2).map((station, index) => ({ ...station, index })) : [
    { ...stations[(currentIndex - 1 + count) % count], index: (currentIndex - 1 + count) % count, role: "prev" as const },
    { ...stations[currentIndex], index: currentIndex, role: undefined },
    { ...stations[(currentIndex + 1) % count], index: (currentIndex + 1) % count, role: "next" as const },
  ];
  const currentCatchment = currentIndex >= 0 ? stations[currentIndex].catchmentName : undefined;

  return (
    <nav className="tour-route-rail" data-expanded={expanded || undefined} aria-label="Monitoring tour route">
      <button type="button" className="tour-route-heading" aria-expanded={expanded} onClick={toggle}
        title={expanded ? "Show only the stations around the current one" : "Show the whole tour route"}>
        <span>Tour route</span>
        {currentIndex >= 0 && <b>{currentIndex + 1}<small>/{count}</small></b>}
        {expanded ? <ChevronUp size={12} aria-hidden="true" /> : <ChevronDown size={12} aria-hidden="true" />}
      </button>
      {expanded ? (
        <ol ref={listRef}>
          {groups.map((group) => {
            const holdsCurrent = group.stations.some((station) => station.index === currentIndex);
            return (
              <li key={group.key} className="tour-route-group" data-active={holdsCurrent || undefined}
                data-reached={(currentIndex >= 0 && group.stations[0].index <= currentIndex) || undefined}>
                {group.name && <div className="tour-route-catchment" data-showing={(holdsCurrent && showingCatchment) || undefined}>{group.name}</div>}
                <ol>{group.stations.map((station) => stop(station))}</ol>
              </li>
            );
          })}
        </ol>
      ) : (
        <ol className="tour-route-nearby">
          {nearby.map((station) => [
            // The current station's catchment is named just above it.
            station.index === currentIndex && currentCatchment
              ? <li key="catchment" className="tour-route-catchment" data-showing={showingCatchment || undefined}>{currentCatchment}</li> : null,
            stop(station, station.role),
          ])}
        </ol>
      )}
    </nav>
  );
}
