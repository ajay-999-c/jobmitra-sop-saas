import fs from 'node:fs';

// Reuse the existing Email landing page; its approved composers stay separate resources.
export function emailWorkspaceMarkup(){
 const source=fs.readFileSync('src/jobmitra/templates/email_studio/index.html','utf8');
 const body=source.match(/{% block content %}([\s\S]*?){% endblock %}/)?.[1];
 if(!body)throw Error('Email landing page boundary missing.');
 const home=body.replace('href="/email/updates"','href="/workspace-v12/email?tool=updates"').replace('href="/email/submission"','href="/workspace-v12/email?tool=submission"').replace('href="/email/proposal"','href="/workspace-v12/email?tool=proposal"');
 return `<section id="emailHost" class="app-shell" hidden aria-label="Email workspace"><div id="emailHome">${home}</div><div id="emailTool" hidden><p class="email-return"><a href="/workspace-v12/email">← Email Studio</a></p><div id="emailFrames"></div></div><p id="emailWorkspaceNotice" role="status"></p></section>`;
}

export function emailWorkspaceStyles(){
 const css=fs.readFileSync('src/jobmitra/static/stage2/portal.css','utf8').split('\n').filter(l=>l.includes('.email-')).join('\n');
 // Every reused landing-page rule is scoped to the fourth workspace.
 const scoped=css.replace(/\.email-/g,'#emailHost .email-');
 return '/* Existing Email landing-page styles, scoped to the V12 host. */\n'+scoped+`
#emailHost{padding:16px clamp(12px,2vw,30px)}
#emailHost [hidden]{display:none!important}
#emailHost .email-return a{color:#c32230;font-weight:700}
#emailHost iframe{display:block;width:100%;height:1100px;border:0;background:#f4f6f8}
#emailWorkspaceNotice:empty{display:none}
`;
}
