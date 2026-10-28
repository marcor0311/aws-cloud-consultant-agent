import * as THREE from 'three';

const noise=i=>{const v=Math.sin(i*127.1+311.7)*43758.5453;return v-Math.floor(v);};
const v=(x,y,z)=>new THREE.Vector3(x,y-.7,z);

function barkTexture(){
  const canvas=document.createElement('canvas');canvas.width=128;canvas.height=512;
  const ctx=canvas.getContext('2d');ctx.fillStyle='#998f7c';ctx.fillRect(0,0,128,512);
  for(let i=0;i<150;i++){
    const x=noise(i)*128,y=noise(i+500)*512;
    ctx.strokeStyle=i%3?'rgba(68,57,41,.1)':'rgba(222,210,179,.22)';ctx.lineWidth=.4+noise(i+30)*1.2;
    ctx.beginPath();ctx.moveTo(x,y);ctx.bezierCurveTo(x+3,y+28,x-2,y+60,x+noise(i+80)*4-2,y+36+noise(i+100)*100);ctx.stroke();
  }
  const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;map.wrapS=map.wrapT=THREE.RepeatWrapping;map.anisotropy=4;return map;
}
function leafTexture(){
  const canvas=document.createElement('canvas');canvas.width=128;canvas.height=256;
  const ctx=canvas.getContext('2d');ctx.fillStyle='#e1e7ce';ctx.fillRect(0,0,128,256);
  ctx.strokeStyle='#91a16c55';ctx.lineWidth=1.2;ctx.beginPath();ctx.moveTo(64,256);ctx.quadraticCurveTo(60,120,64,0);ctx.stroke();
  for(let i=1;i<9;i++)for(const side of [-1,1]){
    const y=i*27;ctx.strokeStyle='#84965c28';ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(64,y);ctx.quadraticCurveTo(64+side*23,y-8,64+side*58,y-25);ctx.stroke();
  }
  const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;map.anisotropy=4;return map;
}
function leafGeometry(){
  const rows=12,cols=6,positions=[],uv=[],indices=[];
  for(let row=0;row<=rows;row++){
    const t=row/rows,width=.082*Math.sqrt(Math.max(0,1-Math.pow(t*2-1,2)));
    for(let col=0;col<=cols;col++){
      const s=col/cols*2-1;
      positions.push(s*width,t*.205,.016*Math.sin(Math.PI*t)*(1-.3*s*s)-.01*t*t);
      uv.push(col/cols,t);
    }
  }
  for(let row=0;row<rows;row++)for(let col=0;col<cols;col++){
    const a=row*(cols+1)+col,b=a+cols+1;indices.push(a,b,a+1,b,b+1,a+1);
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geometry.setIndex(indices);geometry.computeVertexNormals();return geometry;
}

export function createCommonsTree(){
  const tree=new THREE.Group();tree.name='central-tree';
  const bark=new THREE.MeshStandardMaterial({color:0xd0c8b6,map:barkTexture(),roughness:.98});
  function branch(points,baseRadius,tipRadius,name='curved-tree-branch'){
    const curve=new THREE.CatmullRomCurve3(points,false,'centripetal');
    const segments=Math.max(12,Math.ceil(curve.getLength()*10));
    const geometry=new THREE.TubeGeometry(curve,segments,1,10,false),positions=geometry.attributes.position,uv=geometry.attributes.uv;
    for(let row=0;row<=segments;row++){
      const t=row/segments,center=curve.getPointAt(t),radius=THREE.MathUtils.lerp(baseRadius,tipRadius,Math.pow(t,.85));
      for(let col=0;col<=10;col++){
        const i=row*11+col;
        positions.setXYZ(i,center.x+(positions.getX(i)-center.x)*radius,center.y+(positions.getY(i)-center.y)*radius,center.z+(positions.getZ(i)-center.z)*radius);
        uv.setXY(i,col/10,t*curve.getLength()*1.8);
      }
    }
    geometry.computeVertexNormals();geometry.computeBoundingBox();
    const mesh=new THREE.Mesh(geometry,bark);mesh.name=name;mesh.castShadow=true;mesh.receiveShadow=true;tree.add(mesh);return mesh;
  }
  // Three gently diverging stems grow from a flared, shared root base.
  branch([v(0,.7,0),v(.1,1.08,-.04),v(.045,1.6,.05),v(.16,2.1,.08),v(.1,2.84,0)],.09,.022,'main-curved-trunk');
  branch([v(.09,1.18,-.02),v(-.06,1.5,.055),v(-.18,1.85,.12),v(-.32,2.2,.18),v(-.58,2.65,.24)],.046,.014,'secondary-curved-trunk');
  branch([v(.065,1.46,.04),v(.15,1.7,.02),v(.25,1.97,-.07),v(.4,2.3,-.15),v(.61,2.7,-.3)],.041,.014,'secondary-curved-trunk');
  const clusters=[];
  for(let i=0;i<12;i++){
    const angle=i*2.39996,radius=.5+noise(i+90)*.2;
    const root=v(.06,1.68+(i%4)*.12,.02);
    const end=v(Math.cos(angle)*radius,2.13+noise(i+130)*.43,Math.sin(angle)*radius*.84);
    const middle=root.clone().lerp(end,.58);middle.y-=.07;
    branch([root,middle,end],.039-(i%3)*.006,.009);
    for(let j=0;j<3;j++){
      const a=angle+(j-1)*.48,tip=end.clone().add(new THREE.Vector3(Math.cos(a)*.1,.08+noise(i*3+j+150)*.08,Math.sin(a)*.085));
      branch([end,end.clone().lerp(tip,.5).add(new THREE.Vector3(0,.035,0)),tip],.011,.0035,'canopy-twig');clusters.push(tip);
    }
  }
  for(let i=0;i<4;i++)clusters.push(v((noise(i+400)-.5)*.65,2.88+noise(i+410)*.12,(noise(i+420)-.5)*.55));

  for(let i=0;i<8;i++){
    const angle=i*2.39996,radius=.3+noise(i+460)*.13;
    clusters.push(v(Math.cos(angle)*radius,2.68+noise(i+480)*.19,Math.sin(angle)*radius*.84));
  }

  for(let i=0;i<6;i++){
    const angle=i*2.39996,radius=.38+noise(i+520)*.15;
    clusters.push(v(Math.cos(angle)*radius,2.01+noise(i+540)*.13,Math.sin(angle)*radius*.84));
  }

  // Rounded oval leaves build a softly pruned crown with depth above and below.
  const geometry=leafGeometry(),map=leafTexture(),matrix=new THREE.Object3D(),up=new THREE.Vector3(0,1,0);
  const leavesPerCluster=24,total=clusters.length*leavesPerCluster;
  for(let tone=0;tone<4;tone++){
    const material=new THREE.MeshStandardMaterial({color:[0x456547,0x587750,0x708f63,0x8ba17a][tone],map,roughness:.94,side:THREE.DoubleSide});
    const leaves=new THREE.InstancedMesh(geometry,material,total/4);leaves.name='layered-ficus-canopy';let slot=0;
    for(let i=tone;i<total;i+=4){
      const center=clusters[Math.floor(i/leavesPerCluster)],a=i*2.39996,vertical=noise(i+700)*2-1,radial=Math.sqrt(1-vertical*vertical),radius=.075+noise(i+900)*.1;
      matrix.position.copy(center).add(new THREE.Vector3(Math.cos(a)*radial*radius,vertical*radius*.7,Math.sin(a)*radial*radius));
      // A compact, upright oval crown with small irregularities, not a wide umbrella.
      const crownCenter=new THREE.Vector3(0,1.71,0),offset=matrix.position.clone().sub(crownCenter);
      const boundary=Math.sqrt((offset.x/.93)**2+(offset.y/.68)**2+(offset.z/.8)**2);
      if(boundary>1)matrix.position.copy(crownCenter).addScaledVector(offset,1/boundary);
      matrix.position.y=Math.min(matrix.position.y,2.29);
      const direction=new THREE.Vector3(Math.cos(a)*.8,.15+noise(i+1200)*.5,Math.sin(a)*.8).normalize();
      matrix.quaternion.setFromUnitVectors(up,direction);matrix.rotateY(noise(i+1500)*Math.PI*2);matrix.scale.setScalar(.72+noise(i+1800)*.36);matrix.updateMatrix();leaves.setMatrixAt(slot++,matrix.matrix);
    }
    leaves.instanceMatrix.needsUpdate=true;leaves.castShadow=true;leaves.receiveShadow=true;leaves.computeBoundingBox();leaves.computeBoundingSphere();tree.add(leaves);
  }
  return tree;
}
