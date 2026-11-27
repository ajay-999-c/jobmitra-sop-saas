// One visible-workspace read at a time. No browser reloads or draft persistence.
export function createSynchronizer({read,visible,onError=()=>{},interval=()=>15000,setTimer=setTimeout,clearTimer=clearTimeout}){
 let timer=null,running=null,stopped=false,again=false;
 const schedule=()=>{clearTimer(timer);if(!stopped&&visible())timer=setTimer(tick,interval());};
 async function tick(){
  clearTimer(timer);if(stopped||!visible())return false;
  if(running){again=true;return running;}
  running=Promise.resolve().then(read).catch(onError).finally(()=>{running=null;if(again){again=false;void tick();}else schedule();});
  return running;
 }
 return{tick,start(){stopped=false;schedule();},pause(){clearTimer(timer);},stop(){stopped=true;clearTimer(timer);},running:()=>!!running};
}
export function installJDSync(native,bridge){
 const visible=()=>!document.hidden&&!document.getElementById('jdHost')?.hidden&&bridge.active();
 const sync=createSynchronizer({visible,interval:()=>Math.max(5,native.pollSeconds||15)*1000,
  read:async()=>{if(bridge.view()==='dashboard')await native.jdDashboard?.refresh();else if(bridge.id())await native.refreshJD(bridge.id());bridge.error('');},
  onError:error=>bridge.error(error.message)});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)sync.pause();else void sync.tick();});
 window.addEventListener('focus',()=>void sync.tick());
 window.addEventListener('jobmitra-workspace-visible',()=>void sync.tick());
 const nav=document.querySelector('[aria-label="Recruitment workspaces"]');if(nav)new MutationObserver(()=>{if(visible())void sync.tick();else sync.pause();}).observe(nav,{subtree:true,attributes:true,attributeFilter:['aria-selected']});
 sync.start();return sync;
}
