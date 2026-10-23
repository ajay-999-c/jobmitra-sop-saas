// One export boundary for the supplied Studio's preview, JSON, DOCX and print.
// Does not mutate the private registration record or send data anywhere.
const escapePattern = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
function privateStrings(value) {
  if (typeof value === 'string') return value.trim() ? [value.trim()] : [];
  if (Array.isArray(value)) return value.flatMap(privateStrings);
  if (value && typeof value === 'object') return Object.values(value).flatMap(privateStrings);
  return [];
}
export function sanitizePublicResume(resume, candidate = {}) {
  const privateValues = privateStrings({emails:candidate.emails, phones:candidate.phones,
    location:candidate.location, links:candidate.links}).sort((a,b) => b.length - a.length);
  function clean(text, isName = false) {
    let result = String(text);
    if (!isName) {
      for (const value of privateValues) {
        const pattern = escapePattern(value).replace(/\s+/g, '\\s+');
        result = result.replace(new RegExp('(?<![\\p{L}\\p{N}])' + pattern + '(?![\\p{L}\\p{N}])', 'giu'), '');
      }
    }
    result = result.split(/\r?\n/).map(line => {
      // Residential information may be embedded in a summary or a project bullet.
      if (/\b(?:home|residential|permanent|postal|mailing)\s+address\b|\b(?:resides?|lives?)\s+(?:at|in)\b|\baddress\s*:/i.test(line)) return '';
      if (/\b\d{1,5}\s+[^,;\n]{0,70}\b(?:road|street|lane|apartment|colony|nagar|society|avenue)\b/i.test(line)) return '';
      return line
        .replace(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/gi, '')
        .replace(/(?:https?:\/\/|www\.)[^\s<>]+/gi, '')
        .replace(/\b(?:linkedin\.com|github\.com|facebook\.com|instagram\.com|wa\.me)\/[^\s<>]*/gi, '')
        .replace(/(?<!\d)\+?\d(?:[\t ().-]*\d){9,14}(?!\d)/g, '')
        .replace(/\b(?:phone|mobile|email|e-mail|contact|linkedin|github|website)\s*[:=-]\s*[^;|\n]*/gi, '')
        .replace(/[ \t]{2,}/g, ' ').trim();
    }).filter(Boolean).join('\n');
    return result.replace(/^[\s,;|·—-]+|[\s,;|·—-]+$/g, '').trim();
  }
  function walk(value, key = '') {
    if (typeof value === 'string') return clean(value, key === 'name');
    if (Array.isArray(value)) return value.map(item => walk(item)).filter(item => item !== '');
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
      .filter(([field]) => !['candidate', 'review_flags'].includes(field))
      .map(([field,item]) => [field, walk(item, field)]));
    return value;
  }
  return {...walk(resume), review_flags:[]};
}
