import * as THREE from 'three';
import {MarchingCubes} from 'three/addons/objects/MarchingCubes.js';

// Rounded volume in every direction, with a single continuous skin.
const lobes=[
  [-.4,.12,0,.28,.25,.28],[-.2,.3,0,.3,.32,.3],
  [.15,.34,0,.31,.34,.31],[.42,.12,0,.29,.26,.29],
  [0,.05,0,.52,.23,.32]
];
function fieldAt(x,y,z){
  let distance=Infinity;
  for(const [cx,cy,cz,rx,ry,rz] of lobes){
    const next=(Math.hypot((x-cx)/rx,(y-cy)/ry,(z-cz)/rz)-1)*Math.min(rx,ry,rz);
    const h=Math.max(.09-Math.abs(distance-next),0)/.09;
    distance=Math.min(distance,next)-h*h*.09*.25;
  }
  return -distance;
}
function frontSurface(x,y){
  let inside=0,outside=.65;
  for(let i=0;i<24;i++){const middle=(inside+outside)/2;if(fieldAt(x,y,middle)>0)inside=middle;else outside=middle;}
  return (inside+outside)/2;
}
let cloudGeometry;
function makeVolume(material){
  if(!cloudGeometry){
    const resolution=56,volume=new MarchingCubes(resolution,material,false,false,24000);
    volume.isolation=0;
    for(let z=0;z<resolution;z++)for(let y=0;y<resolution;y++)for(let x=0;x<resolution;x++){
      volume.field[x+y*resolution+z*resolution*resolution]=fieldAt(x*2/resolution-1,y*2/resolution-1,z*2/resolution-1);
    }
    volume.update();
    cloudGeometry=new THREE.BufferGeometry();
    cloudGeometry.setAttribute('position',new THREE.BufferAttribute(volume.positionArray.slice(0,volume.count*3),3));
    cloudGeometry.setAttribute('normal',new THREE.BufferAttribute(volume.normalArray.slice(0,volume.count*3),3));
    cloudGeometry.computeBoundingBox();cloudGeometry.computeBoundingSphere();volume.geometry.dispose();
  }
  return new THREE.Mesh(cloudGeometry,material);
}
export function createCloudAgent(){
  const group=new THREE.Group();group.name='cloud-agent';group.scale.setScalar(.88);
  const body=new THREE.Group();group.add(body);
  const porcelain=new THREE.MeshStandardMaterial({color:0xeff3f1,roughness:.76,emissive:0xc1d2d0,emissiveIntensity:.035});
  const ink=new THREE.MeshStandardMaterial({color:0x46545a,roughness:.85});
  const volume=makeVolume(porcelain);volume.name='cloud-volume';body.add(volume);
  const eyes=[];
  for(const side of [-1,1]){
    const x=side*.18,y=.19,z=frontSurface(x,y);
    const eye=new THREE.Mesh(new THREE.SphereGeometry(1,20,14),ink);
    eye.name=side<0?'left-eye':'right-eye';eye.position.set(x,y,z+.004);eye.scale.set(.026,.038,.008);
    // The marks lie against the curved skin instead of projecting out as eyeballs.
    eye.rotation.y=side*.17;body.add(eye);eyes.push(eye);
  }
  const mouthPoints=[[-.055,.085],[0,.073],[.055,.085]].map(([x,y])=>new THREE.Vector3(x,y,frontSurface(x,y)+.006));
  const mouth=new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(mouthPoints),12,.005,6,false),ink);
  mouth.name='quiet-smile';body.add(mouth);
  const shadow=new THREE.Mesh(new THREE.CircleGeometry(.37,32),new THREE.MeshBasicMaterial({color:0x5b6661,transparent:true,opacity:.12,depthWrite:false}));
  shadow.name='cloud-contact-shadow';shadow.rotation.x=-Math.PI/2;
  function animate({walking=false,pose='stand',time=0,dt=1/60,immediate=false}={}){
    const smooth=(value,target)=>immediate?target:THREE.MathUtils.damp(value,target,7,dt);
    body.position.y=smooth(body.position.y,Math.sin(time*1.8)*(pose==='seated'?.004:.012));
    body.rotation.z=smooth(body.rotation.z,walking?Math.sin(time*2)*.012:0);
    body.scale.y=smooth(body.scale.y,(pose==='seated'?.96:1)+Math.sin(time*1.8)*.006);
    const t=time%6.4,blink=t>6.12&&t<6.32?Math.max(.12,Math.abs(t-6.22)/.1):1;
    eyes.forEach(eye=>eye.scale.y=.038*blink);
    shadow.position.set(group.position.x,.222,group.position.z);
    shadow.scale.setScalar(.98-Math.sin(time*1.8)*.015);
  }
  animate({immediate:true});
  return {group,shadow,animate,hoverHeight:.53};
}
