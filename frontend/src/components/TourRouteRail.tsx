import { useEffect, useMemo, useRef } from "react";
import "../tour-route-rail.css";

export interface TourRailStation { id: string; name: string; catchmentId?: string; catchmentName?: string }

/**
 * The monitoring tour's route, small, at the side of the map: every station in
 * the order the tour visits them, on one line, grouped under their catchments.
 * Stations already seen are filled in, the current one glows (a pulsing ring
 * while the camera is still flying to it), and the current catchment's name
 * lights up while its establishing shot is on screen. Purely informative: it
 * never takes the pointer, so the map underneath stays draggable.
 */
export function TourRouteRail({ stations, currentId, arrived, showingCatchment }: {
  stations: TourRailStation[]; currentId: string | null; arrived: boolean; showingCatchment: boolean;
}) {
  const listRef = useRef<HTMLOListElement>(null);
  const currentIndex = stations.findIndex((station) => station.id === currentId);
  // Consecutive stations of one catchment form a group (the tour visits them together).
  const groups = useMemo(() => stations.reduce<Array<{ key: string; name?: string; stations: Array<TourRailStation & { index: number }> }>>((all, station, index) => {
    const last = all.at(-1);
    if (last && station.catchmentId && last.key.startsWith(`${station.catchmentId}:`)) last.stations.push({ ...station, index });
    else all.push({ key: `${station.catchmentId ?? station.id}:${index}`, name: station.catchmentName, stations: [{ ...station, index }] });
    return all;
  }, []), [stations]);

  // Keep the current station in view when the list is taller than the space.
  useEffect(() => {
    const list = listRef.current, row = list?.querySelector<HTMLElement>("[data-current]");
    if (!list || !row || list.scrollHeight <= list.clientHeight) return;
    list.scrollTo({ top: Math.max(0, row.offsetTop - list.clientHeight / 2 + row.offsetHeight / 2), behavior: "smooth" });
  }, [currentId]);

  if (!stations.length) return null;
  return (
    <nav className="tour-route-rail" aria-label="Monitoring tour route">
      <header>
        <span>Tour route</span>
        {currentIndex >= 0 && <b>{currentIndex + 1}<small>/{stations.length}</small></b>}
      </header>
      <ol ref={listRef}>
        {groups.map((group) => {
          const holdsCurrent = group.stations.some((station) => station.index === currentIndex);
          return (
            <li key={group.key} className="tour-route-group" data-active={holdsCurrent || undefined}
              data-reached={(currentIndex >= 0 && group.stations[0].index <= currentIndex) || undefined}>
              {group.name && <div className="tour-route-catchment" data-showing={(holdsCurrent && showingCatchment) || undefined}>{group.name}</div>}
              <ol>
                {group.stations.map((station) => {
                  const state = currentIndex < 0 ? "upcoming" : station.index < currentIndex ? "done" : station.index === currentIndex ? (arrived ? "here" : "approaching") : "upcoming";
                  return (
                    <li key={station.id} className="tour-route-stop" data-state={state} data-current={station.index === currentIndex || undefined}
                      aria-current={station.index === currentIndex ? "location" : undefined}>
                      <i aria-hidden="true" />
                      <span>{station.name}</span>
                    </li>
                  );
                })}
              </ol>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
