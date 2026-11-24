import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,randomBytes,webcrypto} from 'node:crypto';
import {uuid,sha256} from '../src/jobmitra/static/ats_v2/crypto.mjs';

test('plain-HTTP fallbacks retain exact SHA-256 and cryptographic UUID v4',async()=>{
 const original=Object.getOwnPropertyDescriptor(globalThis,'crypto');
 try{
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:webcrypto.getRandomValues.bind(webcrypto)}});
  for(const data of [Buffer.alloc(0),Buffer.from('abc'),Buffer.from('Résumé ₹\r\n'),randomBytes(55),randomBytes(56),randomBytes(64),randomBytes(131073),randomBytes(10*1024*1024)]){
   const bytes=Uint8Array.from(data).buffer;
   assert.equal(await sha256(bytes),createHash('sha256').update(data).digest('hex'));
  }
  const ids=new Set(Array.from({length:1000},uuid));assert.equal(ids.size,1000);
  for(const id of ids)assert.match(id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:{}});
  assert.throws(uuid,/Secure random/);
 }finally{if(original)Object.defineProperty(globalThis,'crypto',original);else delete globalThis.crypto;}
});
