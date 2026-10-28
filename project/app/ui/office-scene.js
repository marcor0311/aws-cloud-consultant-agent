
    import * as THREE from 'three';
    import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
    import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
    import { createOfficeAssets } from './assets/office-assets.js';
    import { shelfPrintMaterial } from './assets/office-identity.js';
    import { createCloudAgent } from './assets/cloud-agent.js';
    import { createCommons } from './assets/commons-space.js';
    import { createNavigation } from './assets/office-navigation.js';
    import { createCommonsChair } from './assets/commons-seating.js';
    import { createOfficePlant } from './assets/office-plant.js';
    import { officeSeatMotion, OFFICE_VISIT_DURATION } from './assets/office-seat-motion.js';

    export function createOffice(root, { onContextLost = () => {}, onFollowChange = () => {} } = {}) {
    const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)').matches;
    const scene=new THREE.Scene();
    scene.background=new THREE.Color(0xe7e7e2);
    scene.fog=new THREE.Fog(0xe7e7e2,65,150);
    const camera=new THREE.PerspectiveCamera(39,1,.1,180);
    camera.position.set(13,20,25);
    const renderer=new THREE.WebGLRenderer({antialias:true});
    renderer.setPixelRatio(Math.min(devicePixelRatio,2));
    renderer.shadowMap.enabled=true;
    renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate=false;
    renderer.shadowMap.needsUpdate=true;
    let needsRender=true;
    renderer.outputColorSpace=THREE.SRGBColorSpace;
    renderer.toneMapping=THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure=1.05;
    root.append(renderer.domElement);

    const controls=new OrbitControls(camera,renderer.domElement);
    controls.target.set(0,0,0);
    controls.enableDamping=!reducedMotion;
    controls.dampingFactor=.07;
    controls.minPolarAngle=.28;
    controls.maxPolarAngle=1.34;
    controls.minDistance=3.2;
    controls.maxDistance=95;
    controls.maxTargetRadius=18;
    controls.cursor.set(0,0,-2);
    renderer.domElement.tabIndex=0;
    renderer.domElement.setAttribute('aria-label','Oficina 3D. Flechas para girar, más y menos para acercar o alejar, Inicio para restablecer la vista.');
    renderer.domElement.setAttribute('aria-describedby','navigation-help');

    const material=(color,roughness=.82,extra={})=>new THREE.MeshStandardMaterial({color,roughness,...extra});
    const M={
      ground:material(0xd1d2ca),slab:material(0xe8e9df),wall:material(0xe7e7df),wallTop:material(0xf0f1e9),
      oak:material(0xb4875e),oakLight:material(0xeee5d4),metal:material(0x59665c),
      glass:new THREE.MeshStandardMaterial({color:0xdfe9e8,roughness:.18,transparent:true,opacity:.12,depthWrite:false}),
      rug:material(0x9c8065),rugInset:material(0xb5a187),blueRug:material(0xabbdb3),
      sofa:material(0x244c49),sofaLight:material(0x956548),sofaCream:material(0xd0c1a7),
      loungeBlue:material(0x344d66),loungeOlive:material(0x65745b),
      cushion:material(0xe1d5bd),cushionGold:material(0xc99e62),brass:material(0x68736d,.5,{metalness:.35}),
      green:material(0x557454),leaf:material(0x6d9367),
      screen:material(0x344d4a,.32),black:material(0x38443e),white:material(0xf4f2e9)
    };
    const boxGeometry=new THREE.BoxGeometry(1,1,1),geometryCache=new Map();
    function geometry(key,create){if(!geometryCache.has(key))geometryCache.set(key,create());return geometryCache.get(key)}
    function box(parent,w,h,d,mat,x,y,z,opts={}){const o=new THREE.Mesh(boxGeometry,mat);o.scale.set(w,h,d);o.position.set(x,y,z);o.castShadow=opts.cast!==false;o.receiveShadow=true;parent.add(o);return o}
    function rounded(parent,w,h,d,r,mat,x,y,z){const o=new THREE.Mesh(geometry(`rounded:${w}:${h}:${d}:${r}`,()=>new RoundedBoxGeometry(w,h,d,2,r)),mat);o.position.set(x,y,z);o.castShadow=true;o.receiveShadow=true;parent.add(o);return o}
    function cylinder(parent,rTop,rBot,h,mat,x,y,z,segments=16){const o=new THREE.Mesh(geometry(`cylinder:${rTop}:${rBot}:${h}:${segments}`,()=>new THREE.CylinderGeometry(rTop,rBot,h,segments)),mat);o.position.set(x,y,z);o.castShadow=true;o.receiveShadow=true;parent.add(o);return o}
    const assets=createOfficeAssets({M,box,rounded,cylinder});
    const officeRug=material(0xdad8ce,1,{map:M.rugInset.map.clone()});officeRug.map.repeat.set(12,12);
    function wall(parent,w,h,d,x,y,z,mat=M.wall){return box(parent,w,h,d,mat,x,y,z)}
    function addLabel(text,x,z,width=4.5){
      const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');canvas.width=1024;canvas.height=224;
      ctx.fillStyle='rgba(32,48,43,.94)';ctx.beginPath();ctx.roundRect(8,8,1008,208,38);ctx.fill();
      ctx.fillStyle='#c6a46c';ctx.beginPath();ctx.roundRect(36,58,5,108,2.5);ctx.fill();
      const words=text.split(' '),lines=[''];ctx.font='600 76px Inter,system-ui,sans-serif';
      for(const word of words){const i=lines.length-1,next=lines[i]?`${lines[i]} ${word}`:word;if(ctx.measureText(next).width>850&&lines[i])lines.push(word);else lines[i]=next}
      ctx.fillStyle='#f5f3ea';ctx.textAlign='center';ctx.textBaseline='middle';
      const lineHeight=lines.length>1?76:0;lines.forEach((line,i)=>ctx.fillText(line,535,(canvas.height/2)+(i-(lines.length-1)/2)*lineHeight,850));
      const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
      const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}));sprite.position.set(x,3.35,z);sprite.scale.set(width,width*.25,1);sprite.userData.baseWidth=width;scene.add(sprite);return sprite
    }
    function plant(parent,x,z,scale=1){return assets.plant(parent,x,z,scale)}
    function conferenceChair(parent,x,z,angle=0,color=M.sofa){
      const c=new THREE.Group();c.position.set(x,0,z);c.rotation.y=angle;parent.add(c);
      cylinder(c,.27,.3,.13,M.brass,0,.25,0,24);
      cylinder(c,.075,.095,.33,M.metal,0,.45,0,20);
      rounded(c,.68,.2,.68,.09,color,0,.62,0);
      rounded(c,.63,.72,.18,.08,color,0,1.03,-.25);
      for(const dx of [-.37,.37]){
        box(c,.045,.32,.045,M.metal,dx,.78,-.01);
        rounded(c,.1,.08,.42,.035,M.oakLight,dx,.91,.04)
      }
      return c
    }
    function desk(parent,x,z,rotation=0,theme='engagement',plateSide=-1){
      const d=new THREE.Group();d.name=`${theme}-desk`;d.position.set(x,0,z);d.rotation.y=rotation;parent.add(d);
      const style={
        engagement:{seat:0x796351,mat:0xb29d80,art:0x87654e},
        architecture:{seat:0x4f6a79,mat:0x8da7ae,art:0x527f94},
        finops:{seat:0x5e7055,mat:0x9aaa86,art:0x8e9a65},
        infrastructure:{seat:0x46565e,mat:0x8b9ea0,art:0x52636b}
      }[theme]||{seat:0x805b48,mat:0xc4a979,art:0x87654e};
      const walnut=M.oakLight;
      rounded(d,1.9,.09,.9,.025,walnut,0,.865,0);
      box(d,1.7,.05,.66,M.metal,0,.8,0);
      for(const dx of [-.72,.72])for(const dz of [-.28,.28])box(d,.045,.62,.045,M.metal,dx,.51,dz);
      rounded(d,.44,.28,.65,.02,M.wall,-.56,.68,0);
      box(d,.18,.016,.018,M.metal,-.56,.71,.335);
      rounded(d,.9,.025,.46,.04,material(style.mat,.55),0,.914,-.08);
      // A large, single display and a keyboard keep the desk calm and executive.
      const monitorX=0;
      box(d,1.02,.63,.055,M.black,monitorX,1.27,-.28);
      box(d,.93,.53,.018,assets.screenMaterial(theme),monitorX,1.27,-.246,{cast:false});
      box(d,.08,.2,.08,M.metal,monitorX,1.035,-.28);box(d,.34,.035,.2,M.metal,monitorX,.94,-.28);
      rounded(d,.62,.035,.17,.025,M.black,monitorX,.95,.2);
      assets.deskDetails(d,theme,{plateSide,monitorX});
      plant(d,plateSide*.78,.32,.14).position.y=.91;
      // Deep-cushioned executive chair with a high back, padded arms, and a compact swivel base.
      const c=new THREE.Group();c.position.set(0,0,1.18);c.rotation.y=Math.PI;d.add(c);
      cylinder(c,.25,.29,.12,M.metal,0,.2,0,24);cylinder(c,.07,.09,.29,M.metal,0,.4,0,20);
      rounded(c,.82,.2,.74,.12,material(style.seat,.52),0,.59,0);
      rounded(c,.7,.76,.13,.065,material(style.seat,.75),0,1.05,-.28);
      for(const side of [-1,1]){
        box(c,.04,.28,.04,M.metal,side*.48,.79,-.04);
        rounded(c,.16,.12,.57,.055,material(style.seat,.5),side*.48,.94,-.02)
      }
      return d
    }
    function officeShelving(parent,x,z,theme){
      const group=new THREE.Group();group.name=`${theme}-shelving`;group.position.set(x,0,z);parent.add(group);
      const wood=material(theme==='infrastructure'?0x6f746b:theme==='engagement'?0x86674f:0x88785e,.75),back=material(0xd2d3c7,.95);
      const palettes={engagement:[0xa87f64,0xd9c7a3,0x6c8076],architecture:[0x587f95,0xa4bec5,0xd1d1bf],finops:[0x637d59,0xa6b48c,0xc8bb92],infrastructure:[0x4f6976,0x91a8b2,0xbecac5]};
      const colors=palettes[theme];
      box(group,1.62,1.65,.045,back,0,1.04,.04);
      for(const side of [-1,1])box(group,.055,1.68,.4,wood,side*.8,1.05,.23);
      for(const y of [.24,.78,1.32,1.88])box(group,1.65,.045,.42,M.oakLight,0,y,.23);
      box(group,1.54,.46,.36,M.wall,0,.51,.24);box(group,.018,.4,.014,M.metal,0,.51,.43);
      for(const side of [-1,1])box(group,.12,.012,.02,M.metal,side*.18,.65,.438);
      function book(xx,y,color,h=.33){box(group,.12,h,.22,material(color,.92),xx,y+h/2,.22);box(group,.065,.012,.007,M.sofaCream,xx,y+h*.73,.334);}
      function stack(xx,y,count){for(let i=0;i<count;i++){rounded(group,.35,.032,.25,.008,material(colors[i%3]),xx,y+i*.045,.24);box(group,.31,.018,.24,M.sofaCream,xx,y+i*.045+.023,.24);}}
      function print(xx,y,w=.4,h=.3){rounded(group,w+.045,h+.045,.025,.008,wood,xx,y,.26);box(group,w,h,.008,shelfPrintMaterial(theme),xx,y,.278);}
      function green(xx,y,scale=.24){assets.plant(group,xx,.22,scale).position.y=y;}
      if(theme==='engagement'){
        for(let i=0;i<3;i++)book(-.55+i*.17,.81,colors[i],.34+i*.02);
        stack(.36,.84,2);print(-.35,1.54,.42,.31);green(.43,1.35,.24);
        cylinder(group,.055,.08,.18,material(0xbfa68e),.58,1.03,.23,20);
      }else if(theme==='architecture'){
        for(let i=0;i<4;i++)book(-.55+i*.15,1.35,colors[i%3],.31+(i%2)*.05);
        const model=new THREE.Group();model.name='architectural-study-model';group.add(model);
        box(model,.53,.025,.28,M.oakLight,.28,.83,.23);
        for(const [xx,h] of [[.13,.12],[.28,.23],[.44,.16]]){box(model,.12,h,.17,M.white,xx,.85+h/2,.23);box(model,.065,.025,.006,M.blueRug,xx,.9+h*.45,.319);}
        print(.43,1.55,.3,.33);
        for(let i=0;i<2;i++)cylinder(group,.026,.026,.31,M.sofaCream,-.48+i*.08,.98,.23,14);
        green(-.05,.81,.22);
      }else if(theme==='finops'){
        for(let i=0;i<3;i++)book(-.55+i*.16,.81,colors[i],.36);stack(.35,.84,2);
        const canvas=document.createElement('canvas');canvas.width=canvas.height=256;const ctx=canvas.getContext('2d');ctx.fillStyle='#ede9da';ctx.fillRect(0,0,256,256);ctx.fillStyle='#435044';ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='25px system-ui';for(const [n,x,y] of [['12',128,34],['3',222,128],['6',128,225],['9',34,128]])ctx.fillText(n,x,y);ctx.strokeStyle='#435044';ctx.lineWidth=6;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(128,128);ctx.lineTo(91,92);ctx.moveTo(128,128);ctx.lineTo(182,79);ctx.stroke();
        const map=new THREE.CanvasTexture(canvas);map.colorSpace=THREE.SRGBColorSpace;
        const face=new THREE.Mesh(new THREE.CircleGeometry(.17,32),new THREE.MeshBasicMaterial({map}));face.position.set(-.36,1.56,.27);group.add(face);
        const rim=new THREE.Mesh(new THREE.TorusGeometry(.17,.012,8,32),wood);rim.position.copy(face.position);rim.position.z+=.006;group.add(rim);green(.43,1.35,.25);
      }else{
        rounded(group,.32,.27,.25,.025,M.black,-.42,.965,.23);
        for(let i=0;i<3;i++){box(group,.23,.012,.008,M.metal,-.42,.89+i*.07,.359);box(group,.02,.016,.009,M.blueRug,-.29,.89+i*.07,.36);}
        stack(.04,.84,2);green(.56,.81,.21);print(-.36,1.56,.39,.31);
        box(group,.18,.025,.16,M.metal,.43,1.35,.22);box(group,.018,.27,.018,M.metal,.43,1.49,.22);
        const band=new THREE.Mesh(new THREE.TorusGeometry(.11,.016,8,28,Math.PI),M.black);band.position.set(.43,1.62,.22);group.add(band);
        for(const side of [-1,1])rounded(group,.055,.1,.055,.02,M.black,.43+side*.11,1.6,.22);
      }
      return group;
    }
    function officePartition(parent,w,z){
      wall(parent,w,1.85,.15,0,1.125,z);
      box(parent,w,.045,.17,M.wallTop,0,2.065,z);
    }
    const officeDoors=[],officeSeats=new Map();
    function workstationRoom(name,x,z,w=6.4,d=4.55,turn=0,accessSide=1,theme='engagement'){
      const g=new THREE.Group();g.name=`office-${theme}`;g.position.set(x,0,z);g.rotation.y=turn;scene.add(g);
      officePartition(g,w,-d/2);
      const entry=new THREE.Group();entry.name='office-entry';g.add(entry);
      // Paired sliding leaves keep the complete approach clear, with no swing arc.
      const doorW=1.9,wallSpan=(d-doorW)/2,sideX=accessSide*w/2;
      for(const side of [-1,1]){
        wall(entry,.15,1.85,wallSpan,sideX,1.125,side*(doorW/2+wallSpan/2));
        box(entry,.07,1.88,.045,M.metal,sideX,1.14,side*doorW/2);
        const leaf=new THREE.Group();leaf.position.set(sideX-accessSide*.065,0,side*doorW/4);entry.add(leaf);
        box(leaf,.025,1.77,doorW/2-.03,M.glass,0,1.115,0,{cast:false});
        for(const edge of [-1,1])box(leaf,.035,1.82,.025,M.metal,0,1.14,edge*(doorW/4-.015));
        for(const y of [.23,2.05])box(leaf,.045,.025,doorW/2,M.metal,0,y,0);
        box(leaf,.07,.25,.025,M.brass,-accessSide*.025,1.02,-side*.33);
        officeDoors.push({leaf,axis:'z',closed:side*doorW/4,open:side*(doorW/4+1),x:x+sideX,z});
      }
      box(entry,.17,.045,d,M.wallTop,sideX,2.065,0);
      if(z>0)officePartition(g,w,d/2);
      // One private executive workstation faces the entrance, with clear circulation around it.
      const deskRotation=-accessSide*Math.PI/2,workstation=desk(g,0,0,deskRotation,theme,-accessSide);
      assets.deskNameplate(workstation,theme,{side:-accessSide});
      // Books, a print, and a few personal objects give each private room its own character.
      officeShelving(g,-accessSide*1.7,-d/2+.18,theme);
      box(g,1.48,.86,.045,M.oakLight,0,1.38,-d/2+.11);
      box(g,1.36,.74,.012,assets.wallArtMaterial(theme),0,1.38,-d/2+.14);
      // Keep the plant in the inside corner beside the entrance, clear of the sliding leaves.
      const ficus=createOfficePlant();ficus.position.set(accessSide*(w/2-.72),.21,-d/2+.68);g.add(ficus);
      // A low storage piece balances the tall bookcase, with a restrained personal vignette.
      const storage=new THREE.Group();storage.name='office-credenza';storage.position.set(-accessSide*1.45,0,d/2-.33);g.add(storage);
      rounded(storage,1.7,.62,.43,.025,M.wall,0,.57,0);box(storage,1.76,.045,.47,M.oakLight,0,.902,0);
      for(const side of [-1,1]){
        box(storage,.045,.15,.31,M.metal,side*.65,.28,0);
        box(storage,.18,.012,.018,M.metal,side*.34,.76,-.224);
      }
      box(storage,.012,.54,.012,M.metal,0,.57,-.222);
      for(let i=0;i<2;i++)rounded(storage,.38,.035,.26,.008,i?M.sofaCream:M.blueRug,-.4,.943+i*.04,0);
      cylinder(storage,.065,.11,.23,M.white,.49,1.04,0,24);
      // A compact visitor chair faces the desk, leaving room for the corner plant and access.
      const visitor=createCommonsChair({oak:M.oakLight,upholstery:M.sofaCream,frame:M.metal});
      visitor.name='office-visitor-chair';visitor.scale.set(1.1,1.05,1.18);visitor.position.set(accessSide*1.4,.21,.85);visitor.rotation.y=deskRotation;g.add(visitor);
      visitor.updateWorldMatrix(true,true);const seat=visitor.localToWorld(new THREE.Vector3(0,0,.18));
      officeSeats.set(theme,{x:seat.x,z:seat.z,y:1.13,surfaceY:.751});
      rounded(g,3.5,.012,3.08,.09,officeRug,0,.219,.2);
      addLabel(name,x,z,Math.min(5.5,w-.3));return g
    }
    const executiveDoors=[];
    function boardroom(){
      const g=new THREE.Group();g.position.set(0,0,-9.3);scene.add(g);const w=8.4,d=5.3,h=2.8;
      // Floor-to-ceiling low-iron glass with a quiet, integrated champagne finish.
      const glass=new THREE.MeshPhysicalMaterial({color:0xc9e0df,roughness:.1,metalness:.02,transparent:true,opacity:.1,transmission:0,depthWrite:false,thickness:.1,side:THREE.DoubleSide});
      const frame=material(0x665d50,.48,{metalness:.28});
      wall(g,.055,h,d,-w/2,h/2,0,glass);wall(g,.12,h,d,w/2,h/2,0,glass);
      // Wide sliding entrances sit flush with the glazed facade.
      wall(g,2.6,h,.08,0,h/2,d/2,glass);
      for(const side of [-1,1])wall(g,1,h,.08,side*3.7,h/2,d/2,glass);
      for(const x of [-w/2,w/2])for(const z of [-d/2,0,d/2])box(g,.025,h,.025,frame,x,h/2,z);
      for(const center of [-2.25,2.25])for(const side of [-1,1]){
        const closed=center+side*.475,leaf=new THREE.Group();leaf.position.set(closed,0,d/2+.07);g.add(leaf);
        box(leaf,.92,2.58,.035,glass,0,1.32,0,{cast:false});
        for(const edge of [-1,1])box(leaf,.025,2.62,.04,frame,edge*.462,1.32,0);
        for(const y of [.01,2.63])box(leaf,.95,.025,.04,frame,0,y,0);
        box(leaf,.025,.3,.055,M.brass,-side*.34,1.3,.025);
        executiveDoors.push({leaf,axis:'x',closed,open:closed+side*.96,x:center,z:-9.3+d/2});
      }
      const rug=box(g,6.8,.035,3.9,material(0x8a928b,.96),0,.23,0);rug.castShadow=false;
      const furniture=new THREE.Group();furniture.position.z=-.7;g.add(furniture);
      const boardTop=M.oakLight;
      rounded(furniture,4.25,.17,1.72,.075,boardTop,0,.98,0);
      for(const x of [-1.32,1.32]){
        box(furniture,.17,.66,1.2,boardTop,x,.55,0);
        box(furniture,.42,.075,1.45,M.brass,x,.235,0)
      }
      for(const x of [-1.7,-.55,.55,1.7]){conferenceChair(furniture,x,-1.25,0,M.black);conferenceChair(furniture,x,1.22,Math.PI,M.black)}
      conferenceChair(furniture,-3.05,0,Math.PI/2,M.black);conferenceChair(furniture,3.05,0,-Math.PI/2,M.black);
      assets.boardroomDetails(g,-.7);
      addLabel('Sala de juntas',0,-12.48,4.5)
    }
    function commonLounge(){
      const commons=createCommons({M,box,rounded,cylinder});scene.add(commons);
      addLabel('Espacio común',0,.1,4.1);
    }
    const cutawayFacades=[];
    function architecturalShell(){
      const wallFinish=material(0xe9e9e2,.95),frame=material(0x77817a,.65,{metalness:.25});
      const windowGlass=new THREE.MeshStandardMaterial({color:0xe3eeed,roughness:.12,transparent:true,opacity:.065,depthWrite:false});
      const shell=new THREE.Group();shell.name='office-shell';scene.add(shell);
      function facade(name,normal,origin){
        const group=new THREE.Group();group.name=name;shell.add(group);cutawayFacades.push({group,normal,origin});return group;
      }
      // One building envelope and one floor. Roof and camera-facing upper walls
      // are sectioned visually; their full geometry remains in the navigation map.
      box(shell,22.2,.12,18.45,M.ground,0,.14,-2.975);
      const floor=new THREE.Group();floor.position.z=-2.975;shell.add(floor);assets.floor(floor,22.15,18.4);
      box(shell,22.1,.64,.18,wallFinish,0,.52,-12.1);
      const rear=facade('rear-elevation',new THREE.Vector3(0,0,-1),new THREE.Vector3(0,0,-12.1));
      box(rear,22.1,2.46,.18,wallFinish,0,2.07,-12.1);
      box(shell,22.0,.1,.04,M.white,0,.28,-11.99);
      for(const side of [-1,1]){
        const upper=facade(side>0?'east-windows':'west-windows',new THREE.Vector3(side,0,0),new THREE.Vector3(side*10.95,0,0));
        box(shell,.15,.64,18.35,wallFinish,side*10.95,.52,-2.975);
        box(upper,.045,2.19,18.3,windowGlass,side*10.95,1.935,-2.975,{cast:false});
        box(upper,.17,.12,18.35,wallFinish,side*10.95,3.09,-2.975);
        box(shell,.19,.06,18.35,wallFinish,side*10.95,.87,-2.975);
        for(const z of [-12.1,6.15])box(upper,.07,2.25,.05,frame,side*10.95,1.95,z);
      }
      const front=facade('entrance-elevation',new THREE.Vector3(0,0,1),new THREE.Vector3(0,0,6.15));
      // No low wall stubs across the entrance. The private front walls finish the edge.
      box(front,22,2.8,.035,windowGlass,0,1.63,6.15,{cast:false});
      box(front,22,.08,.12,wallFinish,0,3.08,6.15);
      const strip=material(0xf9f6e9,.6,{emissive:0xfff8e7,emissiveIntensity:.35});
      box(rear,21.5,.035,.12,strip,0,3.04,-11.94);
      return shell;
    }
    function makeStructure(){
      architecturalShell();
      boardroom();
      workstationRoom('Engagement',-7.6,-1.05,6.4,4.75,0,1,'engagement');
      workstationRoom('Arquitectura',7.6,-1.05,6.4,4.75,0,-1,'architecture');
      workstationRoom('FinOps',-7.6,3.7,6.4,4.75,0,1,'finops');
      workstationRoom('Infraestructura',7.6,3.7,6.4,4.75,0,-1,'infrastructure');
      commonLounge();
      assets.coffeeCorner(scene);assets.projectCorner(scene);
    }
    scene.add(new THREE.HemisphereLight(0xf7f8f3,0x9ba69e,1.85));
    const sun=new THREE.DirectionalLight(0xfffbf0,1.35);sun.position.set(-6,16,5);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.normalBias=.025;sun.shadow.camera.left=-18;sun.shadow.camera.right=18;sun.shadow.camera.top=17;sun.shadow.camera.bottom=-20;scene.add(sun);
    const fill=new THREE.DirectionalLight(0xe4eeef,.7);fill.position.set(9,10,-9);scene.add(fill);
    makeStructure();
    for(const {leaf} of [...officeDoors,...executiveDoors])leaf.traverse(object=>{object.castShadow=false});
    const agent=createCloudAgent(),courier=agent.group;
    scene.add(courier,agent.shadow);
    courier.traverse(object=>{object.castShadow=false});
    scene.updateMatrixWorld(true);
    const allDoors=[...officeDoors,...executiveDoors];
    for(const {leaf} of allDoors)leaf.traverse(object=>object.userData.dynamicDoor=true);
    const obstacleBox=new THREE.Box3(),obstacles=[],floorSurfaces=[];
    scene.traverse(object=>{
      if(!object.isMesh||object.userData.dynamicDoor||object===agent.shadow)return;
      let parent=object;while(parent){if(parent===courier)return;parent=parent.parent;}
      obstacleBox.setFromObject(object);
      // Floor finishes, rugs, and overhead rails are outside the walking body.
      if(obstacleBox.max.y<=.27){
        if(obstacleBox.max.y>=.15)floorSurfaces.push({minX:obstacleBox.min.x,maxX:obstacleBox.max.x,minZ:obstacleBox.min.z,maxZ:obstacleBox.max.z,height:obstacleBox.max.y});
        return;
      }
      if(obstacleBox.min.y>=1.6)return;
      obstacles.push({minX:obstacleBox.min.x,maxX:obstacleBox.max.x,minZ:obstacleBox.min.z,maxZ:obstacleBox.max.z});
    });
    // Open leaves still occupy their parking pockets. Include those real
    // footprints so a path cannot graze a panel when entering or leaving.
    for(const door of allDoors){
      door.leaf.position[door.axis]=door.open;door.leaf.updateWorldMatrix(true,true);obstacleBox.setFromObject(door.leaf);
      obstacles.push({minX:obstacleBox.min.x,maxX:obstacleBox.max.x,minZ:obstacleBox.min.z,maxZ:obstacleBox.max.z});
      door.leaf.position[door.axis]=door.closed;door.leaf.updateWorldMatrix(true,true);
    }
    const navigation=createNavigation({bounds:{minX:-10.95,maxX:10.95,minZ:-12.1,maxZ:6.15},obstacles,radius:.8,cellSize:.1});
    const stops=[
      {x:0,z:4.8,pose:'stand',pause:1.4,heading:Math.PI},
      {x:-2.65,z:2.1,pose:'rest',pause:2.2,heading:0},
      {x:-5.85,z:-1.45,pose:'work',pause:OFFICE_VISIT_DURATION,heading:-Math.PI/2,seat:officeSeats.get('engagement')},
      {x:-3,z:-7.55,pose:'meeting',pause:2.2,heading:Math.PI},
      {x:5.85,z:-1.45,pose:'work',pause:OFFICE_VISIT_DURATION,heading:Math.PI/2,seat:officeSeats.get('architecture')},
      {x:5.85,z:3.3,pose:'work',pause:OFFICE_VISIT_DURATION,heading:Math.PI/2,seat:officeSeats.get('infrastructure')},
      {x:-5.85,z:3.3,pose:'work',pause:OFFICE_VISIT_DURATION,heading:-Math.PI/2,seat:officeSeats.get('finops')}
    ];
    const journeys=stops.map((stop,i)=>navigation.plan(stop,stops[(i+1)%stops.length]));
    // Fail early if a layout change blocks any entire leg of the circuit.
    for(const path of journeys)for(let i=1;i<path.length;i++)if(!navigation.segmentClear(path[i-1],path[i]))throw new Error('El recorrido cruza mobiliario.');
    const floorAt=(x,z)=>floorSurfaces.reduce((height,surface)=>x>=surface.minX&&x<=surface.maxX&&z>=surface.minZ&&z<=surface.maxZ?Math.max(height,surface.height):height,.2);
    const groundContact=agent.hoverHeight;
    courier.position.set(stops[0].x,floorAt(stops[0].x,stops[0].z)+groundContact,stops[0].z);courier.rotation.y=stops[0].heading;
    agent.animate({pose:'stand',immediate:true});
    let stopIndex=0,waypointIndex=1,routePause=stops[0].pause,seatPhase=null;
    const dynamicObstacles=[];
    function updateDoors(dt){
      dynamicObstacles.length=0;
      for(const door of allDoors){
        const near=Math.hypot(courier.position.x-door.x,courier.position.z-door.z)<2.5;
        door.leaf.position[door.axis]=THREE.MathUtils.damp(door.leaf.position[door.axis],near?door.open:door.closed,9,dt);
        door.leaf.updateWorldMatrix(true,true);obstacleBox.setFromObject(door.leaf);
        dynamicObstacles.push({minX:obstacleBox.min.x,maxX:obstacleBox.max.x,minZ:obstacleBox.min.z,maxZ:obstacleBox.max.z});
      }
    }
    function moveCourier(dt,time){
      updateDoors(dt);
      let walking=false,pose=stops[stopIndex].pose,desiredHeading=stops[stopIndex].heading,seatPosition=null;
      seatPhase=null;
      if(routePause>0){
        routePause=Math.max(0,routePause-dt);
        const stop=stops[stopIndex];
        if(stop.seat){
          seatPosition=officeSeatMotion(stop,stop.pause-routePause,floorAt(stop.x,stop.z)+groundContact);
          courier.position.set(seatPosition.x,seatPosition.y,seatPosition.z);seatPhase=seatPosition.phase;
          pose=seatPhase==='seated'?'seated':'stand';
        }
      }
      else{
        const path=journeys[stopIndex],target=path[waypointIndex];
        const dx=target.x-courier.position.x,dz=target.z-courier.position.z,distance=Math.hypot(dx,dz),step=Math.min(distance,1.3*dt);
        const next={x:courier.position.x+(distance?dx/distance*step:0),z:courier.position.z+(distance?dz/distance*step:0)};
        // A closing or partly open leaf blocks motion until its real geometry clears.
        if(navigation.segmentClear({x:courier.position.x,z:courier.position.z},next,dynamicObstacles)){
          courier.position.x=next.x;courier.position.z=next.z;walking=distance>.001;
          if(distance<=step+.0001){
            waypointIndex++;
            if(waypointIndex>=path.length){stopIndex=(stopIndex+1)%stops.length;waypointIndex=1;routePause=stops[stopIndex].pause;walking=false;}
          }
        }
        pose=walking?'move':'stand';desiredHeading=Math.atan2(dx,dz);
      }
      const floorY=floorAt(courier.position.x,courier.position.z);
      if(!seatPosition)courier.position.y=THREE.MathUtils.damp(courier.position.y,floorY+groundContact,18,dt);
      const delta=Math.atan2(Math.sin(desiredHeading-courier.rotation.y),Math.cos(desiredHeading-courier.rotation.y));
      courier.rotation.y+=delta*(1-Math.exp(-10*dt));courier.rotation.z=0;
      agent.animate({pose,walking,time,dt});agent.shadow.position.y=seatPhase==='seated'?stops[stopIndex].seat.surfaceY+.01:floorY+.012;
    }
    const officeView=(x,z,side)=>({
      target:new THREE.Vector3(x+side*.4,.8,z),direction:new THREE.Vector3(side,.75,.12).normalize(),
      distance:8.5,individualOffice:true
    });
    const views={
      overview:{target:new THREE.Vector3(0,1,-2),direction:new THREE.Vector3(13,16,24).normalize()},
      engagement:officeView(-7.6,-1.05,1),
      architecture:officeView(7.6,-1.05,-1),
      finops:officeView(-7.6,3.7,1),
      infrastructure:officeView(7.6,3.7,-1),
      boardroom:{target:new THREE.Vector3(0,1,-9.3),distance:18},
      lounge:{target:new THREE.Vector3(0,.9,.1),distance:18}
    };
    let paused=reducedMotion,transition=null,currentView='overview',simulationTime=0,following=false,labelsVisible=false;
    let followingOffset=new THREE.Vector3();
    const followTarget=new THREE.Vector3();
    const bounds=new THREE.Box3(new THREE.Vector3(-11.15,.05,-12.3),new THREE.Vector3(11.15,3.5,6.3));
    function fitDistance(direction,target,frame=bounds,padding=1.12){
      const right=new THREE.Vector3().crossVectors(camera.up,direction).normalize();
      const up=new THREE.Vector3().crossVectors(direction,right).normalize();
      const tanV=Math.tan(THREE.MathUtils.degToRad(camera.fov/2)),tanH=tanV*camera.aspect;
      let distance=0;
      for(const x of [frame.min.x,frame.max.x])for(const y of [frame.min.y,frame.max.y])for(const z of [frame.min.z,frame.max.z]){
        const relative=new THREE.Vector3(x,y,z).sub(target),depth=relative.dot(direction);
        distance=Math.max(distance,depth+Math.abs(relative.dot(right))/tanH,depth+Math.abs(relative.dot(up))/tanV)
      }
      return Math.min(controls.maxDistance,distance*padding)
    }
    function goTo(view='overview',immediate=false,top=false){
      setFollowing(false);
      const selected=views[view]||views.overview;currentView=view;needsRender=true;
      const direction=top?new THREE.Vector3(0,Math.cos(controls.minPolarAngle),Math.sin(controls.minPolarAngle)):(selected.direction||views.overview.direction);
      const distance=selected.individualOffice?selected.distance/Math.min(1,camera.aspect):view==='overview'?fitDistance(direction,selected.target):selected.distance;
      const position=selected.target.clone().addScaledVector(direction,distance);
      if(immediate||matchMedia('(prefers-reduced-motion: reduce)').matches){camera.position.copy(position);controls.target.copy(selected.target);controls.update();transition=null}
      else transition={position,target:selected.target.clone()};
    }
    function setFollowing(value){
      if(following===value)return;following=value;needsRender=true;onFollowChange(value);
      if(value){
        currentView='agent';transition=null;
        followingOffset.set(Math.sin(courier.rotation.y)*.8,.65,Math.cos(courier.rotation.y)*.8).normalize().multiplyScalar(8);
        if(matchMedia('(prefers-reduced-motion: reduce)').matches){followTarget.copy(courier.position).add(new THREE.Vector3(0,.35,0));controls.target.copy(followTarget);camera.position.copy(followTarget).add(followingOffset);controls.update()}
      }
    }
    controls.addEventListener('start',()=>{transition=null;setFollowing(false)});
    controls.addEventListener('change',()=>{needsRender=true});
    function zoom(factor){transition=null;if(following){followingOffset.setLength(THREE.MathUtils.clamp(followingOffset.length()*factor,controls.minDistance,controls.maxDistance));needsRender=true;return;}const offset=camera.position.clone().sub(controls.target);offset.setLength(THREE.MathUtils.clamp(offset.length()*factor,controls.minDistance,controls.maxDistance));camera.position.copy(controls.target).add(offset);controls.update()}
    function resize(){
      const w=Math.max(1,root.clientWidth),h=Math.max(1,root.clientHeight);
      renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();needsRender=true;
      if(currentView==='overview'||views[currentView]?.individualOffice)goTo(currentView,true);
    }
    const observer=new ResizeObserver(resize);observer.observe(root);resize();
    const clock=new THREE.Clock();
    const labelPosition=new THREE.Vector3();
    function updateLabels(){
      camera.updateMatrixWorld();
      for(const facade of cutawayFacades)facade.group.visible=camera.position.clone().sub(facade.origin).dot(facade.normal)<=.05;
      const pixelScale=2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))/Math.max(1,root.clientHeight);
      const maxWidth=root.clientWidth<600?108:142;
      for(const label of scene.children.filter(child=>child.isSprite)){
        labelPosition.copy(label.position).applyMatrix4(camera.matrixWorldInverse);
        label.visible=labelsVisible&&!following&&labelPosition.z<-.1;
        const width=maxWidth*Math.max(.1,-labelPosition.z)*pixelScale;
        label.scale.set(width,width*.25,1);
      }
    }
    function render(){
      const dt=Math.min(clock.getDelta(),.05);
      if(!paused){simulationTime+=dt;moveCourier(dt,simulationTime)}
      if(transition){camera.position.lerp(transition.position,1-Math.exp(-7*dt));controls.target.lerp(transition.target,1-Math.exp(-7*dt));if(camera.position.distanceTo(transition.position)<.015){camera.position.copy(transition.position);controls.target.copy(transition.target);transition=null}}
      if(following){
        followTarget.copy(courier.position);followTarget.y+=.35;
        const destination=followTarget.clone().add(followingOffset);
        if(camera.position.distanceTo(destination)>.001||controls.target.distanceTo(followTarget)>.001){
          camera.position.lerp(destination,1-Math.exp(-6*dt));controls.target.lerp(followTarget,1-Math.exp(-6*dt));needsRender=true;
        }
      }
      const animating=!paused||Boolean(transition);
      controls.update();if(animating||needsRender){updateLabels();renderer.render(scene,camera);needsRender=false}
    }
    function visibility(){needsRender=true;clock.getDelta();renderer.setAnimationLoop(document.hidden?null:render)}
    document.addEventListener('visibilitychange',visibility);
    renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();renderer.setAnimationLoop(null);onContextLost()});
    renderer.domElement.addEventListener('keydown',event=>{
      if(event.key==='+'||event.key==='='){event.preventDefault();zoom(.85)}
      else if(event.key==='-'){event.preventDefault();zoom(1.18)}
      else if(event.key==='Home'){event.preventDefault();goTo('overview')}
      else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){
        event.preventDefault();transition=null;setFollowing(false);
        const spherical=new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
        spherical.theta+=event.key==='ArrowLeft'?.12:event.key==='ArrowRight'?-.12:0;
        spherical.phi=THREE.MathUtils.clamp(spherical.phi+(event.key==='ArrowUp'?-.1:event.key==='ArrowDown'?.1:0),controls.minPolarAngle,controls.maxPolarAngle);
        camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(spherical));controls.update()
      }
    });
    visibility();
    return {
      goTo,zoom,followCourier:setFollowing,
      inspectNavigation(){return {radius:navigation.radius,obstacles:navigation.obstacles,doors:dynamicObstacles,journeys,stops,position:{x:courier.position.x,z:courier.position.z},height:courier.position.y,seatPhase,stopIndex,waypointIndex,pause:routePause}},
      stepSimulation(dt){simulationTime+=dt;moveCourier(dt,simulationTime);needsRender=true},
      setPaused(value){paused=value;needsRender=true},
      setLabels(value){needsRender=true;labelsVisible=value},
      topView(){goTo('overview',false,true)}
    };
    }
