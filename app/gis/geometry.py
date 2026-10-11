from collections.abc import Iterable


Coordinate = tuple[float, float]


def iter_coordinates(coordinates) -> Iterable[Coordinate]:
    if coordinates and isinstance(coordinates[0], (int, float)):
        yield float(coordinates[0]), float(coordinates[1])
        return
    for item in coordinates:
        yield from iter_coordinates(item)


def geometry_bounds(geometry: dict) -> tuple[float, float, float, float]:
    points = list(iter_coordinates(geometry["coordinates"]))
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def representative_point(geometry: dict) -> Coordinate:
    west, south, east, north = geometry_bounds(geometry)
    midpoint = (west + east) / 2, (south + north) / 2
    if point_in_geometry(*midpoint, geometry):
        return midpoint

    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    candidates = []
    for polygon in polygons:
        latitudes = sorted({point[1] for point in polygon[0]})
        scanlines = [(south + north) / 2]
        scanlines.extend((lower + upper) / 2 for lower, upper in zip(latitudes, latitudes[1:]) if upper > lower)
        for latitude in scanlines:
            intersections = []
            ring = polygon[0]
            for index, start in enumerate(ring):
                end = ring[(index + 1) % len(ring)]
                if (start[1] <= latitude < end[1]) or (end[1] <= latitude < start[1]):
                    ratio = (latitude - start[1]) / (end[1] - start[1])
                    intersections.append(start[0] + ratio * (end[0] - start[0]))
            intersections.sort()
            for west_edge, east_edge in zip(intersections[::2], intersections[1::2]):
                candidate = ((west_edge + east_edge) / 2, latitude)
                if point_in_geometry(*candidate, geometry):
                    candidates.append((east_edge - west_edge, candidate))

    if not candidates:
        raise ValueError("Cannot find an interior point for the supplied district geometry")
    return max(candidates, key=lambda item: item[0])[1]


def bounds_intersect(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] < right[0]
        or left[0] > right[2]
        or left[3] < right[1]
        or left[1] > right[3]
    )


def point_in_geometry(longitude: float, latitude: float, geometry: dict) -> bool:
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return any(_point_in_polygon(longitude, latitude, polygon) for polygon in polygons)


def _point_in_polygon(longitude: float, latitude: float, polygon: list) -> bool:
    if not polygon or not _point_in_ring(longitude, latitude, polygon[0]):
        return False
    return not any(_point_in_ring(longitude, latitude, hole) for hole in polygon[1:])


def _point_in_ring(longitude: float, latitude: float, ring: list) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > latitude) != (y2 > latitude):
            crossing_x = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing_x:
                inside = not inside
        previous = current
    return inside

