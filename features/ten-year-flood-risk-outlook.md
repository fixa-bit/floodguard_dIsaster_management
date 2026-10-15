# Ten-year flood-risk outlook

## International research

Research date: 14 October 2026

Official systems in developed countries consistently separate live flood warnings from long-range flood-risk planning. They present future conditions as scenarios or projections with uncertainty, rather than as an exact weather or discharge forecast for each future year.

| System | How future flood risk is presented | Design lesson for FloodGuard |
| --- | --- | --- |
| England: Environment Agency national assessment and climate-change allowances | Current and future risk are assessed together, but planning allowances are selected by catchment, time epoch, event probability, and percentile. The central, higher-central, and upper-end allowances correspond to the 50th, 70th, and 95th percentiles. | Let users select a basin, time horizon, and scenario. Show an uncertainty range and keep the result in a planning view rather than the alert workflow. |
| United States: FEMA Risk MAP and NOAA climate-resilience mapping | FEMA describes future-condition products as scenario-based, probabilistic, and non-regulatory. Inputs can include precipitation, sea-level rise, land-use change, dams, levees, and mitigation works. NOAA's mapping tool lets users explore present and future exposure to flooding and other hazards. | Clearly label the outlook as planning guidance. Show the assumptions behind each scenario and compare current with future exposure. |
| Netherlands: Climate Impact Atlas | A zoomable national map is combined with layers for impacts, vulnerability, adaptation opportunities, monitoring, and area characteristics. Available flood layers can switch among current, 2050-low, 2050-high, and 2100 views. The site warns that national maps are indicative at local scale. | Use a map-first comparison with scenario/year controls and a visible geographic-resolution limitation. Add adaptation context later instead of displaying risk alone. |
| Canada: federal flood mapping and future susceptibility maps | Canada combines authoritative flood mapping guidance with future susceptibility maps. Its current future dataset uses temperature and precipitation with an XGBoost model for 2050, 2070, and 2100 under SSP2-4.5 and SSP5-8.5, and explicitly calls the results indicators rather than precise forecasts. | A simple ML model is acceptable for an early screening version if inputs, scenario, time horizon, and limitations are explicit. Keep hazard/susceptibility separate from estimated consequences. |
| Australia: Climate Change in Australia and AFRIP | Climate tools separate basic, intermediate, and advanced views. Users compare time periods, emissions scenarios, regions, variables, and multiple models. The flood portal catalogs standardized historical studies, modeled scenarios, and map metadata. | Start with a simple summary, with methodology and advanced controls available on demand. Retain provenance for every dataset and model result. |
| European Union: Climate-ADAPT flood-risk viewer | A Europe-wide viewer provides a high-level flood-risk map using points, lines, and polygons, then links users to detailed national sources. | Provide a national overview that drills down to province, district, basin, and station corridor instead of presenting one resolution as equally reliable everywhere. |

### Sources

- [Environment Agency: National assessment of flood and coastal erosion risk in England 2024](https://www.gov.uk/government/publications/national-assessment-of-flood-and-coastal-erosion-risk-in-england-2024)
- [Environment Agency: Flood-risk assessment climate-change allowances](https://www.gov.uk/guidance/flood-risk-assessments-climate-change-allowances)
- [FEMA: Risk MAP Multi-Year Plan 2023-2027](https://www.fema.gov/sites/default/files/documents/fema_fi-riskmap-multiyear-plan-v1.2.pdf)
- [NOAA: Climate Mapping for Resilience and Adaptation Assessment Tool](https://www.coast.noaa.gov/digitalcoast/tools/cmra.html)
- [Netherlands Climate Impact Atlas](https://www.klimaateffectatlas.nl/en/)
- [Netherlands Climate Impact Atlas FAQ](https://www.klimaateffectatlas.nl/en/faq)
- [Natural Resources Canada: Future Flood Susceptibility Mapping](https://open.canada.ca/data/en/dataset/c00f95a3-7bab-4d28-b9cc-b30f06b5afd2)
- [Natural Resources Canada: Federal Flood Mapping Guidelines](https://natural-resources.canada.ca/science-data/science-research/natural-hazards/federal-flood-mapping-guidelines)
- [Australia: Climate projection tools](https://www.climatechangeinaustralia.gov.au/en/projections-tools/)
- [Geoscience Australia: Australian Flood Risk Information Portal](https://www.ga.gov.au/scientific-topics/community-safety/data-and-products/afrip)
- [European Climate-ADAPT: Flood risk areas viewer](https://climate-adapt.eea.europa.eu/en/navigator/tool-catalogue/flood-risk-areas-viewer)

## Staged implementation and approvals

The user subsequently authorized a **hypothetical** maps/chart/summary and Inputs & Method implementation in the existing sub-tab. That preview includes demonstration selectors and deterministic example logic, without starting the validated model/data service. See [hypothetical maps and charts](ten-year-hypothetical-maps-and-charts.md) and [Inputs & Method](ten-year-outlook-inputs-and-method.md). Production-model and scenario-data work remain separate future tasks.

The user then requested more dynamic visuals. [Animated exploration](ten-year-outlook-motion-and-map-tour.md) adds a play/pause timeline, moving graph trace, map tour, and motion controls to the same hypothetical sub-tab.

Requested workflow: complete one approved task at a time, report the result and verification, and wait for explicit approval before starting the next task. Tasks 1 and 2 are complete. The user requested the dataset audit and listed the next implementation stages; under the staged workflow, projection-method implementation awaits approval after the audit findings.

| Task | Deliverable | Status |
| --- | --- | --- |
| 1. Sub-tab foundation | Add Near-Term Screening and 10-Year Outlook inside Predictive Risk Views. Create the outlook component with introductory planning text and an honest state showing that projections are not yet available. Verify switching and the existing near-term view. | Complete; see [navigation implementation](ten-year-outlook-navigation.md) |
| 2. Data readiness and historical baseline | Audit the available Pakistan flood-event, rainfall, and geographic datasets. Document coverage, missing years, district matching, feature definitions, and what can support a historical baseline. Missing flood records must not automatically be treated as flood-free observations. | Complete; see [dataset audit](ten-year-dataset-audit.md) |
| 3. Projection method and data service | Implement the modest method supported by Task 2, with documented baseline, scenario assumptions, output definition, and uncertainty. Use time-based historical validation. Climate scenarios require sourced future inputs; synthetic or sensitivity examples must be labeled explicitly and never presented as calibrated flood probabilities. Report any data constraint before finalizing the method. | Awaiting approval after audit |
| 4. Outlook selectors | Connect geography, available hazard, scenario, and planning-year controls to supported data. Disable or explain unavailable combinations. | Hypothetical selectors implemented; real-data controls pending |
| 5. Maps and charts | Add current-versus-future comparison, zoomable geography, planning checkpoints, uncertainty bands, and change summaries using the approved data service. | Hypothetical preview implemented; validated projections pending |
| 6. Inputs and methodology | Add an expandable panel listing datasets, selected and engineered features, model, outputs, baseline, versions, limitations, international inspiration, and future scope. | Implemented for the preview, with actual inputs distinguished from future datasets |
| 7. Final web verification | Check selectors, tab switching, map/chart consistency, missing-data states, reload behavior, and isolation from operational alerts and incidents. Run the relevant build and behavior checks. | Preview build, fixture checks, browser interactions, map cleanup, failure/retry, and no-write checks passed; real-data pipeline verification pending |

Update this document after each completed task. Any additional independent feature or strategy should receive its own Markdown file in `features`, linked here. Advanced hydrological models, detailed infrastructure exposure, and adaptation simulations remain future scope until their data and validation are available.

## Recommended location

Place this feature inside **Predictive Risk Views** as a second page mode in the toolbar:

```text
Predictive Risk Views
[ Near-term screening ] [ 10-Year Outlook ]
```

The existing five predictive cards remain under **Near-term screening**. Selecting **10-Year Outlook** replaces that card grid with a planning view. A separate main-sidebar item is unnecessary initially because this is another risk horizon within the same predictive function.

Do not place the feature in River Monitoring, Upstream Source Flood Watch, Alerts, or Incidents. Those areas are for observed conditions, days-ahead forecasts, and operational events. A ten-year result should not create an automatic emergency alert.

## Product wording

Use **10-Year Flood-Risk Outlook** or **Scenario Projection**. Exact rainfall and river discharge cannot be forecast ten years ahead. The feature should estimate how flood likelihood, susceptibility, or exposure may change under stated assumptions.

Every result should show:

- projection period, such as 2027-2036;
- baseline period;
- selected climate or planning scenario;
- geographic target;
- uncertainty range;
- data and model version;
- issue date;
- a **Planning projection - not an operational warning** label.

## Proposed layout

### Controls

- Geography: Pakistan, province, district, basin, or configured station corridor.
- Hazard: riverine, flash flood, or urban flooding.
- Scenario: baseline/current conditions, moderate change, and high change.
- Metric: flood probability, expected affected area, or normalized risk score.

### Main content

1. **Current versus future map** - projected risk category by district or basin for the selected scenario and planning year.
2. **Ten-year outlook chart** - a central estimate with a broad uncertainty band. Use yearly points only if the data supports them; otherwise use planning checkpoints such as 2027, 2030, 2033, and 2036.
3. **Change summary** - projected change from the baseline and the locations with the largest increase.
4. **Main drivers** - rainfall trend, historical flood frequency, terrain, land cover, drainage, population exposure, and river-flow indicators actually available to the model.
5. **Inputs & method** - reuse the existing predictive-input dialog pattern, but give the long-range model its own dataset, features, scenario, and version list.
6. **Limitations** - state map resolution, unavailable local factors, uncertainty, and intended planning use.

## Minimum credible first version

The completed [dataset audit](ten-year-dataset-audit.md) supersedes the provisional model suggestions below: existing historical model artifacts failed validation, labels are sampled reports, and future climate inputs are not yet prepared. The first model should therefore expose supported climate-pressure indicators and historical reporting context unless additional labels permit calibrated flood-risk estimates. Real sourced future inputs are required for scenario results.

Keep the first version modest:

- Target district-level or basin-level flood susceptibility/risk over the ten-year period, not exact future discharge on a date.
- Use historical flood events already prepared from DesInventar.
- Add annual or seasonal rainfall summaries and static geographic features already available in the project.
- Use a simple interpretable baseline such as logistic regression or the existing small XGBoost classification workflow.
- Compare a historical/current baseline with moderate-change and high-change planning scenarios.
- Produce planning checkpoints with a wide uncertainty band; add annual values only after they can be validated.
- Label the result as an experimental planning outlook.

Do not fabricate ten future years by extending the current five-day GloFAS line. GloFAS operational forecasts and FFD observations belong to short-range monitoring and are not ten-year climate projections.

## Future scope

After the first version is validated, add downscaled CMIP6 climate scenarios, land-use and population projections, hydrological routing, reservoir-operation assumptions, calibrated probability estimates, exposure and infrastructure layers, adaptation alternatives, and comparison across multiple models. Those additions should remain future scope until the required datasets are present and validated.

## Product decision from the research

Implement this as a second sub-tab inside **Predictive Risk Views**. The international examples support separating operational warnings from future planning while still keeping both under one risk-information product.

The first release should use a progressive layout:

1. A simple summary with current versus future risk, map, scenario, and uncertainty.
2. An expandable **Inputs & method** panel for datasets, features, model, output definition, and limitations.
3. Advanced scenario and model comparison controls only when multiple validated projections exist.

The ten-year result must not generate alerts or incidents. Alerts should continue to come only from observed data, operational forecasts, or explicit simulation tests.

## Navigation implementation point

The mode selector should be added to the toolbar in `frontend/src/components/FloodRiskMultiView.tsx`. The current `predictive` route and sidebar item can remain unchanged. A separate component such as `TenYearRiskOutlook.tsx` should own the long-range controls, charts, map, and methodology panel so short-range and long-range logic remain separate.
