import {test} from 'node:test';
import assert from 'node:assert/strict';
import {officeSeatMotion,OFFICE_VISIT_DURATION} from '../assets/office-seat-motion.js';

const stop={x:-5.85,z:-1.55,seat:{x:-6.158,z:.13,y:1.13}},groundY=.755;

test('clears the chair back before moving horizontally into or out of the seat',()=>{
  let previous=officeSeatMotion(stop,0,groundY);
  for(let t=.01;t<=OFFICE_VISIT_DURATION;t+=.01){
    const current=officeSeatMotion(stop,t,groundY);
    if(Math.hypot(current.x-previous.x,current.z-previous.z)>1e-7){
      assert.ok(current.y>=1.72-1e-9);assert.ok(previous.y>=1.72-1e-9);
    }
    assert.ok(Math.hypot(current.x-previous.x,current.y-previous.y,current.z-previous.z)<.04,'No jump between phases');
    previous=current;
  }
});

test('rests at the chair and rejoins the exact walking stop before the next journey',()=>{
  const seated=officeSeatMotion(stop,3,groundY);
  assert.deepEqual(seated,{...stop.seat,phase:'seated'});
  const done=officeSeatMotion(stop,OFFICE_VISIT_DURATION,groundY);
  assert.deepEqual(done,{x:stop.x,y:groundY,z:stop.z,phase:'stand'});
  const mirrored={x:-stop.x,z:stop.z,seat:{...stop.seat,x:-stop.seat.x}};
  const right=officeSeatMotion(mirrored,3,groundY);
  assert.deepEqual(right,{...mirrored.seat,phase:'seated'});
});
