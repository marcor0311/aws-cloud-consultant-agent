import * as THREE from 'three';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import {mergeVertices} from 'three/addons/utils/BufferGeometryUtils.js';

let backGeometry;
function sculptedBack(){
  if(backGeometry)return backGeometry;
  const w=.62,h=.51,r=.075,shape=new THREE.Shape();
  shape.moveTo(-w/2+r,0);shape.lineTo(w/2-r,0);shape.quadraticCurveTo(w/2,0,w/2,r);
  shape.lineTo(w/2,h-r);shape.quadraticCurveTo(w/2,h,w/2-r,h);
  shape.lineTo(-w/2+r,h);shape.quadraticCurveTo(-w/2,h,-w/2,h-r);
  shape.lineTo(-w/2,r);shape.quadraticCurveTo(-w/2,0,-w/2+r,0);
  const raw=new THREE.ExtrudeGeometry(shape,{depth:.03,bevelEnabled:true,bevelSize:.022,bevelThickness:.022,bevelSegments:4,curveSegments:14});
  const points=raw.attributes.position;
  for(let i=0;i<points.count;i++){
    const x=points.getX(i),y=points.getY(i);
    points.setXYZ(i,x*(1-.06*y/h),y+.47,points.getZ(i)-.245+x*x*.95-y*.17);
  }
  raw.deleteAttribute('normal');raw.deleteAttribute('uv');
  backGeometry=mergeVertices(raw,1e-5);backGeometry.computeVertexNormals();raw.dispose();return backGeometry;
}
export function createCommonsChair({oak,upholstery,frame}){
  const chair=new THREE.Group();chair.name='sculpted-upholstered-chair';
  const mesh=(geometry,mat,x=0,y=0,z=0)=>{const item=new THREE.Mesh(geometry,mat);item.position.set(x,y,z);item.castShadow=true;item.receiveShadow=true;chair.add(item);return item;};
  mesh(new RoundedBoxGeometry(.59,.045,.53,3,.025),oak,0,.405,0);
  mesh(new RoundedBoxGeometry(.62,.1,.57,4,.055),upholstery,0,.465,.025);
  const back=mesh(sculptedBack(),upholstery);back.name='curved-upholstered-back';
  for(const side of [-1,1]){
    mesh(new RoundedBoxGeometry(.055,.05,.32,3,.025),upholstery,side*.31,.67,-.015);
    mesh(new THREE.CylinderGeometry(.012,.014,.16,10),frame,side*.31,.565,-.09);
  }
  for(const x of [-1,1])for(const z of [-1,1]){
    const top=new THREE.Vector3(x*.21,.39,z*.16),bottom=new THREE.Vector3(x*.265,.022,z*.23),direction=top.clone().sub(bottom);
    const leg=mesh(new THREE.CylinderGeometry(.022,.027,direction.length(),12),oak);
    leg.position.copy(top).add(bottom).multiplyScalar(.5);leg.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),direction.normalize());
    mesh(new THREE.CylinderGeometry(.027,.027,.012,12),frame,bottom.x,.012,bottom.z);
  }
  return chair;
}

let loungeShellGeometry;
function loungeShell(){
  if(loungeShellGeometry)return loungeShellGeometry;
  const shape=new THREE.Shape(),start=THREE.MathUtils.degToRad(48),end=THREE.MathUtils.degToRad(312),steps=64;
  for(let i=0;i<=steps;i++){const a=start+(end-start)*i/steps,x=Math.sin(a)*.43,y=-Math.cos(a)*.43;if(i===0)shape.moveTo(x,y);else shape.lineTo(x,y);}
  for(let i=steps;i>=0;i--){const a=start+(end-start)*i/steps;shape.lineTo(Math.sin(a)*.315,-Math.cos(a)*.315);}
  shape.closePath();
  const raw=new THREE.ExtrudeGeometry(shape,{depth:1,steps:1,bevelEnabled:true,bevelSize:.025,bevelThickness:.018,bevelSegments:4});raw.rotateX(-Math.PI/2);
  const points=raw.attributes.position;
  for(let i=0;i<points.count;i++){
    const x=points.getX(i),z=points.getZ(i),radius=Math.hypot(x,z),rear=(1-z/Math.max(radius,.001))/2;
    points.setY(i,.2+points.getY(i)*(.25+.35*rear));
  }
  raw.deleteAttribute('normal');raw.deleteAttribute('uv');loungeShellGeometry=mergeVertices(raw,1e-5);loungeShellGeometry.computeVertexNormals();raw.dispose();return loungeShellGeometry;
}
export function createLoungeChair({oak,upholstery,frame}){
  const chair=new THREE.Group();chair.name='upholstered-lounge-chair';
  function add(geometry,mat,x=0,y=0,z=0){const mesh=new THREE.Mesh(geometry,mat);mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;chair.add(mesh);return mesh;}
  add(loungeShell(),upholstery);
  add(new RoundedBoxGeometry(.64,.06,.6,3,.035),oak,0,.25,0);
  add(new RoundedBoxGeometry(.7,.16,.68,4,.09),upholstery,0,.37,.025);
  for(const x of [-1,1])for(const z of [-1,1]){
    const a=new THREE.Vector3(x*.22,.24,z*.2),b=new THREE.Vector3(x*.28,.018,z*.26),d=a.clone().sub(b);
    const leg=add(new THREE.CylinderGeometry(.025,.03,d.length(),12),oak);leg.position.copy(a).add(b).multiplyScalar(.5);leg.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),d.normalize());
    add(new THREE.CylinderGeometry(.03,.03,.012,12),frame,b.x,.012,b.z);
  }
  return chair;
}
