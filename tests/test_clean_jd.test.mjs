import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {allocation,salaryLabel,experienceLabel,linkedRows,createPoolAttacher} from '../src/jobmitra/static/ats_v2/jd-clean.mjs';
import {cleanJDStyles} from '../scripts/v12-clean-jd.mjs';

test('eligibility keeps blocked profiles visible and current-JD links distinct',()=>{
 const job={id:'8',status:'ACTIVE',candidates:[{id:'4'}]};
 assert.equal(allocation({id:4},job).label,'Already added');
 assert.equal(allocation({id:5,can_allocate:true},job).allowed,true);
 for(const eligibility of ['PLACED_LOCKED','SELECTED_ON_HOLD'])assert.match(allocation({id:5,can_allocate:false,allocation_eligibility:eligibility},job).reason,/joining|Selected/);
 assert.equal(allocation({id:5,can_allocate:true},{...job,status:'CLOSED'}).allowed,false);
});
test('salary and experience keep recorded precision, basis, period and unknowns',()=>{
 assert.equal(salaryLabel({expected_salary_inr:'123456.789',expected_salary_period:'ANNUAL',expected_salary_basis:'GROSS'}),'₹1,23,456.789 / year · gross');
 assert.equal(salaryLabel({}),'Not recorded');
 assert.match(salaryLabel({expected_salary_inr:0}),/period not recorded · basis not recorded/);
 assert.equal(experienceLabel({experience_months:38}),'3 yr 2 mo');
 assert.equal(experienceLabel({}),'Not recorded');
});
test('stage filters retain distinct closures and advanced history',()=>{
 const rows=['SCREENING','SELECTED','JOINED','NOT_SELECTED','NOT_JOINED','SELECTION_CANCELLED'].map(stage=>({stage}));
 const ctx={stage:'SCREENING',reached:()=>rows,stageOf:c=>c.stage};
 assert.deepEqual(linkedRows(ctx,'here'),[rows[0]]);
 assert.equal(linkedRows(ctx,'reached').length,6);
 assert.deepEqual(linkedRows(ctx,'selected'),rows.slice(1,3));
 assert.deepEqual(linkedRows(ctx,'closed'),rows.slice(3));
});
test('double click shares one request and success requires canonical readback',async()=>{
 let resolve,calls=0;
 const native={jobs:[{id:'9',candidates:[]}],addToPool:async()=>{calls++;await new Promise(r=>{resolve=r;});native.jobs[0].candidates.push({id:'2'});}};
 const add=createPoolAttacher(native),first=add(2,9),second=add('2','9');
 assert.equal(first,second);resolve();assert.equal((await first).id,'2');assert.equal(calls,1);
 await assert.rejects(createPoolAttacher({jobs:[],addToPool:async()=>{}})(2,9),/not confirmed/);
});
test('uncertain failure retries with the same idempotency owner',async()=>{
 const owners=[];const native={jobs:[{id:'9',candidates:[{id:'2'}]}],addToPool:async(c,j,owner)=>{owners.push(owner);if(owners.length===1)throw Error('Network interrupted');}};
 const add=createPoolAttacher(native);await assert.rejects(add(2,9),/interrupted/);await add(2,9);assert.equal(owners[0],owners[1]);
});
test('generated CSS is scoped and preserves reference palette and stage sizing',()=>{
 const css=cleanJDStyles();assert.equal(css,fs.readFileSync('src/jobmitra/static/ats_v2/jd-clean.css','utf8'));
 for(const value of ['#d51e29','#b71924','#203046','#65768b','#f1f6fc','#7099d6','#f5f1fc','#9775d5','#eaf8f0','#3ca779','#187653','min-width:128px','min-height:102px'])assert.ok(css.includes(value));
 assert.ok(!/(^|\})\s*(body|:root|\.stage)[{\s]/.test(css));
});
