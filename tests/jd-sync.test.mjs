import test from 'node:test';
import assert from 'node:assert/strict';
import {createSynchronizer} from '../src/jobmitra/static/ats_v2/jd-sync.mjs';

test('hidden tabs do not read and overlapping ticks share one read plus one follow-up',async()=>{
 let visible=false,calls=0,resolve,timer;
 const sync=createSynchronizer({visible:()=>visible,read:()=>{calls++;return new Promise(r=>resolve=r);},setTimer:fn=>{timer=fn;return 1;},clearTimer:()=>{}});
 await sync.tick();assert.equal(calls,0);visible=true;
 const first=sync.tick();await Promise.resolve();void sync.tick();void sync.tick();
 assert.equal(calls,1);resolve();await first;await Promise.resolve();assert.equal(calls,2);
 resolve();await Promise.resolve();sync.stop();assert.ok(!timer||typeof timer==='function');
});
test('read failures are reported and polling can resume without overlapping',async()=>{
 let calls=0,message='',timer;
 const sync=createSynchronizer({visible:()=>true,read:async()=>{calls++;if(calls===1)throw Error('Network unavailable');},onError:e=>message=e.message,setTimer:fn=>{timer=fn;return 1;},clearTimer:()=>{}});
 await sync.tick();assert.equal(message,'Network unavailable');await timer();assert.equal(calls,2);sync.stop();
});

test('scoped reads deduplicate and a late pre-mutation response cannot overwrite a newer result',async()=>{
 globalThis.window={addEventListener(){},dispatchEvent(){}};
 globalThis.document={querySelector:()=>null};
 const {native}=await import('../src/jobmitra/static/ats_v2/approved-api.mjs');
 const requests=[];const previous=globalThis.fetch;
 globalThis.fetch=()=>new Promise(resolve=>requests.push(resolve));
 const client=Object.create(native);client.applyState=function(s){this.snapshot=s;};
 const payload=title=>({jobs:[{id:1,title}],candidates:[],companies:[],events:[],activities:[],placements:[],resumes:[],poll_seconds:15});
 const response=title=>({ok:true,status:200,headers:new Headers({ETag:'"'+title+'"'}),json:async()=>payload(title)});
 try{
  const first=client.refreshJD(1),duplicate=client.refreshJD(1);assert.equal(requests.length,1);
  client.readEpoch=1;const newer=client.refreshJD(1,{force:true});assert.equal(requests.length,2);
  requests[1](response('Newer'));await newer;requests[0](response('Older'));await first;await duplicate;
  assert.equal(client.snapshot.jobs[0].title,'Newer');
  const unchanged=client.refreshJD(1);requests[2]({status:304});assert.equal(await unchanged,false);
 }finally{globalThis.fetch=previous;delete globalThis.window;delete globalThis.document;}
});
