# Portal guided tour

## Purpose

Give users a guided, in-place introduction to the existing FloodGuard portal without replacing or disabling its controls.

## Tour behavior

- The **Portal tour** action is available from the top bar.
- The portal remains visible and interactive while a compact guide stays in the lower corner.
- The guide panel is slightly translucent and can be dragged by its header or repositioned with arrow keys when that handle is focused.
- Tour steps navigate to real portal views and sub-tabs, scroll to the relevant control, and highlight it. The Operational Overview step stays unhighlighted.
- The map-layer walkthrough opens the Overview map's existing layer panel only when collapsed, then highlights each static, priority-monitoring, operational, and rainfall checkbox individually. It never changes a layer setting automatically.
- Simulation steps expose the live flood-spread, district-replay, and Jhang terrain layer controls.
- Location and station dropdown steps provide an action that opens the real native selector, preserving browser user-activation requirements.
- Escape closes the tour; arrow keys and the Back/Next buttons move between steps.
- Google Flood Hub remains an external link and opens in a separate tab.

## Scope and limits

The tour only navigates and reveals existing controls. It does not enable or disable data layers on the user's behalf, modify saved records, or present simulation layers as operational flood forecasts. Users can operate visible map layers while the tour is open.
