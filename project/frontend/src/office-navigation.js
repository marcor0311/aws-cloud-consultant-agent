// Plan and validate circulation using the same footprint at planning and movement time.
export function createNavigation({bounds,obstacles,radius=.8,cellSize=.1}) {
  const width=Math.floor((bounds.maxX-bounds.minX)/cellSize)+1;
  const height=Math.floor((bounds.maxZ-bounds.minZ)/cellSize)+1;
  const blocked=new Uint8Array(width*height);
  const point=(x,z)=>({x:bounds.minX+x*cellSize,z:bounds.minZ+z*cellSize});
  const index=(x,z)=>z*width+x;
  function hits(x,z,rect,padding=radius){
    const dx=Math.max(rect.minX-x,0,x-rect.maxX),dz=Math.max(rect.minZ-z,0,z-rect.maxZ);
    return dx*dx+dz*dz<padding*padding;
  }
  function clear(x,z,extra=[]){
    if(x<bounds.minX+radius||x>bounds.maxX-radius||z<bounds.minZ+radius||z>bounds.maxZ-radius)return false;
    return !obstacles.some(rect=>hits(x,z,rect))&&!extra.some(rect=>hits(x,z,rect));
  }
  for(const rect of obstacles){
    const x0=Math.max(0,Math.floor((rect.minX-radius-bounds.minX)/cellSize));
    const x1=Math.min(width-1,Math.ceil((rect.maxX+radius-bounds.minX)/cellSize));
    const z0=Math.max(0,Math.floor((rect.minZ-radius-bounds.minZ)/cellSize));
    const z1=Math.min(height-1,Math.ceil((rect.maxZ+radius-bounds.minZ)/cellSize));
    for(let z=z0;z<=z1;z++)for(let x=x0;x<=x1;x++){const p=point(x,z);if(hits(p.x,p.z,rect))blocked[index(x,z)]=1;}
  }
  const free=(x,z)=>x>=0&&x<width&&z>=0&&z<height&&!blocked[index(x,z)]&&x*cellSize>=radius&&z*cellSize>=radius&&(width-1-x)*cellSize>=radius&&(height-1-z)*cellSize>=radius;
  function segmentClear(a,b,extra=[]){
    const steps=Math.max(1,Math.ceil(Math.hypot(b.x-a.x,b.z-a.z)/(cellSize*.4)));
    for(let i=0;i<=steps;i++){const t=i/steps;if(!clear(a.x+(b.x-a.x)*t,a.z+(b.z-a.z)*t,extra))return false;}
    return true;
  }
  // Binary heap keeps full-office path planning inexpensive.
  function plan(start,goal){
    if(!clear(start.x,start.z)||!clear(goal.x,goal.z))throw new Error(`Un punto del recorrido no tiene espacio suficiente: ${JSON.stringify({start,goal,blocking:obstacles.filter(r=>hits(start.x,start.z,r)||hits(goal.x,goal.z,r))})}`);
    const sx=Math.round((start.x-bounds.minX)/cellSize),sz=Math.round((start.z-bounds.minZ)/cellSize);
    const gx=Math.round((goal.x-bounds.minX)/cellSize),gz=Math.round((goal.z-bounds.minZ)/cellSize);
    if(!free(sx,sz)||!free(gx,gz))throw new Error('Un destino queda fuera de los pasillos.');
    const begin=index(sx,sz),end=index(gx,gz),cost=new Float64Array(width*height).fill(Infinity),parent=new Int32Array(width*height).fill(-1),closed=new Uint8Array(width*height),heap=[];
    const heuristic=(x,z)=>Math.hypot(gx-x,gz-z);
    function push(node){heap.push(node);let i=heap.length-1;while(i>0){const p=(i-1)>>1;if(heap[p].f<=node.f)break;heap[i]=heap[p];i=p;}heap[i]=node;}
    function pop(){const root=heap[0],last=heap.pop();if(heap.length){let i=0;while(i*2+1<heap.length){let c=i*2+1;if(c+1<heap.length&&heap[c+1].f<heap[c].f)c++;if(heap[c].f>=last.f)break;heap[i]=heap[c];i=c;}heap[i]=last;}return root;}
    cost[begin]=0;push({id:begin,x:sx,z:sz,f:heuristic(sx,sz)});
    while(heap.length){
      const node=pop();if(closed[node.id])continue;closed[node.id]=1;if(node.id===end)break;
      for(const [dx,dz] of [[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]]){
        const x=node.x+dx,z=node.z+dz;if(!free(x,z)||dx&&dz&&(!free(node.x+dx,node.z)||!free(node.x,node.z+dz)))continue;
        const id=index(x,z),next=cost[node.id]+Math.hypot(dx,dz);
        if(next<cost[id]){cost[id]=next;parent[id]=node.id;push({id,x,z,f:next+heuristic(x,z)});}
      }
    }
    if(!Number.isFinite(cost[end]))throw new Error(`No hay un acceso despejado: ${JSON.stringify({start,goal})}`);
    const points=[];for(let id=end;id!==-1;id=parent[id])points.push(point(id%width,Math.floor(id/width)));points.reverse();
    points[0]={x:start.x,z:start.z};points[points.length-1]={x:goal.x,z:goal.z};
    // Never cut across a corner while smoothing the grid route.
    const result=[points[0]];let at=0;
    while(at<points.length-1){let next=at+1;for(let i=points.length-1;i>at;i--)if(segmentClear(points[at],points[i])){next=i;break;}if(!segmentClear(points[at],points[next]))throw new Error('El segmento de navegación no es seguro.');result.push(points[next]);at=next;}
    return result;
  }
  return {plan,clear,segmentClear,radius,obstacles,bounds};
}
