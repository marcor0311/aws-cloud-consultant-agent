// The cloud rises above the chair before approaching and returns to the clear
// walking stop before navigation resumes. Coordinates are in world space.
export const OFFICE_VISIT_DURATION=7.2;
export function officeSeatMotion(stop,elapsed,groundY){
  const approach={x:stop.x,y:groundY,z:stop.z},seat=stop.seat;
  const aboveApproach={...approach,y:1.72},aboveSeat={...seat,y:1.72};
  const phases=[
    [.7,approach,aboveApproach,'rise'],
    [1,aboveApproach,aboveSeat,'approach'],
    [.65,aboveSeat,seat,'settle'],
    [2,seat,seat,'seated'],
    [.65,seat,aboveSeat,'rise'],
    [1,aboveSeat,aboveApproach,'return'],
    [.7,aboveApproach,approach,'land']
  ];
  let remaining=Math.max(0,elapsed);
  for(const [duration,from,to,phase] of phases){
    if(remaining<=duration){
      const t=remaining/duration,ease=t*t*(3-2*t);
      return {x:from.x+(to.x-from.x)*ease,y:from.y+(to.y-from.y)*ease,z:from.z+(to.z-from.z)*ease,phase};
    }
    remaining-=duration;
  }
  return {...approach,phase:'stand'};
}
