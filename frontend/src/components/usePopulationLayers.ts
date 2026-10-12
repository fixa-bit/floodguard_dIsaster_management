import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { Popup } from 'maplibre-gl';
import type { GeoJSONSource, Map, MapLayerMouseEvent } from 'maplibre-gl';
import type { PopulationOverlay } from '../services/population';
import { artifactUrl } from '../services/population';

const empty = {type:'FeatureCollection' as const,features:[]};
export function usePopulationLayers(mapRef: RefObject<Map | null>, overlay?: PopulationOverlay | null) {
  const fitted = useRef('');
  const loadedAnalysis = useRef<Record<string,string>>({});
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const popup = new Popup({ closeButton:true, maxWidth:'300px' });
    function update() {
      if (!map || !map.getLayer('background')) return;
      for (const name of ['population_grid','flood_extent','administrative_exposure','settlements']) {
        const id='population-'+name;
        const data=overlay ? artifactUrl(overlay.summary.layers[name]) : empty;
        const revision=overlay?.summary.analysis_id ?? '';
        if (!map.getSource(id)) map.addSource(id,{type:'geojson',data,
          attribution:name==='population_grid' ? 'Population: WorldPop / CC BY 4.0' : name==='settlements' ? 'Settlements: OpenStreetMap / ODbL' : 'Flood and administrative areas: see analysis provenance'});
        else if (loadedAnalysis.current[id] !== revision) (map.getSource(id) as GeoJSONSource).setData(data);
        loadedAnalysis.current[id]=revision;
        if (!map.getLayer(id)) {
          if (name==='settlements') map.addLayer({id,type:'circle',source:id,paint:{'circle-color':'#ff6dce','circle-radius':6,'circle-stroke-color':'#fff','circle-stroke-width':1}});
          else map.addLayer({id,type:'fill',source:id,paint:{'fill-color':name==='flood_extent' ? '#30b9ff' : name==='administrative_exposure' ? '#ffbf61' : ['interpolate',['linear'],['coalesce',['get','population_density_km2'],0],0,'#fff7b2',500,'#ffc658',2000,'#ed6d36',5000,'#c51b37'], 'fill-opacity':name==='flood_extent' ? .4 : name==='administrative_exposure' ? .08 : .65,'fill-outline-color':name==='administrative_exposure' ? '#fff' : 'rgba(0,0,0,0)'}});
        }
        map.setLayoutProperty(id,'visibility',overlay?.visible[name] ? 'visible' : 'none');
        if (name==='administrative_exposure') map.setFilter(id,['==',['get','level'],overlay?.adminLevel ?? 'ADM2']);
      }
      if (overlay && fitted.current !== overlay.summary.analysis_id) {
        fitted.current=overlay.summary.analysis_id;
        const [w,s,e,n]=overlay.summary.bounds;
        map.fitBounds([[w,s],[e,n]],{padding:70,duration:500,maxZoom:11});
      }
    }
    function click(event: MapLayerMouseEvent) {
      if (!overlay || !map) return;
      const ids=['population-settlements','population-administrative_exposure','population-population_grid'].filter(id=>map.getLayer(id));
      const feature=map.queryRenderedFeatures(event.point,{layers:ids})[0];
      if (!feature) return;
      const p=feature.properties;
      const format=(x: unknown)=>x==null?'Unknown':Number(x).toLocaleString(undefined,{maximumFractionDigits:1});
      const node=document.createElement('div'); node.className='population-map-popup';
      const title=document.createElement('strong'); title.textContent=String(p.name || 'Population display cell'); node.append(title);
      for (const text of [overlay.summary.flood.is_sample?'SYNTHETIC TEST':overlay.summary.flood.label,
        feature.layer.id==='population-settlements'?'Mapped settlement intersects flood extent':`Estimated exposed: ${format(p.estimated_exposed_population ?? p.exposed_population)}`,
        p.population_density_km2!=null?`Density: ${format(p.population_density_km2)} people/km²`:`Known population exposed: ${format(p.percentage_exposed_of_known_population)}%`,
        'Known cells only; missing population and OSM coverage remain limitations.']) { const line=document.createElement('p'); line.textContent=text; node.append(line); }
      popup.setLngLat(event.lngLat).setDOMContent(node).addTo(map);
    }
    function diagnostics() {
      if (!map || new URLSearchParams(window.location.search).get('mapDiagnostics') !== '1') return;
      const element=map.getContainer();
      element.dataset.populationAnalysis=overlay?.summary.analysis_id ?? '';
      for (const name of ['population_grid','flood_extent','administrative_exposure','settlements']) {
        const id='population-'+name;
        element.setAttribute('data-population-'+name.replaceAll('_','-'),String(map.getLayer(id) ? map.queryRenderedFeatures({layers:[id]}).length : 0));
      }
    }
    map.on('load',update); map.on('style.load',update); map.on('click',click); map.on('idle',diagnostics); update();
    return () => { map.off('load',update); map.off('style.load',update); map.off('click',click); map.off('idle',diagnostics); popup.remove(); };
  }, [mapRef,overlay]);
}
