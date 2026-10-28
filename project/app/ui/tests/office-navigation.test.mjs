import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createNavigation} from '../assets/office-navigation.js';

const bounds={minX:-6,maxX:6,minZ:-6,maxZ:6};
const wall=(minZ,maxZ)=>({minX:-.08,maxX:.08,minZ,maxZ});

test('plans a full detour and preserves clearance along each smoothed segment',()=>{
  const nav=createNavigation({bounds,obstacles:[{minX:-1,maxX:1,minZ:-2,maxZ:2}],radius:.8});
  const start={x:-4,z:0},end={x:4,z:0},path=nav.plan(start,end);
  assert.ok(path.length>2);
  assert.deepEqual(path[0],start);assert.deepEqual(path.at(-1),end);
  for(let i=1;i<path.length;i++)assert.ok(nav.segmentClear(path[i-1],path[i]));
  assert.equal(nav.segmentClear(start,end),false);
});

test('rejects an opening that is narrower than the walking footprint',()=>{
  const nav=createNavigation({bounds,obstacles:[wall(-6,-.6),wall(.6,6)],radius:.8});
  assert.throws(()=>nav.plan({x:-3,z:0},{x:3,z:0}),/acceso despejado/);
});

test('wide entrances remain traversable after accounting for open door pockets',()=>{
  const nav=createNavigation({bounds,obstacles:[wall(-6,-.95),wall(.95,6),{minX:-.15,maxX:-.1,minZ:1,maxZ:2}],radius:.8});
  const path=nav.plan({x:-3,z:0},{x:3,z:0});
  for(let i=1;i<path.length;i++)assert.ok(nav.segmentClear(path[i-1],path[i]));
});

test('waits for a real sliding leaf to clear the passage',()=>{
  const nav=createNavigation({bounds,obstacles:[wall(-6,-.95),wall(.95,6)],radius:.8});
  const a={x:-1,z:0},b={x:1,z:0};
  assert.equal(nav.segmentClear(a,b,[{minX:-.04,maxX:.04,minZ:-.94,maxZ:.94}]),false);
  assert.equal(nav.segmentClear(a,b,[{minX:-.04,maxX:.04,minZ:-1.94,maxZ:-1.02},{minX:-.04,maxX:.04,minZ:1.02,maxZ:1.94}]),true);
});

test('does not use the edge of the office to bypass a solid wall',()=>{
  const nav=createNavigation({bounds,obstacles:[wall(-6,6)],radius:.8});
  assert.throws(()=>nav.plan({x:-3,z:0},{x:3,z:0}),/acceso despejado/);
});

test('refuses a destination inside furniture or outside the floor',()=>{
  const nav=createNavigation({bounds,obstacles:[{minX:1,maxX:2,minZ:1,maxZ:2}],radius:.8});
  assert.throws(()=>nav.plan({x:0,z:-2},{x:1.5,z:1.5}),/espacio suficiente/);
  assert.equal(nav.clear(5.5,0),false);
});
