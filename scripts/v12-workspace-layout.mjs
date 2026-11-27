import fs from 'node:fs';
import crypto from 'node:crypto';

// Presentation only: never import the reference's demo objects, scripts or persistence.
export const workspaceReference='Jobmitra_JD_Tracking_Interview_Rounds_Preview.html';
export const workspaceReferenceHash='6587ab895c7024cc03871338cfbe172c084a0528c88c7a7ad5b2c2f77793fed9';
export function workspaceStyles(){
 const bytes=fs.readFileSync(workspaceReference);
 if(crypto.createHash('sha256').update(bytes).digest('hex')!==workspaceReferenceHash)throw Error('Approved interview-round layout reference changed.');
 return '/* Generated presentation from immutable approved interview-round preview. */\n'+bytes.toString().match(/<style>([\s\S]*?)<\/style>/)[1].replaceAll(':root',':host')+`
:host .layout{display:grid;grid-template-columns:222px minmax(0,1fr);min-height:calc(100vh - var(--jm-header-height,66px));max-width:none;padding:0;gap:0}
:host .jd-sidebar{display:block;position:sticky;top:var(--jm-header-height,66px);align-self:start;min-height:calc(100vh - var(--jm-header-height,66px));max-height:calc(100vh - var(--jm-header-height,66px));overflow-y:auto;background:#fff;border-right:1px solid var(--line);padding:22px 12px}
:host .jd-sidebar .workspace-tab{display:block;width:100%;height:auto;text-align:left;white-space:normal;border:0;box-shadow:none;padding:10px;border-radius:6px;background:transparent;color:#47566a;font-weight:550;margin:2px 0}
:host .jd-sidebar .workspace-tab.active{background:#fff0f1;color:#bb2130;font-weight:700}
:host .jd-sidebar .workspace-picker{display:block;border-top:1px solid var(--line);padding:14px 9px;margin-top:16px}
:host .jd-sidebar .workspace-picker label{display:block;margin-bottom:7px}
:host .jd-sidebar .workspace-picker select,:host .jd-sidebar .searchable-select{max-width:100%;width:100%}
:host .jd-sidebar .searchable-select input{min-width:0;width:100%}
:host .layout>.main{padding:25px 28px;max-width:1900px;margin:0 auto;width:100%;min-width:0}
:host .jd-clean-header .hero{background:white;border:1px solid var(--line);border-radius:8px;padding:16px 18px;align-items:flex-start;margin-bottom:16px!important;gap:20px}
:host .jd-clean-header .hero h1{font-size:22px;letter-spacing:-.5px}
:host .jd-clean-header .hero-right{display:flex;align-items:center;gap:12px}
:host .jd-clean-header .summary{padding:0;border:0;box-shadow:none;gap:20px;background:transparent}
:host .jd-clean-header .companyline{font-size:12px;margin-top:5px;gap:10px;flex-wrap:wrap}
:host .jd-clean-header .ownerline{font-size:12px;color:var(--muted);margin:5px 0 0}
:host .jd-clean-header .ownerline strong{color:var(--ink)}
:host .jd-editor{max-width:1050px}.jd-editor .formgrid .field{min-width:0}.jd-editor .formgrid .field:has(textarea){grid-column:1/-1}
:host .jd-editor details>summary{cursor:pointer;padding:16px 18px;border-bottom:1px solid var(--line);font-size:14px;font-weight:700}
:host .jd-editor details .formgroup{border-bottom:0}.jd-editor .savebar{margin:0}
:host .jd-editor .control{min-height:36px;box-shadow:none;border-radius:6px}
:host .jd-editor .full-jd-content{padding:18px}
:host .jd-dashboard-table{min-width:1100px}.jd-dashboard-table button.jd-open{border:0;padding:0;background:transparent;white-space:normal;text-align:left;font-weight:700}
:host .jd-dashboard-table .recruiter{max-width:180px;white-space:normal}.jd-dashboard-table .jd-row-target{display:block}
:host .jd-dashboard-pages{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end;border:0}.jd-dashboard-pages label{display:flex;align-items:center;gap:7px;white-space:nowrap}.jd-dashboard-pages .control{width:auto;min-width:70px;display:inline-block}.jd-dashboard-pages span{white-space:nowrap}
:host .jd-dashboard-status{padding:10px 15px;font-size:12px;color:var(--muted)}
:host .jd-filter-toolbar{border:0;padding:0;display:block}.jd-primary-filters{display:flex;gap:9px;align-items:center;flex-wrap:wrap;padding:14px 16px;border-bottom:1px solid var(--line)}
:host .jd-primary-filters input[type=search]{flex:1;min-width:190px}.jd-extra-filters{display:flex;flex-wrap:wrap;gap:12px;background:#fbfcfe;padding:14px 16px;border-bottom:1px solid var(--line)}
:host .jd-extra-filters .field{min-width:150px}.jd-extra-filters label{font-size:12px}.jd-filter-custom{display:flex;gap:12px}
:host .jd-dashboard .metrics .metric strong{margin-top:7px}.jd-dashboard .metrics .metric{border-top-color:#899aaf}
:host .jd-dashboard .metrics .metric.red{border-top-color:#c72c39}.jd-dashboard .metrics .metric.amber{border-top-color:#d69a26}.jd-dashboard .metrics .metric.green{border-top-color:#458e62}
.jd-row-more{position:relative}.jd-row-more>summary{display:block;list-style:none;border:1px solid #dbe1e8;border-radius:6px;padding:5px 10px;cursor:pointer;background:white;line-height:1.4;font-size:17px}.jd-row-menu{position:fixed;width:190px;z-index:300;background:white;border:1px solid var(--line);border-radius:7px;box-shadow:0 8px 28px #24324726;padding:5px;max-height:70vh;overflow:auto}.jd-row-menu button{display:block;width:100%;border:0;text-align:left;font-size:12px;padding:9px 12px}.jd-clean .rowactions{display:flex;justify-content:flex-end;gap:6px;flex-wrap:wrap}.jd-clean .reject-visible{color:#b82430;border-color:#ebc6ca;background:white}
:host [hidden]{display:none!important}
@media(max-width:1150px){:host .layout{grid-template-columns:190px minmax(0,1fr)}:host .layout>.main{padding:20px 18px}:host .jd-clean-header .hero{flex-wrap:wrap}}
@media(max-width:700px){:host .layout{grid-template-columns:145px minmax(0,1fr)}:host .jd-sidebar{padding:12px 6px}:host .jd-sidebar .workspace-tab{font-size:11px;padding:8px}:host .layout>.main{padding:15px 10px}.jd-editor .formgrid{grid-template-columns:1fr}.jd-primary-filters input[type=search]{min-width:120px}.jd-filter-custom{flex-wrap:wrap}}
`;
}

export function workspaceMarkup(ui){
 const style=ui.slice(0,ui.indexOf('</style>')+8);
 return style+`<link rel="stylesheet" href="/static/ats-v2/jd-clean.css"><link rel="stylesheet" href="/static/ats-v2/jd-workspace.css">
<div class="layout"><aside class="jd-sidebar"><nav aria-label="JD workspace navigation">
<div class="navgroup">JD Tracking</div><button class="workspace-tab" id="navDashboard" type="button">JD Dashboard</button>
<div class="navgroup">Selected JD</div><button class="workspace-tab" id="navPipeline" type="button">Candidate Pipeline</button>
<button class="workspace-tab" id="navDetails" type="button">Edit JD</button><button class="workspace-tab" id="navWorkflow" type="button">Interview Rounds (Add/Remove)</button>
<button class="workspace-tab" id="navPlacement" type="button">Placement &amp; Billing</button><button class="workspace-tab" id="navHistory" type="button">JD Activity</button>
<div class="workspace-picker" id="jdSwitch"><label for="jobPicker">Switch JD</label><select id="jobPicker" aria-label="Choose job requirement"></select></div>
<p class="side-note" id="jdSidebarContext">Select a JD to manage its pipeline.</p></nav></aside>
<main class="main"><div class="jd-main-actions" style="display:flex;justify-content:flex-end;margin-bottom:10px"><button class="btn secondary small" id="newJobBtn" type="button">＋ New JD</button></div>
<div class="jd-clean jd-clean-header" id="jdSelectedHeader"><section class="hero"><div class="hero-left"><h1 id="heroTitle"></h1><div class="companyline"><span id="heroSubtitle"></span><span id="statusPill" class="status"></span></div><p class="ownerline">Assigned Recruiter <strong id="jdRecruiter"></strong></p></div>
<div class="hero-right"><div id="jdTargetSummary" class="summary"></div><button id="resetBtn" class="btn icon" aria-label="Refresh current JD" title="Refresh current JD">↻</button><div id="jdContextActions"></div><button id="topSaveBtn" hidden>Review &amp; Save Workflow</button></div></section></div>
<span id="breadcrumbCurrent" hidden></span><div id="jdSyncNotice" role="status"></div><div id="workspace"></div></main></div><div id="modalHost"></div><div aria-live="polite" class="toast" id="toast" role="status"></div>`;
}
