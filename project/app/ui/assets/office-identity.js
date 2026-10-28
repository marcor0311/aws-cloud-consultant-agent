import * as THREE from 'three';

const materialCache=new Map();
export function shelfPrintMaterial(theme){
  const key=`shelf:${theme}`;if(materialCache.has(key))return materialCache.get(key);
  const canvas=document.createElement('canvas');canvas.width=384;canvas.height=288;const ctx=canvas.getContext('2d');
  if(theme==='engagement'){
    ctx.fillStyle='#bdc9c4';ctx.fillRect(0,0,384,288);ctx.fillStyle='#758c77';ctx.beginPath();ctx.moveTo(0,232);ctx.lineTo(109,67);ctx.lineTo(222,228);ctx.lineTo(301,116);ctx.lineTo(384,228);ctx.lineTo(384,288);ctx.lineTo(0,288);ctx.fill();
    ctx.fillStyle='#ddd6ba';ctx.beginPath();ctx.moveTo(122,288);ctx.lineTo(201,202);ctx.lineTo(220,202);ctx.lineTo(190,288);ctx.fill();
    ctx.strokeStyle='#586457';ctx.lineWidth=7;for(const x of [201,225]){ctx.beginPath();ctx.arc(x,188,6,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(x,195);ctx.lineTo(x-2,218);ctx.lineTo(x-8,231);ctx.moveTo(x-2,218);ctx.lineTo(x+8,229);ctx.stroke();}
  }else if(theme==='architecture'){
    ctx.fillStyle='#e4e7df';ctx.fillRect(0,0,384,288);ctx.strokeStyle='#66818d';ctx.lineWidth=5;ctx.strokeRect(55,45,275,198);ctx.strokeRect(55,45,112,113);ctx.strokeRect(217,45,113,113);ctx.strokeRect(217,205,113,38);ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(167,158);ctx.lineTo(167,243);ctx.moveTo(217,158);ctx.lineTo(217,205);ctx.stroke();
  }else{
    ctx.fillStyle='#e5e8e0';ctx.fillRect(0,0,384,288);ctx.strokeStyle='#65818a';ctx.lineWidth=4;
    for(const [x,y] of [[74,75],[264,75],[170,180]]){ctx.strokeRect(x,y,54,47);ctx.beginPath();ctx.moveTo(x+27,y+47);ctx.lineTo(x+27,y+70);ctx.lineTo(197,250);ctx.stroke();}
  }
  const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;
  const result=new THREE.MeshStandardMaterial({map,roughness:.9});materialCache.set(key,result);return result;
}
