import * as THREE from 'three';

// Local, deterministic textures: no downloads, image services, or random shimmer.
function texture(draw, width = 512, height = 512) {
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  draw(canvas.getContext('2d'), width, height);
  const map = new THREE.CanvasTexture(canvas);
  map.colorSpace = THREE.SRGBColorSpace;
  map.anisotropy = 4;
  return map;
}
const noise = value => {const n = Math.sin(value * 127.1 + 311.7) * 43758.5453; return n - Math.floor(n);};

export function createOfficeAssets({M, box, rounded, cylinder}) {
  const grain = texture((ctx, w, h) => {
    ctx.fillStyle = '#d2b58a'; ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 360; i++) {
      const y = noise(i) * h;
      ctx.strokeStyle = `rgba(92,61,35,${.025 + noise(i + 100) * .06})`;
      ctx.lineWidth = .5 + noise(i + 2);
      ctx.beginPath(); ctx.moveTo(0, y);
      ctx.bezierCurveTo(w * .3, y + 7, w * .65, y - 6, w, y); ctx.stroke();
    }
  });
  const floorTexture=texture((ctx,w,h)=>{
    ctx.fillStyle='#d6d4cc';ctx.fillRect(0,0,w,h);
    for(let i=0;i<26000;i++){
      ctx.fillStyle=i%2?'rgba(255,255,250,.11)':'rgba(86,84,73,.06)';
      ctx.fillRect(noise(i)*w,noise(i+70000)*h,1,1);
    }
  });
  floorTexture.wrapS=floorTexture.wrapT=THREE.RepeatWrapping;
  floorTexture.repeat.set(8,7);
  const weave = texture((ctx, w, h) => {
    ctx.fillStyle = '#e4dfd1'; ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < w; i += 4) {
      ctx.strokeStyle = i % 8 ? '#ffffff25' : '#5f59491b';
      ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, h); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(w, i); ctx.stroke();
    }
  }, 128, 128);
  weave.wrapS = weave.wrapT = THREE.RepeatWrapping;
  weave.repeat.set(3, 3);
  for (const name of ['oak', 'oakLight']) {M[name].map = grain; M[name].roughness = .57;}
  for (const name of ['sofa','sofaLight','sofaCream','loungeBlue','loungeOlive','cushion','cushionGold','rugInset','blueRug']) {
    M[name].map = weave; M[name].roughness = .94;
  }
  M.brass.metalness = .55;
  const floorMaterial = new THREE.MeshStandardMaterial({color:0xffffff, map:floorTexture, roughness:.94});
  const soil = new THREE.MeshStandardMaterial({color:0x3c392d, roughness:1});
  const ceramic = new THREE.MeshStandardMaterial({color:0xe9dfc9, roughness:.52});
  const stem = new THREE.MeshStandardMaterial({color:0x566044, roughness:.88});
  const foliage = [0x4d7353,0x66855b,0x829568].map(color => new THREE.MeshStandardMaterial({color, roughness:.8, side:THREE.DoubleSide}));
  const leafShape = new THREE.Shape();
  leafShape.moveTo(0,0); leafShape.bezierCurveTo(-.22,.18,-.18,.52,0,.72);
  leafShape.bezierCurveTo(.18,.52,.22,.18,0,0);
  const leafGeometry = new THREE.ShapeGeometry(leafShape, 10);
  const positions = leafGeometry.attributes.position;
  for (let i = 0; i < positions.count; i++) positions.setZ(i, .09 * Math.sin(positions.getY(i) * Math.PI / .72) + Math.abs(positions.getX(i)) * .35);
  leafGeometry.computeVertexNormals();
  const screenCache = new Map();
  function screenMaterial(theme) {
    if (screenCache.has(theme)) return screenCache.get(theme);
    const map = texture((ctx,w,h) => {
      ctx.fillStyle = '#152f35'; ctx.fillRect(0,0,w,h);
      ctx.fillStyle = '#223f43'; ctx.fillRect(0,0,w,40);
      for (let i=0;i<3;i++){ctx.fillStyle=['#dba58a','#e2c380','#8fb997'][i];ctx.beginPath();ctx.arc(21+i*17,20,4,0,Math.PI*2);ctx.fill();}
      ctx.fillStyle='#a9c6be';ctx.font='600 14px system-ui';ctx.fillText({architecture:'DISEÑO DE ARQUITECTURA',finops:'PLAN DE COSTOS',infrastructure:'INFRAESTRUCTURA · TERRAFORM',engagement:'DESCUBRIMIENTO · PROYECTO'}[theme]||'ESPACIO DE PROYECTO',90,25);
      if(theme==='architecture'){
        const nodes=[[256,88],[130,173],[382,173],[130,257],[382,257]];
        ctx.strokeStyle='#6faaa9';ctx.lineWidth=3;
        for(const [a,b] of [[0,1],[0,2],[1,3],[2,4]]){ctx.beginPath();ctx.moveTo(...nodes[a]);ctx.lineTo(...nodes[b]);ctx.stroke();}
        for(const [i,[x,y]] of nodes.entries()){
          ctx.fillStyle=i?'#315e63':'#a98b51';ctx.beginPath();ctx.roundRect(x-47,y-22,94,44,8);ctx.fill();
          ctx.fillStyle='#e3eecc';ctx.font='13px system-ui';ctx.textAlign='center';ctx.fillText(['CLIENTE','API','DATOS','SERVICIOS','ARCHIVO'][i],x,y+5);
        }
      }else if(theme==='finops'){
        ctx.fillStyle='#adc5b0';ctx.font='18px system-ui';ctx.fillText('Distribución estimada',28,80);
        for(let i=0;i<5;i++){ctx.fillStyle=i===2?'#d8b66d':'#7da69a';ctx.beginPath();ctx.roundRect(38+i*92,257-[70,115,145,92,125][i],52,[70,115,145,92,125][i],5);ctx.fill();}
        ctx.strokeStyle='#48666a';ctx.beginPath();ctx.moveTo(24,264);ctx.lineTo(486,264);ctx.stroke();
      }else if(theme==='infrastructure'){
        ctx.font='16px monospace';
        const lines=['module "cloud" {','  source = "./modules"','  region = var.region','  tags = local.tags','}', '', '# Configuración del proyecto'];
        lines.forEach((line,i)=>{ctx.fillStyle=i===6?'#8fae9a':i%2?'#b5d2cd':'#e0be7c';ctx.fillText(line,28,83+i*29);});
      }else{
        for(let i=0;i<3;i++){
          const y=65+i*77;ctx.fillStyle='#24494b';ctx.beginPath();ctx.roundRect(24,y,464,62,8);ctx.fill();
          ctx.fillStyle='#b7c7a5';ctx.font='16px system-ui';ctx.fillText(['Objetivos del cliente','Alcance y necesidades','Próximos pasos'][i],65,y+36);
          ctx.fillStyle='#d6b87c';ctx.beginPath();ctx.arc(43,y+30,6,0,Math.PI*2);ctx.fill();
        }
      }
    },512,304);
    const mat = new THREE.MeshBasicMaterial({map, toneMapped:false});
    screenCache.set(theme,mat);return mat;
  }
  const artCache=new Map();
  function wallArtMaterial(theme){
    if(artCache.has(theme))return artCache.get(theme);
    // A quiet collection of landscape prints, with a paper mat and atmospheric depth.
    const palettes={
      engagement:{sky:'#ead8c6',haze:'#f3e9d8',far:'#d3b7a1',mid:'#b98d73',near:'#866750',ink:'#6c5849'},
      architecture:{sky:'#d2e0df',haze:'#edf0e8',far:'#a4b9bc',mid:'#78959e',near:'#4d6e79',ink:'#405d68'},
      finops:{sky:'#dce2cf',haze:'#f2ecdb',far:'#bac8ae',mid:'#90a183',near:'#5d765f',ink:'#455f50'},
      infrastructure:{sky:'#d8e2e1',haze:'#eee9d9',far:'#afc1c0',mid:'#7f9d9e',near:'#526f75',ink:'#405b64'}
    };
    const colors=palettes[theme]||palettes.engagement;
    const map=texture((ctx,w,h)=>{
      ctx.fillStyle='#f7f3e8';ctx.fillRect(0,0,w,h);
      ctx.save();ctx.beginPath();ctx.rect(34,29,w-68,h-58);ctx.clip();
      ctx.translate(34,29);const iw=w-68,ih=h-58;
      const sky=ctx.createLinearGradient(0,0,0,ih);sky.addColorStop(0,colors.sky);sky.addColorStop(.7,colors.haze);
      ctx.fillStyle=sky;ctx.fillRect(0,0,iw,ih);
      ctx.fillStyle='#fff6df';ctx.globalAlpha=.72;ctx.beginPath();ctx.arc(iw*.73,ih*.26,ih*.095,0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;
      const ridge=(color,start,curves)=>{
        ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(0,ih*start);
        for(const curve of curves)ctx.bezierCurveTo(...curve.map((v,i)=>v*(i%2?ih:iw)));
        ctx.lineTo(iw,ih);ctx.lineTo(0,ih);ctx.closePath();ctx.fill();
      };
      if(theme==='architecture'){
        ridge(colors.far,.64,[[.12,.59,.19,.13,.3,.33],[.4,.5,.47,.18,.6,.39],[.78,.63,.83,.3,1,.52]]);
        ridge(colors.mid,.75,[[.15,.72,.24,.4,.36,.48],[.54,.63,.63,.38,.75,.52],[.85,.67,.91,.51,1,.63]]);
        ridge(colors.haze,.8,[[.22,.74,.38,.81,.55,.76],[.74,.71,.88,.8,1,.77]]);
        ridge(colors.near,.88,[[.15,.7,.3,.8,.39,.85],[.64,.96,.8,.91,1,.94]]);
      }else if(theme==='infrastructure'){
        ridge(colors.far,.56,[[.25,.33,.37,.62,.58,.52],[.78,.43,.92,.53,1,.49]]);
        ridge(colors.mid,.65,[[.17,.51,.3,.59,.45,.68],[.7,.84,.83,.73,1,.76]]);
        ridge(colors.haze,.81,[[.28,.69,.37,.81,.52,.78],[.75,.68,.83,.78,1,.74]]);
        ridge(colors.near,.9,[[.14,.82,.24,.74,.33,.8],[.5,.95,.62,.94,1,1.03]]);
      }else{
        ridge(colors.far,.56,[[.2,.32,.31,.43,.49,.52],[.7,.65,.84,.27,1,.44]]);
        ridge(colors.mid,.72,[[.17,.64,.28,.47,.46,.61],[.64,.76,.82,.51,1,.62]]);
        ridge(colors.near,.93,[[.22,.72,.39,.9,.56,.81],[.72,.69,.86,.81,1,.74]]);
      }
      if(theme==='finops'){
        // Loose ink trees follow the foreground rather than forming a repeated pattern.
        ctx.strokeStyle=colors.ink;ctx.lineCap='round';
        for(let i=0;i<15;i++){
          const x=(.03+noise(i+81)*.92)*iw,base=ih*(.91+noise(i+64)*.13),height=ih*(.13+noise(i+42)*.19);
          ctx.globalAlpha=.38+noise(i+73)*.25;ctx.lineWidth=1.2;ctx.beginPath();ctx.moveTo(x,base);ctx.lineTo(x,base-height);ctx.stroke();
          for(let j=1;j<8;j++){
            const y=base-height+height*j/9,spread=height*j*.045;
            ctx.beginPath();ctx.moveTo(x-spread,y+height*.08);ctx.quadraticCurveTo(x,y-height*.035,x+spread,y+height*.08);ctx.stroke();
          }
        }
        ctx.globalAlpha=1;
      }else{
        // Fine reflected light and contour strokes give the print a hand-worked surface.
        ctx.strokeStyle=colors.haze;ctx.lineWidth=1;ctx.globalAlpha=.35;
        for(let i=0;i<28;i++){
          const x=noise(i+92)*iw,y=ih*(.79+noise(i+22)*.18),length=8+noise(i+3)*45;
          ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+length,y-.6);ctx.stroke();
        }
        ctx.globalAlpha=1;
      }
      // Deterministic paper grain softens the otherwise perfect canvas shapes.
      for(let i=0;i<18000;i++){
        ctx.fillStyle=i%2?'rgba(255,250,229,.045)':'rgba(66,60,49,.025)';
        ctx.fillRect(noise(i+550)*iw,noise(i+26000)*ih,1,1);
      }
      ctx.restore();
    },768,416);
    const result=new THREE.MeshStandardMaterial({map,roughness:.9});artCache.set(theme,result);return result;
  }
  function floor(parent,w,d) {return box(parent,w-.06,.014,d-.06,floorMaterial,0,.207,0,{cast:false});}
  const stemGeometry=new THREE.CylinderGeometry(1,.8,1,6);
  function connect(parent,a,b,r,mat) {
    const direction=b.clone().sub(a),mesh=new THREE.Mesh(stemGeometry,mat);
    mesh.scale.set(r,direction.length(),r);parent.add(mesh);
    mesh.position.copy(a).add(b).multiplyScalar(.5);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),direction.normalize());return mesh;
  }
  function plant(parent,x,z,scale=1) {
    const group=new THREE.Group();group.name='potted-plant';group.position.set(x,.2,z);group.scale.setScalar(scale);parent.add(group);
    cylinder(group,.25,.19,.38,ceramic,0,.19,0,24);
    cylinder(group,.224,.224,.018,soil,0,.388,0,24);
    const rim=new THREE.Mesh(new THREE.TorusGeometry(.245,.025,8,24),ceramic);rim.rotation.x=Math.PI/2;rim.position.y=.37;group.add(rim);
    for(let i=0;i<7;i++){
      const angle=i*2.39996, height=.65+noise(i+3)*.48;
      const end=new THREE.Vector3(Math.cos(angle)*.18,height,Math.sin(angle)*.18);
      connect(group,new THREE.Vector3(0,.38,0),end,.012,stem);
      const leaf=new THREE.Mesh(leafGeometry,foliage[i%3]);leaf.position.copy(end);leaf.rotation.set(.35+noise(i)*.3,angle,-.5);leaf.scale.setScalar(.65+noise(i+30)*.25);leaf.castShadow=true;group.add(leaf);
    }
    return group;
  }
  function mug(parent,x,y,z,color=ceramic) {
    cylinder(parent,.06,.055,.12,color,x,y+.06,z,16);
    cylinder(parent,.048,.048,.006,M.oak,x,y+.122,z,16);
    const handle=new THREE.Mesh(new THREE.TorusGeometry(.045,.012,6,12),color);handle.position.set(x+.065,y+.067,z);parent.add(handle);
  }
  const keys=texture((ctx,w,h)=>{ctx.fillStyle='#283c3c';ctx.fillRect(0,0,w,h);ctx.fillStyle='#738582';for(let row=0;row<4;row++)for(let col=0;col<12;col++)ctx.fillRect(7+col*20,5+row*15,16,10);},256,64);
  const keyboardMaterial=new THREE.MeshStandardMaterial({map:keys,roughness:.7});
  const keyboardGeometry=new THREE.PlaneGeometry(.58,.145);
  function deskDetails(parent,theme,{plateSide=-1,monitorX=0}={}) {
    rounded(parent,.13,.025,.2,.035,M.black,monitorX-plateSide*.43,.95,.21);
    mug(parent,-plateSide*.78,.91,-.01);
    const notebook=new THREE.MeshStandardMaterial({color:{engagement:0x9f7961,architecture:0x728f9d,finops:0x7e8d68,infrastructure:0x637a80}[theme]||0x9f7961,roughness:.85});
    rounded(parent,.29,.025,.36,.015,notebook,plateSide*.52,.93,.11);
    box(parent,.012,.012,.27,M.brass,plateSide*.56,.952,.11);
    // One shared keyboard texture replaces dozens of tiny key meshes.
    const keyboard=new THREE.Mesh(keyboardGeometry,keyboardMaterial);keyboard.rotation.x=-Math.PI/2;keyboard.position.set(monitorX,.969,.2);parent.add(keyboard);
  }
  const nameplateCache=new Map();
  const nameplateMetal=new THREE.MeshStandardMaterial({color:0xb9bfbb,roughness:.45,metalness:.78});
  function deskNameplate(parent,theme,{side=-1}={}){
    const title={architecture:'Arquitectura',infrastructure:'Infraestructura',finops:'FinOps',engagement:'Engagement'}[theme];
    if(!title)return;
    if(!nameplateCache.has(theme)){
      const map=texture((ctx,w,h)=>{
        const silver=ctx.createLinearGradient(0,0,0,h);silver.addColorStop(0,'#e7e9e6');silver.addColorStop(.5,'#cbd0cc');silver.addColorStop(1,'#e0e4e0');
        ctx.fillStyle=silver;ctx.fillRect(0,0,w,h);
        for(let i=0;i<h;i++){
          ctx.strokeStyle=`rgba(76,86,80,${.015+noise(i+200)*.035})`;ctx.lineWidth=.5;
          ctx.beginPath();ctx.moveTo(0,i+.5);ctx.lineTo(w,i+.5);ctx.stroke();
        }
        ctx.fillStyle='#111511';ctx.textAlign='center';ctx.textBaseline='middle';
        ctx.font='700 140px Arial, sans-serif';ctx.fillText(title,w/2,h/2+3,w-76);
      },1024,224);
      nameplateCache.set(theme,new THREE.MeshStandardMaterial({map,roughness:.58,metalness:.38}));
    }
    const plate=new THREE.Group();plate.name='desk-nameplate';plate.userData.title=title;
    // The compact plate sits ahead of the centered display, with a clear gap between them.
    plate.position.set(side*.54,0,-.4);parent.add(plate);
    rounded(plate,.53,.018,.08,.006,nameplateMetal,0,.919,0);
    const panel=new THREE.Group();panel.position.y=.992;panel.rotation.x=.2;plate.add(panel);
    rounded(panel,.51,.13,.014,.005,nameplateMetal,0,0,0);
    const face=new THREE.Mesh(new THREE.PlaneGeometry(.49,.11),nameplateCache.get(theme));
    face.name='desk-nameplate-face';face.rotation.y=Math.PI;face.position.z=-.009;panel.add(face);
  }
  function boardroomDetails(parent,tableZ=0) {
    for(const x of [-1.2,0,1.2])for(const side of [-1,1]){
      rounded(parent,.34,.018,.27,.018,ceramic,x,1.075,side*.6+tableZ);
      mug(parent,x+.3,1.065,side*.62+tableZ);
    }
    rounded(parent,.48,.045,.3,.06,M.black,0,1.085,tableZ);
    for(const x of [-.15,0,.15])box(parent,.05,.012,.09,M.metal,x,1.112,tableZ);
    // Presentation display sits on the rear wall, clear of the doorway and chairs.
    box(parent,2.5,1.23,.1,M.black,0,1.84,-2.5);
    box(parent,2.34,1.1,.012,screenMaterial('architecture'),0,1.84,-2.44,{cast:false});
  }
  function coffeeCorner(parent) {
    const group=new THREE.Group();group.name='integrated-pantry';group.position.set(-8,0,-10.4);parent.add(group);
    const cabinets=new THREE.MeshStandardMaterial({color:0xe5e5de,roughness:.8});
    const worktop=new THREE.MeshStandardMaterial({color:0x969990,roughness:.65});
    // Cabinetry is built against the external wall, on the shared office floor.
    box(group,3.5,.91,.66,cabinets,0,.675,-1.1);
    box(group,3.58,.055,.74,worktop,0,1.155,-1.1);
    for(const x of [-1.15,0,1.15]){
      box(group,.014,.78,.01,M.metal,x,.7,-.763);
      box(group,.21,.018,.025,M.metal,x+.3,.98,-.75);
    }
    rounded(group,.56,.53,.4,.035,M.black,-1,1.445,-1.1);
    box(group,.41,.2,.016,M.metal,-1,1.48,-.895);
    box(group,.36,.035,.25,M.metal,-1,1.205,-.94);
    mug(group,-1,1.225,-.93);
    // Recessed sink and a compact tap keep the worktop functional and clear.
    rounded(group,.65,.022,.42,.07,M.metal,.8,1.187,-1.1);
    rounded(group,.54,.024,.31,.055,M.black,.8,1.19,-1.1);
    cylinder(group,.018,.018,.23,M.metal,.8,1.31,-1.37,12);
    box(group,.018,.018,.16,M.metal,.8,1.426,-1.3);
    return group;
  }
  function projectCorner(parent) {
    const group=new THREE.Group();group.name='collaboration-wall';group.position.set(8,0,-10.4);parent.add(group);
    const cabinet=new THREE.MeshStandardMaterial({color:0xe5e5de,roughness:.85});
    // Wall-mounted board and low storage replace the freestanding display set.
    rounded(group,2.8,1.32,.07,.025,M.metal,0,2,-1.6);
    box(group,2.7,1.22,.014,ceramic,0,2,-1.556);
    box(group,2.9,.72,.48,cabinet,0,.58,-1.37);
    box(group,2.95,.04,.52,M.oakLight,0,.96,-1.37);
    for(const x of [-.73,0,.73])box(group,.012,.6,.012,M.metal,x,.58,-1.12);
    for(const [x,y] of [[-.8,2.2],[0,2.2],[.8,2.2],[0,1.8]]){
      box(group,.38,.22,.008,M.blueRug,x,y,-1.541);
      box(group,.24,.012,.006,M.metal,x,y,-1.534);
    }
    box(group,1.6,.012,.008,M.metal,0,2.02,-1.532);
    return group;
  }
  return {floor,plant,screenMaterial,wallArtMaterial,deskDetails,deskNameplate,boardroomDetails,coffeeCorner,projectCorner};
}
