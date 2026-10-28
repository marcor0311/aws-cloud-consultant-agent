import * as THREE from 'three';

const greens=[0x355b3e,0x476c46,0x608153].map(color=>new THREE.MeshStandardMaterial({color,roughness:.62,side:THREE.DoubleSide}));
const bark=new THREE.MeshStandardMaterial({color:0x6d7250,roughness:.9});
const ceramic=new THREE.MeshStandardMaterial({color:0xdcd9cd,roughness:.78});
const soil=new THREE.MeshStandardMaterial({color:0x444237,roughness:1});
let leafGeometry;
function broadLeaf(){
  if(leafGeometry)return leafGeometry;
  const shape=new THREE.Shape();
  shape.moveTo(0,0);shape.bezierCurveTo(-.07,.015,-.13,.06,-.12,.16);shape.bezierCurveTo(-.11,.25,-.045,.295,0,.3);
  shape.bezierCurveTo(.045,.295,.11,.25,.12,.16);shape.bezierCurveTo(.13,.06,.07,.015,0,0);
  leafGeometry=new THREE.ShapeGeometry(shape,12);
  const points=leafGeometry.attributes.position;
  for(let i=0;i<points.count;i++)points.setZ(i,.046*Math.sin(points.getY(i)*Math.PI/.29)+Math.abs(points.getX(i))*.24);
  leafGeometry.computeVertexNormals();return leafGeometry;
}

// A full, multi-stem ficus. Leaves grow in pairs along real branches, not bare stalks.
export function createOfficePlant(){
  const plant=new THREE.Group();plant.name='office-ficus';
  const add=(geometry,material,x=0,y=0,z=0)=>{
    const mesh=new THREE.Mesh(geometry,material);mesh.position.set(x,y,z);mesh.castShadow=true;mesh.receiveShadow=true;plant.add(mesh);return mesh;
  };
  add(new THREE.CylinderGeometry(.285,.235,.43,40),ceramic,0,.215,0);
  add(new THREE.CylinderGeometry(.257,.257,.012,32),soil,0,.429,0);
  const rim=add(new THREE.TorusGeometry(.274,.012,8,40),ceramic,0,.431,0);rim.rotation.x=Math.PI/2;
  const matrices=[[],[],[]],dummy=new THREE.Object3D(),up=new THREE.Vector3(0,1,0);
  for(let stem=0;stem<7;stem++){
    const angle=stem*2.39996,height=1.12+(stem%3)*.17,radius=.19+(stem%3)*.075;
    const curve=new THREE.QuadraticBezierCurve3(new THREE.Vector3(Math.cos(angle)*.045,.43,Math.sin(angle)*.045),new THREE.Vector3(Math.cos(angle)*.13,height*.64,Math.sin(angle)*.13),new THREE.Vector3(Math.cos(angle)*radius,height,Math.sin(angle)*radius));
    add(new THREE.TubeGeometry(curve,12,.009,6,false),bark);
    for(let row=0;row<8;row++)for(const side of [-1,1]){
      const t=.24+row*.103,point=curve.getPoint(t),azimuth=angle+side*(.7+row*.21);
      dummy.position.copy(point);
      const direction=new THREE.Vector3(Math.cos(azimuth),.08+row*.035,Math.sin(azimuth)).normalize();
      const right=new THREE.Vector3().crossVectors(direction,up).normalize(),normal=new THREE.Vector3().crossVectors(right,direction).normalize();
      dummy.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(right,direction,normal));dummy.rotateY(side*.17);
      dummy.scale.setScalar(.86+(row%3)*.12);dummy.updateMatrix();matrices[(stem+row)%3].push(dummy.matrix.clone());
    }
  }
  for(let i=0;i<3;i++){
    const leaves=new THREE.InstancedMesh(broadLeaf(),greens[i],matrices[i].length);leaves.name='ficus-leaves';leaves.castShadow=true;leaves.receiveShadow=true;
    matrices[i].forEach((matrix,index)=>leaves.setMatrixAt(index,matrix));leaves.instanceMatrix.needsUpdate=true;leaves.computeBoundingSphere();plant.add(leaves);
  }
  return plant;
}
