import * as THREE from 'three';
import {createCommonsChair} from './commons-seating.js';
import {createCommonsTree} from './commons-tree.js';

// A coordinated commons: a shared oak workbench and a planted seating island.
// All permanent pieces remain inside the core, away from office entrances.
export function createCommons({M,box,rounded,cylinder}){
  const group=new THREE.Group();group.name='central-commons';
  const oak=M.oakLight;
  const chalk=new THREE.MeshStandardMaterial({color:0xe9e8de,roughness:.92});
  const aluminum=new THREE.MeshStandardMaterial({color:0xc6cbc6,roughness:.45,metalness:.35});
  const graphite=new THREE.MeshStandardMaterial({color:0x626d67,roughness:.8});
  const linen=new THREE.MeshStandardMaterial({color:0xd9d9cd,roughness:1});

  // One long work surface, with recessed power and two broad, quiet supports.
  const workbench=new THREE.Group();workbench.name='shared-oak-workbench';group.add(workbench);
  rounded(workbench,1.4,.085,3.9,.065,oak,0,.9475,-2.7);
  for(const z of [-4.05,-1.35]){
    rounded(workbench,.86,.69,.115,.025,oak,0,.605,z);
    rounded(workbench,.96,.04,.42,.02,aluminum,0,.235,z);
  }
  rounded(workbench,.13,.008,.7,.025,graphite,0,.993,-2.7);
  for(const z of [-2.91,-2.7,-2.49])box(workbench,.055,.003,.022,aluminum,0,.999,z,{cast:false});
  rounded(workbench,.28,.018,.37,.012,linen,.28,1.005,-3.95);
  rounded(workbench,.28,.014,.38,.012,aluminum,-.25,1.005,-1.45);

  function upholsteredChair(x,z,rotation){
    const chair=createCommonsChair({oak,upholstery:chalk,frame:aluminum});
    chair.position.set(x,.214,z);chair.rotation.y=rotation;group.add(chair);return chair;
  }
  for(const z of [-3.95,-2.7,-1.45]){
    upholsteredChair(-1.29,z,Math.PI/2);upholsteredChair(1.29,z,-Math.PI/2);
  }

  const island=new THREE.Group();island.name='planted-conversation-island';island.position.z=2.1;group.add(island);
  // Curved joinery, cushioning, and planter are designed as one built-in element.
  function arc(inner,outer,start,end,height,y,material,name){
    const shape=new THREE.Shape(),steps=48;
    for(let i=0;i<=steps;i++){
      const a=start+(end-start)*i/steps,x=Math.sin(a)*outer,yy=-Math.cos(a)*outer;
      if(i===0)shape.moveTo(x,yy);else shape.lineTo(x,yy);
    }
    for(let i=steps;i>=0;i--){const a=start+(end-start)*i/steps;shape.lineTo(Math.sin(a)*inner,-Math.cos(a)*inner);}
    shape.closePath();
    const geometry=new THREE.ExtrudeGeometry(shape,{depth:height,steps:1,bevelEnabled:true,bevelSize:.018,bevelThickness:.012,bevelSegments:3,curveSegments:12});
    geometry.rotateX(-Math.PI/2);
    const mesh=new THREE.Mesh(geometry,material);mesh.name=name;mesh.position.y=y;mesh.castShadow=true;mesh.receiveShadow=true;island.add(mesh);return mesh;
  }
  for(const side of [-1,1]){
    const start=THREE.MathUtils.degToRad(side>0?35:-145),end=THREE.MathUtils.degToRad(side>0?145:-35);
    arc(.99,1.59,start,end,.285,.23,oak,'curved-oak-banquette');
    arc(1.025,1.545,start+.025,end-.025,.12,.53,chalk,'curved-seat-cushion');
    arc(.975,1.045,start,end,.25,.635,oak,'curved-backrest');
  }
  cylinder(island,.64,.61,.47,chalk,0,.449,0,64);
  cylinder(island,.593,.593,.018,new THREE.MeshStandardMaterial({color:0x5a5c4c,roughness:1}),0,.693,0,48);
  const rim=new THREE.Mesh(new THREE.TorusGeometry(.616,.014,8,64),chalk);rim.rotation.x=-Math.PI/2;rim.position.y=.7;island.add(rim);

  const tree=createCommonsTree();tree.position.y=.7;island.add(tree);
  const noise=i=>{const v=Math.sin(i*127.1+31.7)*43758.5453;return v-Math.floor(v);};
  const stone=new THREE.MeshStandardMaterial({color:0xa7a390,roughness:1});
  const pebble=new THREE.SphereGeometry(1,10,7);
  for(let i=0;i<8;i++){const a=i*2.39996,mesh=new THREE.Mesh(pebble,stone);const r=.2+noise(i+950)*.31;mesh.scale.set(.022+noise(i+970)*.014,.012,.018+noise(i+980)*.011);mesh.rotation.y=a;mesh.position.set(Math.cos(a)*r,.707,Math.sin(a)*r);island.add(mesh);}
  return group;
}
