# Upstream station location map

## Purpose

Use the empty side of the bottom station-information panel to show where the selected upstream station is located.

## Strategy

- The frontend reads the station latitude and longitude already returned by the upstream forecast API.
- It embeds an interactive Google Maps view centered on those coordinates with a red location marker.
- Selecting another station changes the map URL and marker automatically.
- The map supports Google Maps zoom and full-screen controls.
- An **Open map** link opens the same coordinates in a larger Google Maps view.
- The iframe is lazy-loaded so the external map is requested only when the user scrolls near the location panel.
- The full coordinate precision is displayed below the map.

## Layout

On desktop, station facts occupy the left side and the map occupies the larger right side. At narrower web viewport widths, the two panels stack into one column. This is responsive web behavior and does not require Flutter or mobile tooling.

## Verification

The browser check selects Besham, Danyor, Marala, and Jassar and confirms that each iframe URL contains that station's saved coordinates. It also checks that the rendered map is at least 500 pixels wide and 250 pixels high in the desktop view and that the Google Maps frame loads after scrolling into view.
