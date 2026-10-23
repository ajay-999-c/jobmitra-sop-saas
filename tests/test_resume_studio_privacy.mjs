import test from 'node:test';
import assert from 'node:assert/strict';
import {sanitizePublicResume} from '../src/jobmitra/static/alter_resumes/privacy.mjs';
const candidate = {name:'Synthetic Meera',emails:['meera@example.com'],phones:['+44 7700 900123'],
  location:{city:'Privatecity',state:'Privatestate'},links:{linkedin:'https://linkedin.com/in/synthetic',other:['https://secret.example/profile']}};
test('public exports remove nested contacts, residential details and internal notes without mutating private data', () => {
  const resume={name:candidate.name,job_title:'Analyst',professional_summary:'Excel analyst in Privatecity. meera@example.com +44 (7700) 900123',
    work_experience:[{company:'Example Ltd',duration:'2018 - 2022',responsibilities:['Call +1 (202) 555-0101','Delivered reports','Home address: 42 Hidden Lane','linkedin.com/in/synthetic']}],
    projects:['Lives at 42 Hidden Lane, Privatecity','https://secret.example/profile'],
    education:[{qualification:'BCom',institution:'Example University',year:'2020'}],review_flags:['Privatecity private note']};
  const before=JSON.stringify({resume,candidate});
  const result=sanitizePublicResume(resume,candidate), text=JSON.stringify(result);
  for(const privateValue of ['meera@example.com','7700','202) 555','Privatecity','Hidden Lane','linkedin.com','secret.example','private note']) assert.ok(!text.includes(privateValue),privateValue);
  assert.equal(result.name,candidate.name);
  assert.equal(result.work_experience[0].duration,'2018 - 2022');
  assert.ok(text.includes('Delivered reports'));
  assert.equal(JSON.stringify({resume,candidate}),before);
});
test('same guard handles plain-text job strings and candidate location literals safely', () => {
  const result=sanitizePublicResume({name:'Synthetic Meera',work_experience:['Analyst. 90000-00001 meera@example.com'],professional_summary:'Privatecity analyst'},candidate);
  assert.equal(result.work_experience[0],'Analyst.');
  assert.equal(result.professional_summary,'analyst');
});
