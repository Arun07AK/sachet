const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl = url => { try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
function addTimeline(html) { const box = $('timeline'); if (box.querySelector('.muted')) box.innerHTML = ''; box.insertAdjacentHTML('beforeend', `<div class="event">${html}</div>`); box.scrollTop = box.scrollHeight; }
function renderReport(r) {
  const color = r.score >= 60 ? 'red' : r.score >= 30 ? 'amber' : 'green';
  const order = {critical: 0, high: 1, medium: 2, low: 3, info: 4, positive: 5};
  const sorted = [...r.findings].sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  const live = r.calls.filter(c => c.ok && !c.cached).length, cached = r.calls.filter(c => c.ok && c.cached).length;
  const findings = sorted.map(f => `<div class="finding"><span class="severity ${escapeHtml(f.severity)}">${escapeHtml(f.severity)}</span><strong> ${escapeHtml(f.title)}</strong>${f.origin === 'llm' ? ' <span class="severity info">agent follow-up</span>' : ''}<p>${escapeHtml(f.detail)}</p>${f.sources.map(s => { const url = safeUrl(s.url); return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title || s.url)} ↗</a>` : ''; }).join('')}</div>`).join('');
  $('verdict').className = `card verdict-card ${color}`;
  $('verdict').innerHTML = `<div class="eyebrow">VERDICT</div><div class="score"><div class="gauge" style="--score:${Number(r.score)}%"><span>${Number(r.score)}</span></div><div><h2>${escapeHtml(r.verdict_label)}</h2><p class="muted">Risk score out of 100</p></div></div><p>${escapeHtml(r.summary)}</p><p class="muted">SerpApi searches: ${live} live, ${cached} from cache. Every link below came from those results.</p><h3>Findings</h3>${findings || '<p class="muted">No findings.</p>'}`;
  $('verdict').hidden = false;
  const o = r.offer;
  const fields = [['Company',o.company],['Role',o.role],['City',o.city],['Address',o.address],['Emails',o.emails.join(', ')],['Phones',o.phones.join(', ')],['Links',o.urls.join(', ')],['Pay offered',o.pay.map(m => m.text + ' / ' + m.period).join(', ')],['Fees demanded',o.fees.map(m => m.text).join(', ')],['Official domain',r.official_domain]];
  $('entities').innerHTML = `<div class="eyebrow">EXTRACTED DETAILS</div><h2>Offer details</h2><div class="entity-grid">${fields.map(([label,value]) => `<div><b>${label}</b>${escapeHtml(value || 'Not found')}</div>`).join('')}</div>`;
  $('entities').hidden = false;
  $('next').innerHTML = `<div class="eyebrow">WHAT TO DO</div><h2>Next steps</h2><ul>${r.next_steps.map(step => `<li>${escapeHtml(step)}</li>`).join('')}</ul>`;
  $('next').hidden = false;
}
function eventReceived(e) {
  if (e.type === 'search') addTimeline(`<strong>SerpApi search</strong><span class="badge">${escapeHtml(e.engine)}</span>${e.cached ? '<span class="badge cached">cached</span>' : ''}<span class="search-query">${escapeHtml(e.query)}</span>`);
  if (e.type === 'step') addTimeline(`<strong>${escapeHtml(e.name.replaceAll('_',' '))}</strong><span class="badge ${escapeHtml(e.status)}">${escapeHtml(e.status)}</span><span class="search-query">${escapeHtml(e.reason)} · ${e.searches_left} searches left</span>`);
  if (e.type === 'report') renderReport(e.report);
  if (e.type === 'error') addTimeline(`<strong>Investigation error</strong><span class="search-query">${escapeHtml(e.message)}</span>`);
}
async function investigate() {
  const text = $('offer').value.trim(); if (!text) { $('offer').focus(); return; }
  $('investigate').disabled = true; $('timeline').innerHTML = '';
  for (const id of ['verdict','entities','next']) $(id).hidden = true;
  try {
    const response = await fetch('/api/investigate', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,budget:Number($('budget').value)})});
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let pending = '';
    while (true) { const {value,done} = await reader.read(); if (done) break; pending += decoder.decode(value,{stream:true}); let parts = pending.split('\n'); pending = parts.pop(); for (const line of parts) if (line) eventReceived(JSON.parse(line)); }
    if (pending.trim()) eventReceived(JSON.parse(pending));
  } catch (error) { eventReceived({type:'error',message:error.message}); }
  finally { $('investigate').disabled = false; }
}
$('investigate').addEventListener('click', investigate);
fetch('/api/health').then(r=>r.json()).then(h=> { $('banner').hidden = h.live || h.replay; });
fetch('/api/examples').then(r=>r.json()).then(items=> { for (const item of items) { const button = document.createElement('button'); button.className='chip'; button.textContent=item.name.replaceAll('_',' '); button.onclick=()=>{ $('offer').value=item.text; }; $('example-chips').append(button); } });
