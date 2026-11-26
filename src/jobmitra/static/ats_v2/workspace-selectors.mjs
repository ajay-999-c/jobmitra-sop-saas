import {enhanceSelect} from './searchable-select.mjs';
// Filter the existing complete option sets; never broaden active-JD/company rules.
export function selectorSearch(kind,id,native,label=''){
 const item=(kind==='job'?native.jobs:native.companies).find(x=>String(x.id)===String(id));
 return [label,...(kind==='job'?[item?.title,item?.company,item?.code,item?.id]:[item?.name])].filter(x=>x!==null&&x!==undefined).join(' ');
}
export function installWorkspaceSelectors(native,root){
 const selectors={f_company:['company','Search company'],jobPicker:['job','Choose job requirement'],poolJobSelect:['job','Active job requirement'],selectActiveJD:['job','Select active JD']};
 function scan(){
  for(const [id,[kind,label]] of Object.entries(selectors)){
   const select=root.getElementById(id);if(!select)continue;
   for(const option of select.options){const search=selectorSearch(kind,option.value,native,option.textContent);if(option.dataset.search!==search)option.dataset.search=search;}
   enhanceSelect(select,{label})?.refresh();
  }
 }
 const observer=new MutationObserver(scan);observer.observe(root,{childList:true,subtree:true});scan();
 return {refresh:scan,destroy:()=>observer.disconnect()};
}
