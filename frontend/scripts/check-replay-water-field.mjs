import assert from "node:assert/strict";
import { buildWaterField, sampleWaterField } from "../src/components/replayWaterField.ts";

function mask(width, height, contains) {
  const data = new Uint8ClampedArray(width*height*4);
  for (let y=0; y<height; y++) for(let x=0; x<width; x++) if(contains(x,y)) data[(y*width+x)*4+3]=255;
  return data;
}
const channel = mask(120,120,(x,y)=>x>=30 && x<90 && y>0 && y<119);
const field = buildWaterField(120,120,channel,[[{x:60,y:0},{x:60,y:120}]],4);
assert(sampleWaterField(field,60,60).vy>.99, "Straight-channel field follows the supplied river direction");
assert.equal(sampleWaterField(field,10,60).wet,0,"Dry land has no artistic flow");
assert(sampleWaterField(field,60,60).shore>sampleWaterField(field,34,60).shore,"Bank distance supports a soft transition into water");
assert.equal(sampleWaterField(field,-1,20).wet,0);
const full = mask(120,120,()=>true);
const bend = buildWaterField(120,120,full,[[{x:0,y:50},{x:60,y:50},{x:60,y:120}]],4);
assert(sampleWaterField(bend,15,50).vx>.9,"Flow follows the approach to a bend");
assert(sampleWaterField(bend,60,105).vy>.9,"Flow follows the exit of a bend");
const hole = buildWaterField(120,120,mask(120,120,(x,y)=>!(x>=40&&x<80&&y>=40&&y<80)),[[{x:10,y:0},{x:10,y:120}]],4);
assert.equal(sampleWaterField(hole,60,60).wet,0,"Polygon holes do not seed or advect currents");
assert(!hole.seeds.some(i=>i%hole.columns>=10&&i%hole.columns<20&&Math.floor(i/hole.columns)>=10&&Math.floor(i/hole.columns)<20));
const empty = buildWaterField(30,30,mask(30,30,()=>false),[],4);
assert.equal(empty.seeds.length,0);
assert(Number.isFinite(sampleWaterField(empty,15,15).vx));
console.log("PASS: independent straight/bent channel direction, dry land and holes, bank softening, bounds, and empty-field behavior.");
