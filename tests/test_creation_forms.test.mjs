import {test} from 'node:test';
import assert from 'node:assert/strict';
import {creationScope,submitCreation} from '../src/jobmitra/static/ats_v2/creation-forms.mjs';
function form(){
 const button={disabled:false};
 return {button,querySelectorAll:s=>s.startsWith('button')?[button]:[],setAttribute(){},removeAttribute(){}};
}
test('unchanged retries replay while corrected bodies and distinct operations get different scopes',async()=>{
 const f=form(),calls=[];
 const native={async api(...args){calls.push(args);return {id:calls.length};}};
 const run=body=>submitCreation(f,'candidate',s=>s.request(native,'/register',body));
 assert.deepEqual(await run({name:'A'}),{id:1});
 assert.deepEqual(await run({name:'A'}),{id:1});
 assert.deepEqual(await run({name:'B'}),{id:2});
 assert.equal(calls.length,2);
 assert.notEqual(calls[0][4],calls[1][4]);
 assert.notEqual(creationScope('/register','POST',{}),creationScope('/jobs','POST',{}));
 assert.notEqual(creationScope('/jobs','POST',{}),creationScope('/jobs','PATCH',{}));
});
test('in-flight clicks and a replacement form cannot submit twice; buttons are restored',async()=>{
 const f=form();let release,posts=0;
 const pending=new Promise(resolve=>release=resolve);
 const first=submitCreation(f,'jd',async()=>{posts++;await pending;return 7;});
 assert.equal(f.button.disabled,true);
 assert.equal(await submitCreation(f,'jd',()=>posts++),null);
 assert.equal(await submitCreation(form(),'jd',()=>posts++),null);
 release();assert.equal(await first,7);assert.equal(posts,1);assert.equal(f.button.disabled,false);
 assert.equal(await submitCreation(f,'jd',()=>8),8);
});
test('invalid submission releases its lock without posting and can be corrected',async()=>{
 const f=form();let posts=0;
 assert.equal(await submitCreation(f,'candidate',()=>undefined),undefined);
 assert.equal(f.button.disabled,false);
 await submitCreation(f,'candidate',()=>++posts);
 assert.equal(posts,1);
});
