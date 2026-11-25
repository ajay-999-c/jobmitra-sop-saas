import fs from 'node:fs';
import crypto from 'node:crypto';

// The supplied prototype contributes presentation only, never its data or script.
export function cleanJDStyles(){
 const bytes=fs.readFileSync('Jobmitra_JD_Tracking_Clean_Preview.html');
 if(crypto.createHash('sha256').update(bytes).digest('hex')!=='ed5db4da04e1c023d9473fac7ab68f50eb30463694fc9b9968def4e33599a8ad')throw Error('Clean JD reference hash mismatch.');
 const css=bytes.toString('utf8').match(/<style>([\s\S]*?)<\/style>/)[1];
 function scope(input){
  let out='',offset=0;
  while(offset<input.length){
   const open=input.indexOf('{',offset);if(open<0){out+=input.slice(offset);break;}
   const selector=input.slice(offset,open).trim();let end=open+1,depth=1;
   for(;depth&&end<input.length;end++){if(input[end]==='{')depth++;else if(input[end]==='}')depth--;}
   const body=input.slice(open+1,end-1);
   const scoped=selector.startsWith('@media')?selector:selector.split(',').map(s=>[':root','body'].includes(s.trim())?'.jd-clean':s.trim()==='*'?'.jd-clean, .jd-clean *':'.jd-clean '+s.trim()).join(',');
   out+=scoped+'{'+(selector.startsWith('@media')?scope(body):body)+'}\n';offset=end;
  }
  return out;
 }
 return '/* Generated from immutable clean JD reference. */\n'+scope(css)+`
.jd-clean-header .hero{margin-bottom:18px!important;flex-direction:row}
.jd-clean .btn{box-shadow:none}
.jd-clean .group{flex:0 0 auto}
.jd-clean .stage{width:138px;min-width:138px;max-width:138px;height:114px;min-height:114px;max-height:114px;flex:0 0 138px;display:grid;grid-template-rows:32px 25px 14px;gap:0;align-content:space-between}
.jd-clean .stage-title{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden;text-overflow:ellipsis;overflow-wrap:anywhere;line-height:16px;height:32px;min-height:32px;max-height:32px;min-width:0}
.jd-clean .stage-num,.jd-clean .stage-meta{align-self:start;min-width:0}
.jd-clean .row-status.amber{color:#94620c;background:#fff8e9;padding:5px 7px;border-radius:6px}
.jd-clean .row-status.green{color:#147650;background:#eaf8f0;padding:5px 7px;border-radius:6px}
.jd-clean .row-status.red{color:#a43d45;background:#fff0f2;padding:5px 7px;border-radius:6px}
.jd-clean .row-status.unavailable{color:#65768b}
.jd-clean .workflow-empty{max-width:170px;align-self:center;color:var(--muted);font-size:12px;padding:12px}
.jd-clean .next-destination{display:block;font-size:10px;color:var(--muted);margin-top:4px}
.jd-clean .clean-message{margin:10px 18px;padding:10px;background:#eaf8f0;color:#146746;border-radius:8px;font-size:12px}
.jd-clean .clean-message.error{background:#fff0f2;color:#a43d45}
.jd-clean .clean-batch{padding:0 18px 10px}
.jd-clean .summary.unset,.jd-clean .summary.closed{border-left-color:#65768b}
.jd-clean .candidate-table input[type=checkbox]{min-height:0;margin-right:8px}
`;
}

export function cleanJDMarkup(ui){
 const start=ui.indexOf('<div class="hero">'),end=ui.indexOf('<div id="workspace">',start);
 if(start<0||end<0)throw Error('Clean JD header boundary missing.');
 const header=`<div class="jd-clean jd-clean-header"><section class="hero">
 <div class="hero-left"><h1 id="heroTitle"></h1><div class="companyline"><span id="heroSubtitle"></span><span id="statusPill" class="status"></span></div></div>
 <div class="hero-right"><div id="jdTargetSummary" class="summary" aria-live="polite"></div><button id="resetBtn" class="btn icon" aria-label="Refresh records" title="Refresh records">↻</button><button id="topSaveBtn" class="btn primary" hidden>Review &amp; Save Workflow</button></div>
 </section></div>\n`;
 return (ui.slice(0,start)+header+ui.slice(end)).replace('</style>','</style><link rel="stylesheet" href="/static/ats-v2/jd-clean.css">').replace(/<div class="footer-note">[\s\S]*?<\/div>/,'');
}
