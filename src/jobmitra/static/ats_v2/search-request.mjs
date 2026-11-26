// Invalidate immediately when the query changes, including the debounce interval.
export function searchRequest({delay=220,schedule=setTimeout,cancel=clearTimeout}={}){
 let epoch=0,timer;
 return {
  invalidate(){++epoch;cancel(timer);timer=undefined;},
  later(run){this.invalidate();timer=schedule(()=>{timer=undefined;run();},delay);},
  begin(){this.invalidate();return epoch;},
  current(ticket){return ticket===epoch;},
 };
}
