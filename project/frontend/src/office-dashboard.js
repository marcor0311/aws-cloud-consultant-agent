const $=selector=>document.querySelector(selector);
const viewButtons=[...document.querySelectorAll('[data-view]')];
let scene,paused=matchMedia('(prefers-reduced-motion: reduce)').matches;
function selectView(view,move=true){
  if(move)scene?.followCourier(false);
  for(const button of viewButtons){const selected=button.dataset.view===view;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected));}
  if(move)scene?.goTo(view);
}
function updatePause(){
  scene?.setPaused(paused);
  $('#pause').setAttribute('aria-pressed',String(paused));
  $('#pause').setAttribute('aria-label',paused?'Reanudar':'Pausar');
  $('#pause').title=paused?'Reanudar':'Pausar';
  $('#pause-icon').textContent=paused?'▷':'Ⅱ';
}
function showError(title,description){
  $('#load-state').hidden=false;$('#loader').hidden=true;
  $('#load-title').textContent=title;$('#load-description').textContent=description;
  $('#retry').hidden=false;$('#office').setAttribute('aria-busy','false');
  document.querySelectorAll('.toolbar button:not(#help)').forEach(button=>button.disabled=true);
}
viewButtons.forEach(button=>button.addEventListener('click',()=>selectView(button.dataset.view)));
$('#zoom-in').addEventListener('click',()=>scene?.zoom(.82));
$('#zoom-out').addEventListener('click',()=>scene?.zoom(1.22));
$('#reset').addEventListener('click',()=>selectView('overview'));
$('#top-view').addEventListener('click',()=>{selectView('overview',false);scene?.topView();});
$('#labels').addEventListener('click',()=>{const visible=$('#labels').getAttribute('aria-pressed')!=='true';$('#labels').setAttribute('aria-pressed',String(visible));scene?.setLabels(visible);});
$('#follow-agent').addEventListener('click',()=>scene?.followCourier($('#follow-agent').getAttribute('aria-pressed')!=='true'));
$('#pause').addEventListener('click',()=>{paused=!paused;updatePause();});
$('#retry').addEventListener('click',()=>location.reload());
function showHelp(open,returnFocus=false){$('#help-panel').hidden=!open;$('#help').setAttribute('aria-expanded',String(open));if(open)$('#close-help').focus();else if(returnFocus)$('#help').focus();}
$('#help').addEventListener('click',()=>showHelp($('#help-panel').hidden));
$('#close-help').addEventListener('click',()=>showHelp(false,true));
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('#help-panel').hidden)showHelp(false,true);});
document.addEventListener('pointerdown',event=>{if(!$('#help-panel').hidden&&!$('#help-panel').contains(event.target)&&!$('#help').contains(event.target))showHelp(false);});
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',event=>{if(event.matches){paused=true;updatePause();}});
updatePause();
try{
  const {createOffice}=await import('./office-scene.js');
  scene=createOffice($('#office'),{
    onFollowChange:following=>{
      $('#follow-agent').setAttribute('aria-pressed',String(following));
      $('#follow-agent').setAttribute('aria-label',following?'Dejar de seguir':'Seguir agente');
      $('#follow-agent').title=following?'Dejar de seguir':'Seguir agente';
      if(following)viewButtons.forEach(button=>{button.classList.remove('active');button.setAttribute('aria-pressed','false');});
      else selectView('overview',false);
    },
    onContextLost:()=>showError('La vista 3D se ha interrumpido','Vuelve a cargar la oficina para recuperar la conexión gráfica.')
  });
  scene.setPaused(paused);scene.goTo(viewButtons.find(button=>button.getAttribute('aria-pressed')==='true')?.dataset.view||'overview',true);
  $('#load-state').hidden=true;$('#office').setAttribute('aria-busy','false');
  document.querySelectorAll('.toolbar button').forEach(button=>button.disabled=false);
}catch(error){console.error('No se pudo iniciar la oficina:',error);showError('No pudimos abrir la oficina','Comprueba tu conexión y que la aceleración gráfica esté disponible. Luego vuelve a intentarlo.');}
