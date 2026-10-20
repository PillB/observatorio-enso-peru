import fs from 'fs';
import {feature} from 'topojson-client';
const MIN=1.6; const K=5, LON0=110, LON1=300, LAT0=-25, LAT1=25;
function proj([lon,lat]){ let L=lon<0?lon+360:lon; return [ (L-LON0)*K, (LAT1-lat)*K ]; }
function ringPath(ring){
  // split rings crossing antimeridian badly: we use 0..360 so only Greenwich crossing matters (outside window)
  let d='', prev=null, out=[];
  for(const p of ring){ let q=proj(p); const W=(LON1-LON0)*K,H=(LAT1-LAT0)*K; q=[Math.max(-5,Math.min(W+5,q[0])),Math.max(-5,Math.min(H+5,q[1]))]; const l=out[out.length-1]; if(!l||Math.hypot(q[0]-l[0],q[1]-l[1])>MIN) out.push(q); } if(out.length<3) return '';
  // skip rings fully outside window
  const inside=out.some(([x,y])=>x>=-20&&x<=(LON1-LON0)*K+20&&y>=-20&&y<=(LAT1-LAT0)*K+20);
  if(!inside) return '';
  // detect jumps (wrap) and break path
  let s='';
  out.forEach((q,i)=>{ const j = i>0 && Math.abs(q[0]-out[i-1][0])>K*90; s+=(i===0||j?'M':'L')+q[0].toFixed(0)+' '+q[1].toFixed(0); });
  return s+'Z';
}
function geomPath(g){ const polys=g.type==='Polygon'?[g.coordinates]:g.coordinates; return polys.map(p=>p.map(ringPath).join('')).join(''); }
const land=JSON.parse(fs.readFileSync('node_modules/world-atlas/land-110m.json'));
const lf=feature(land, land.objects.land);
let d=lf.features.map(f=>geomPath(f.geometry)).join('');
// simplify: drop consecutive points closer than 0.8 units
d=d.replace(/L(-?[\d.]+) (-?[\d.]+)/g,(m)=>m);
const c=JSON.parse(fs.readFileSync('node_modules/world-atlas/countries-50m.json'));
const cf=feature(c,c.objects.countries);
const peru=cf.features.find(f=>f.id==='604'||f.properties.name==='Peru');
const pd=geomPath(peru.geometry);
fs.writeFileSync('pacific110.json', JSON.stringify({K,LON0,LON1,LAT0,LAT1,width:(LON1-LON0)*K,height:(LAT1-LAT0)*K,land:d,peru:pd}));
console.log(d.length, pd.length);
