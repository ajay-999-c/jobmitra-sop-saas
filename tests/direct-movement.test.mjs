import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import {parse} from '@babel/parser';
import traverse from '@babel/traverse';
import {matchingOptions} from '../src/jobmitra/static/ats_v2/searchable-select.mjs';
import {stagePresentation} from '../src/jobmitra/static/ats_v2/jd-clean.mjs';

test('stage selector filters all configured destinations by case-insensitive partial words',()=>{
 const rows=Array.from({length:75},(_,i)=>({value:'ROUND:'+i,label:'Custom Interview Panel '+i}));
 assert.equal(matchingOptions(rows,' panel 74 ')[0].value,'ROUND:74');
 assert.equal(matchingOptions(rows,'CUSTOM 74')[0].value,'ROUND:74');
 assert.equal(matchingOptions(rows,'no match').length,0);
 assert.equal(matchingOptions([{value:'retired',label:'Retired',disabled:true}],'').length,0);
});
test('existing cumulative/completion helpers count each direct-move membership once',()=>{
 const source=fs.readFileSync('src/jobmitra/static/ats_v2/approved-jd.mjs','utf8'),names=new Set(['refStage','progression','lastReachedIndex','stageVisited','stageEventsAt','stageDecision','stageRows','stageCount','stagePending']),helpers=[];
 traverse(parse(source,{sourceType:'module'}),{VariableDeclarator(p){if(names.has(p.node.id.name)){helpers.push('const '+source.slice(p.node.start,p.node.end)+';');names.delete(p.node.id.name);}}});assert.equal(names.size,0);
 const path=['POOL','CONTACT','SCREENING','COMPANY_SUBMISSION','ROUND:one','ROUND:two','ROUND:three'],candidate={id:'7',stageId:'three',addedAt:'2026-01-01T00:00:00Z',journey:path.slice(1).map((key,i)=>({type:'MOVED',fromKey:path[i],toKey:key,at:'2026-01-01T00:00:00Z'}))};
 const draft={rounds:[{id:'one',name:'Portfolio'},{id:'two',name:'Custom Panel'},{id:'three',name:'Owner Discussion'}],candidates:[candidate,{id:'8',stageKey:'CONTACT',journey:[]}]};
 const ctx=vm.createContext({draft,stageOf:c=>c.stageId?'ROUND:'+c.stageId:c.stageKey,stageDefs:()=>[...path,'SELECTED','JOINED'].map(key=>({key}))});
 vm.runInContext(helpers.join('\n')+';globalThis.metrics={counts:progression().map(k=>stageCount(k)),pending:progression().map(k=>stagePending(k)),past:progression().slice(0,6).map(k=>stageDecision(draft.candidates[0],k))};',ctx);
 assert.deepEqual(Array.from(ctx.metrics.counts),[2,2,1,1,1,1,1,0,0]);assert.deepEqual(Array.from(ctx.metrics.pending),[0,1,0,0,0,0,1,0,0]);assert.ok(ctx.metrics.past.every(x=>x==='ADVANCED'));
 assert.equal(stagePresentation({stageOf:()=> 'ROUND:three',stage:'ROUND:one',decision:()=>ctx.metrics.past[4],label:()=> 'Owner Discussion'},candidate).label,'Stage completed');
});
