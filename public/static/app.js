'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const LOCAL=!!window.KILN_LOCAL, STATIC=!!window.KILN_STATIC;
const LABELS={pending:'Needs research',ready:'Ready','in-progress':'In progress',made:'Made','set-aside':'Set aside'};
const STATUS={inbox:'ready',triage:'ready',active:'in-progress',done:'made',dropped:'set-aside'};
const FEATURES={project:'Project',prompt:'Prompt',commands:'Commands',pdf:'PDF',transcript:'Transcript',research:'Research'};
let cache=null,seq=0,searchTimer,toastTimer,detailSeq=0,lastFocus=null;
let saved=new Set();try{saved=new Set(JSON.parse(localStorage.getItem('kiln-saved')||'[]'));}catch{}
const params=new URLSearchParams(location.search);
const state={items:[],jobs:{},facets:null,q:params.get('q')||'',filters:{},sort:params.get('sort')||'recent',saved:params.get('saved')==='1',item:null,tab:'overview'};
for(const key of ['topic','section','action','place','content','stage']) if(params.get(key))state.filters[key]=params.get(key);
$('#q').value=state.q;$('#sort').value=state.sort;

function href(u){try{const p=new URL(u,location.href);return ['http:','https:'].includes(p.protocol)?esc(p.href):'#';}catch{return '#';}}
function link(u,title){return `<a href="${href(u)}" target="_blank" rel="noopener noreferrer">${esc(title||u)} ↗</a>`;}
function toast(s){clearTimeout(toastTimer);$('#toast').innerHTML=`<div class="toast">${esc(s)}</div>`;toastTimer=setTimeout(()=>$('#toast').replaceChildren(),4000);}
function progress(i){return i.research_state==='pending'?'pending':i.progress||STATUS[i.status]||'ready';}
function words(s){return s.toLocaleLowerCase().match(/[\p{L}\p{N}_]+/gu)||[];}
function researchTime(i){const value=String(i.note?.research_date||i.links_checked||'');const parsed=Date.parse(value);return Number.isFinite(parsed)?parsed:(i.processed_at||0)*1000;}
function syncUrl(){const p=new URLSearchParams();if(state.q)p.set('q',state.q);for(const[k,v]of Object.entries(state.filters))if(v)p.set(k,v);if(state.sort!=='recent')p.set('sort',state.sort);if(state.saved)p.set('saved','1');history.replaceState(null,'',location.pathname+(p.size?'?'+p:'')+location.hash);}
async function api(url,options={}){
 if(STATIC){
  if(options.method&&options.method!=='GET')throw Error('The public library is read only.');
  if(!cache){const r=await fetch('/data/items.json');if(!r.ok)throw Error('Library data could not be loaded.');cache=await r.json();}
  if(url.startsWith('/api/facets')){const r=await fetch('/data/facets.json');return r.json();}
  if(url.startsWith('/api/item/')){let id=url.split('/').pop();id=cache.aliases?.[id]||id;const it=cache.items.find(i=>i.id===id);if(!it)throw Error('Topic not found.');return it;}
  if(url.startsWith('/api/items')){
   const p=new URLSearchParams(url.split('?')[1]||'');let items=cache.items||[];
   for(const key of ['topic','place','action'])if(p.get(key))items=items.filter(i=>(i.tags?.[key]||[]).includes(p.get(key)));
   const sec=p.get('section');if(sec)items=items.filter(i=>(i.tags?.section||[]).some(v=>v===sec||v.startsWith(sec+'/')));
   if(p.get('content'))items=items.filter(i=>i.contents?.[p.get('content')]);
   const terms=words(p.get('q')||'');if(terms.length)items=items.filter(i=>{const t=JSON.stringify(i).toLocaleLowerCase();return terms.every(w=>t.includes(w));});
   return {items,jobs:{}};
  }
  return {};
 }
 const headers={...(options.headers||{})};if(options.method&&options.method!=='GET')headers['X-Kiln-Token']=window.KILN_TOKEN||'';
 const response=await fetch(url,{...options,headers});let result;try{result=await response.json();}catch{throw Error('The local server returned an unreadable response.');}if(!response.ok)throw Error(result.error||'Request failed');return result;
}
const post=(url,body)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

async function load(){
 const turn=++seq,p=new URLSearchParams({limit:'10000'});if(state.q)p.set('q',state.q);for(const[k,v]of Object.entries(state.filters))if(v&&k!=='stage')p.set(k,v);
 try{const[r,f]=await Promise.all([api('/api/items?'+p),api('/api/facets')]);if(turn!==seq)return;state.items=r.items||[];state.jobs=r.jobs||{};state.facets=f;renderFacets();renderShelf();renderJobs();syncUrl();}
 catch(e){if(turn!==seq)return;$('#shelf').innerHTML=`<div class="empty"><h3>The library could not load</h3><p>${esc(e.message)}</p><button class="button" data-action="retry">Try again</button></div>`;}
}
function facetButton(key,val,label,n,sub=false){return `<button data-filter="${esc(key)}" data-value="${esc(val)}" class="${sub?'sub':''}" aria-pressed="${state.filters[key]===val}"><span>${esc(label)}</span>${n!==undefined?`<span class="n">${n}</span>`:''}</button>`;}
function renderFacets(){
 const f=state.facets;if(!f)return;$('#total').textContent=f.total;const opened=new Map($$('#facets details').map(d=>[d.dataset.group,d.open]));
 const group=(title,key,body,defaultOpen=true)=>`<details class="facet" data-group="${key}" ${(opened.get(key)??defaultOpen)?'open':''}><summary>${esc(title)}</summary>${body}</details>`;
 let html=group('Contains','content',Object.entries(FEATURES).map(([k,v])=>facetButton('content',k,v)).join(''));
 html+=group('Sections','section','<div class="facet-list">'+(f.sections||[]).map(s=>facetButton('section',s.id,s.name,s.count,!!s.parent)).join('')+'</div>');
 html+=group('Tags','topic',`<input id="tagFilter" type="search" placeholder="Find a tag…" aria-label="Find a tag" style="width:100%;font-size:11px;margin:0 0 8px"><div class="facet-list" id="tagList">${Object.entries(f.by_topic||{}).sort((a,b)=>a[0].localeCompare(b[0])).map(([k,n])=>facetButton('topic',k,k,n)).join('')}</div>`,false);
 html+=group('Next action','action',Object.entries(f.by_action||{}).map(([k,n])=>facetButton('action',k,k,n)).join(''),false);
 if(Object.keys(f.by_place||{}).length)html+=group('Platforms','place',Object.entries(f.by_place).map(([k,n])=>facetButton('place',k,k,n)).join(''),false);
 $('#facets').innerHTML=html;
 $('#tagFilter').oninput=e=>{$$('#tagList button').forEach(b=>b.hidden=!b.dataset.value.includes(e.target.value.toLowerCase()));};
}
function renderShelf(){
 let items=state.items.filter(i=>!state.filters.stage||progress(i)===state.filters.stage).filter(i=>!state.saved||saved.has(i.id));
 if(state.sort==='title')items.sort((a,b)=>(a.title||'').localeCompare(b.title||''));
 else if(state.sort==='sources')items.sort((a,b)=>(b.source_count||1)-(a.source_count||1));
 else items.sort((a,b)=>researchTime(b)-researchTime(a)||((b.processed_at||0)-(a.processed_at||0)));
 const section=state.facets?.sections?.find(s=>s.id===state.filters.section)?.name;
 $('#heading').textContent=section||state.filters.topic||(state.saved?'Saved on this device':'All topics');
 $('#count').textContent=`${items.length} topic${items.length===1?'':'s'} · ${items.reduce((n,i)=>n+(i.source_count||1),0)} sources`;
 $('#clear').hidden=!state.q&&!Object.values(state.filters).some(Boolean)&&!state.saved;
 $$('.stage-tabs [data-stage]').forEach(b=>b.setAttribute('aria-pressed',String((state.filters.stage||'')===b.dataset.stage)));
 $('#savedBtn').setAttribute('aria-pressed',String(state.saved));
 $('#activeFilters').innerHTML=Object.entries(state.filters).filter(([k,v])=>v&&k!=='stage').map(([k,v])=>`<button class="filter-pill" data-remove-filter="${esc(k)}">${esc(k)}: ${esc(v)} ×</button>`).join('');
 $('#shelf').innerHTML=items.length?items.map(tile).join(''):`<div class="empty"><h3>${state.saved?'Your saved shelf is empty':'No matching topics'}</h3><p>${state.saved?'Use the star on a tile. Saved topics stay in this browser.':'Try fewer keywords or clear a filter.'}</p><button class="button" data-action="clear">Clear filters</button></div>`;
}
function tile(i){const flags=i.contents||{},p=progress(i),isSaved=saved.has(i.id);return `<article class="tile"><div class="tile-top"><span>${esc(i.action||'reference')} · ${i.source_count||1} source${(i.source_count||1)>1?'s':''}</span><span class="stage ${p}">${LABELS[p]}</span></div><h3><button class="tile-title" data-open="${esc(i.id)}">${esc(i.title||'Untitled topic')}</button></h3><p class="tile-hook">${esc(i.hook||i.summary||'Open for details and source links.')}</p><div class="badges">${Object.entries(FEATURES).filter(([k])=>flags[k]).map(([k,v])=>`<span class="badge ${k}">${v}</span>`).join('')}${i.gate?.gated?'<span class="badge">Creator gate</span>':''}</div><div class="tile-bottom"><div class="tags">${(i.tags?.topic||[]).slice(0,3).map(t=>`<span class="tag">#${esc(t)}</span>`).join('')}</div><button class="save" data-save="${esc(i.id)}" aria-label="${isSaved?'Unsave':'Save'} ${esc(i.title)}" aria-pressed="${isSaved}">${isSaved?'★':'☆'}</button></div></article>`;}
function renderJobs(){const jobs=Object.entries(state.jobs).filter(([,j])=>['working','queued','followup','error'].includes(j.stage));$('#jobs').innerHTML=jobs.map(([,j])=>`<div class="notice ${j.stage==='error'?'error':''}">${j.stage==='error'?'Research needs a retry: '+esc(j.error):'<span class="spinner"></span>Researching README evidence and current sources…'}</div>`).join('');}
function clearFilters(){state.filters={};state.q='';state.saved=false;$('#q').value='';load();}
function filter(key,val){state.filters[key]=state.filters[key]===val?'':val;load();}
function toggleSaved(id){saved.has(id)?saved.delete(id):saved.add(id);try{localStorage.setItem('kiln-saved',JSON.stringify([...saved]));}catch{toast('This browser cannot retain saved topics.');}renderShelf();if(state.item?.id===id){const b=$('#detailSave');if(b){b.setAttribute('aria-pressed',String(saved.has(id)));b.textContent=saved.has(id)?'★ Saved':'☆ Save on this device';}}}

function showDialog(title,body,{small=false,subtitle=''}={}){
 if(!$('#modal').hasChildNodes())lastFocus=document.activeElement;
 $('#modal').innerHTML=`<div class="backdrop" data-action="close"></div><section class="dialog ${small?'small':''}" role="dialog" aria-modal="true" aria-labelledby="dialogTitle"><header class="dialog-header"><button class="close" data-action="close" aria-label="Close dialog">×</button><p class="eyebrow">${LOCAL?'LOCAL WORKSPACE':'PUBLIC LIBRARY'}</p><h2 id="dialogTitle">${esc(title)}</h2>${subtitle?`<p class="lede">${esc(subtitle)}</p>`:''}</header>${body}</section>`;
 document.body.style.overflow='hidden';$('.dialog .close').focus();
}
function closeDialog(){detailSeq++;$('#modal').replaceChildren();document.body.style.overflow='';state.item=null;if(location.hash.startsWith('#item='))history.replaceState(null,'',location.pathname+location.search);lastFocus?.focus();}
async function openItem(id,tab='overview'){
 const turn=++detailSeq;state.tab=tab;showDialog('Opening topic…','<div class="small-content"><span class="spinner"></span>Loading research</div>',{small:true});
 try{const it=await api('/api/item/'+encodeURIComponent(id));if(turn!==detailSeq)return;state.item=it;history.replaceState(null,'',location.pathname+location.search+'#item='+it.id);renderDetail();}
 catch(e){if(turn===detailSeq)showDialog('Could not open topic',`<div class="small-content error">${esc(e.message)}</div>`,{small:true});}
}
function renderDetail(){
 const it=state.item,n=it.note||{},fu=it.followup||{},files=fu.artifacts||[];
 const tabs=[['overview','Overview',''],['guide','Research',''],['toolbox','Prompts & tools',n.prompts?.length||''],['files','Files',files.length||''],['sources','Sources',it.source_count||1],['related','Related',it.related?.length||'']];if(LOCAL)tabs.push(['organize','Organize','']);
 showDialog(it.title,`<div class="dialog-body"><nav class="detail-nav" role="tablist" aria-label="Topic sections">${tabs.map(([key,label,count])=>`<button id="tab-${key}" role="tab" aria-controls="panel-${key}" aria-selected="${state.tab===key}" tabindex="${state.tab===key?0:-1}" data-tab="${key}">${label}<small>${count}</small></button>`).join('')}<div class="detail-meta">${it.source_count||1} original source${(it.source_count||1)>1?'s':''}<br>${n.research_date?'Researched '+esc(n.research_date):'Check source dates in the guide.'}<br><br>Save, share, then make something useful.</div></nav><div class="detail-content" id="detailContent">${panel(it)}</div></div>`,{subtitle:it.hook});
 wirePanel();
}
function details(title,body,open=false){return body?`<details class="details" ${open?'open':''}><summary>${esc(title)}</summary><div>${body}</div></details>`:'';}
function empty(t){return `<p class="lede">${esc(t)}</p>`;}
function panel(it){
 const n=it.note||{},e=it.enrich||{},fu=it.followup||{},key=state.tab;
 let html='';
 if(key==='overview'){
  html=`${it.research_state==='pending'?'<p class="notice">Research is pending or needs a retry. Previous material may remain visible; this revision is not ready for cleanup.</p>':''}<h3>The useful part</h3><p class="lede">${esc(it.summary||it.hook||'Read the research guide for the full explanation.')}</p><div class="summary-grid"><div><strong>${it.source_count||1}</strong>original sources</div><div><strong>${(fu.artifacts||[]).length}</strong>downloadable files</div><div><strong>${it.contents?.project?'Yes':'—'}</strong>project idea</div></div><div class="actions"><button class="button primary" data-tab="guide">Read the guide →</button><button class="button" data-action="share">Copy topic link</button><button class="button" id="detailSave" data-save="${it.id}" aria-pressed="${saved.has(it.id)}">${saved.has(it.id)?'★ Saved':'☆ Save on this device'}</button></div><div class="progress-line">${Object.entries(LABELS).filter(([k])=>!['set-aside','pending'].includes(k)).map(([k,v])=>`<span class="${progress(it)===k?'current':''}">${v}</span>`).join('<b>→</b>')}</div><p class="lede" style="font-size:11px">${LOCAL?'Research completion makes an item ready. Move it to In progress while using or building it, and Made when your outcome is complete.':'These stages reflect the owner’s published progress. Stars are your own bookmarks and stay on this device.'}</p>`;
  if(e.next_action||fu.next_action)html+=details('Next step',`<p class="prose">${esc(fu.next_action||e.next_action)}</p>`,true);
  if(it.gate?.gated)html+=details('Creator access gate',`<p class="prose">${esc(it.gate.advice||'Some material requires a creator response. Check the original source.')}</p>`,true);
  html+=`<div class="tags" style="margin-top:18px">${(it.tags?.topic||[]).map(t=>`<button class="filter-pill" data-topic-link="${esc(t)}">#${esc(t)}</button>`).join('')}</div>`;
 }else if(key==='guide'){
  html=`<h3>Research guide</h3>${n.evidence_notice?`<p class="lede" style="font-size:11px">${esc(n.evidence_notice)}</p>`:''}<div class="prose" id="guideProse">${fu.answer_html||'<p>No finished research guide yet. The source notes below remain available.</p>'}</div>`;
  if(e.what_it_is&&!fu.answer_html)html+=details('Beyond the post',`<p class="prose">${esc(e.what_it_is)}</p>`,true);
  const secs=[...(n.sections||[]),...(fu.extra_sections||[])];
  html+=details('Source notes and additional detail',secs.map(s=>details(s.heading||'Detail',`<div class="prose">${s.html||'<p>'+esc(s.detail)+'</p>'}</div>`)).join(''));
  if(e.gotchas?.length)html+=details('Limits and common mistakes','<ul class="prose">'+e.gotchas.map(g=>'<li>'+esc(g)+'</li>').join('')+'</ul>');
 }else if(key==='toolbox'){
  html='<h3>Prompts & tools</h3>';
  const commands=n.commands?.length?n.commands:n.code_snippets||[];
  html+=commands.length?details('Commands and code',`<p class="lede" style="font-size:11px">Read the guide for prerequisites, verification dates and supported platforms. Copying a command does not execute it.</p>${commands.map((c,i)=>`<pre class="codebox">${esc(c)}</pre><button class="button" data-copy-command="${i}">Copy command ${i+1}</button>`).join('')}`,true):empty('No standalone verified command is recorded. Check the research guide for setup details.');
  if(n.prompts?.length)html+=details('Reusable prompts',n.prompts.map((p,i)=>details(p.heading||'Prompt',`<div class="prose">${p.html||esc(p.detail)}</div><button class="button" data-copy-prompt="${i}">Copy this prompt</button>`,i===0)).join(''),true);
  if(e.project){const p=e.project;html+=details('Project idea: '+(p.name||'Build something useful'),`<p class="lede">${esc(p.one_liner||'')}</p><p class="prose">${esc(p.scope||'')}</p><div class="tags">${(p.stack||[]).map(t=>`<span class="badge">${esc(t)}</span>`).join('')}</div><ol class="prose">${(p.milestones||[]).map(m=>`<li><strong>${esc(m.step)}</strong> — ${esc(m.outcome)}</li>`).join('')}</ol>${it.build_prompt?`<div class="actions"><button class="button primary" data-action="build-copy">Copy build prompt</button>${LOCAL?'<button class="button" data-action="build-queue">Queue project</button>':''}</div><div id="buildOut"></div>`:''}`,true);}
  if(e.install?.command)html+=details('Install instructions',`<pre class="codebox">${esc(e.install.command)}</pre><p class="prose">${esc(e.install.touches||'')} ${esc(e.install.uninstall||'')}</p><button class="button" data-action="copy-install">Copy installation command</button>`);
 }else if(key==='files'){
  html='<h3>Downloadable files</h3>'+(fu.artifacts?.length?fu.artifacts.map(a=>{const path=STATIC?`/media/${it.id}/files/${encodeURIComponent(a.file)}`:`/artifacts/${it.id}/${encodeURIComponent(a.file)}`;return `<div class="file"><span class="badge">${esc((a.kind||a.file.split('.').pop()).toUpperCase())}</span><div>${link(path,a.title||a.file)}<small>${a.pages?a.pages+' pages · ':''}${esc(a.about||'')}</small></div></div>`;}).join(''):empty('No generated downloads on this topic. You can still copy the guide and prompts.'));
  const dir=(it.media_dir||'').split(/[\\/]/).pop(),base=STATIC?`/media/${it.media_id||it.id}/`:`/media/${dir}/`,ext=it.slide_ext||'.webp',pdf=it.pdf_file||(it.pdf_path||'').split(/[\\/]/).pop();
  if(pdf&&it.slide_count)html+=details('Original carousel PDF',link(base+encodeURIComponent(pdf),'Open bound slides'),true);
  if(it.slide_count)html+=details(`${it.slide_count} original slides`,`<div class="slides">${Array.from({length:it.slide_count},(_,i)=>{const src=base+(STATIC?'':dir+'_')+String(i+1).padStart(2,'0')+ext;return `<a href="${href(src)}" target="_blank" rel="noopener"><img loading="lazy" src="${href(src)}" alt="Source slide ${i+1}"></a>`;}).join('')}</div>`);
 }else if(key==='sources'){
  html='<h3>Original reels & videos</h3><p class="lede" style="font-size:12px">Every original remains attached to the topic, including sources merged into this guide.</p>'+(it.source_urls||[it.url]).map((u,i)=>`<div class="source-link"><span class="badge">${i+1}</span><div>${link(u,u)}${it.owner?'<small>'+esc(it.owner)+'</small>':''}</div></div>`).join('');
  html+=details('Research sources', (fu.sources||[]).map(s=>`<div class="source-link">${link(s.url,s.title||s.url)}</div>`).join(''),true);
  html+=details('Useful links'+(it.links_checked?' · checked '+it.links_checked:''),(it.links||[]).map(l=>`<div class="source-link"><span class="health ${l.alive?'':'bad'}">${l.alive?'reachable':l.status_code?'HTTP '+l.status_code:'unconfirmed'}</span><div>${link(l.url,l.label||l.page_title||l.url)}</div></div>`).join(''));
  if(n.spoken_transcript)html+=details('Source transcript',`<p class="lede" style="font-size:11px">Supplied by the initial source dossier. It may be auto-transcribed, lightly cleaned or reconstructed. Check the original for exact wording.</p><pre class="codebox">${esc(n.spoken_transcript)}</pre>`);
  html+=(it.members||[]).filter(m=>m.transcript).map(m=>details('Transcript: '+m.title,`<pre class="codebox">${esc(m.transcript)}</pre>`)).join('');
 }else if(key==='related'){
  html='<h3>Keep exploring</h3><p class="lede" style="font-size:12px">Related subjects stay separate when they teach a different tool, method or course.</p>'+(it.related?.length?it.related.map(r=>`<button class="related-card" data-open="${esc(r.id)}"><strong>${esc(r.title)}</strong><small>${esc(r.why)}</small></button>`).join(''):empty('No related topic has been found yet.'));
 }else if(key==='organize'&&LOCAL){
  const tree=state.facets?.sections||[];
  html=`<h3>Make this yours</h3><label class="field">Progress<select id="itemStatus">${[['inbox','Ready'],['active','In progress'],['done','Made'],['dropped','Set aside']].map(([v,l])=>`<option value="${v}" ${((it.status==='triage'?'inbox':it.status)||'inbox')===v?'selected':''}>${l}</option>`).join('')}</select><small>Research completion does not mean the project is made.</small></label><button class="button primary" data-action="save-status">Save progress</button><div class="organize-box"><h4>Tags</h4><label class="field">Tags, separated by commas<input id="editTags" value="${esc((it.tags?.topic||[]).join(', '))}"><small>These topic tags appear in the public library on the next publish.</small></label><button class="button" data-action="save-tags">Save tags</button></div><div class="organize-box"><h4>Move or file in sections</h4><div class="checks" id="sectionChecks">${tree.map(s=>`<label><input type="checkbox" value="${esc(s.id)}" ${(it.tags?.section||[]).includes(s.id)?'checked':''}>${esc((s.parent?'↳ ':'')+s.name)}</label>`).join('')}</div><p class="lede" style="font-size:11px;margin-top:9px">Uncheck a section to remove it. Check multiple to file in more than one place.</p><label class="field">Create a section or subsection<input id="newSection" placeholder="e.g. Build ideas / Voice tools"></label><button class="button" data-action="save-sections">Save sections</button></div><div class="organize-box"><h4>Research & source grouping</h4><div class="actions"><button class="button" data-action="refresh">Refresh from README</button><button class="button" data-action="combine">Combine with another topic</button>${it.members?.length?'<button class="button danger" data-action="split">Restore separate source tiles</button>':''}</div><p class="lede" style="font-size:11px;margin-top:9px">Combining creates a unified guide and preserves original sources. Restoring separates them again.</p></div>`;
 }
 return `<section class="tab-panel" id="panel-${key}" role="tabpanel" aria-labelledby="tab-${key}">${html}</section>`;
}
function wirePanel(){
 $$('.dialog .prose a').forEach(a=>{if(href(a.getAttribute('href'))==='#')a.removeAttribute('href');a.target='_blank';a.rel='noopener noreferrer';});
 const guide=$('#guideProse');if(guide){const headings=[...guide.querySelectorAll('h2,h3')];headings.forEach((h,i)=>{h.id='guide-section-'+i;h.classList.add('read-section');});if(headings.length>1){const nav=document.createElement('nav');nav.className='section-jumps';nav.setAttribute('aria-label','Jump to guide section');nav.innerHTML=headings.map(h=>`<a href="#${h.id}" data-jump="${h.id}">${esc(h.textContent)}</a>`).join('');guide.before(nav);}}
}
function selectTab(key){state.tab=key;$$('.detail-nav [data-tab]').forEach(b=>{b.setAttribute('aria-selected',String(b.dataset.tab===key));b.tabIndex=b.dataset.tab===key?0:-1;});$('#detailContent').innerHTML=panel(state.item);$('#detailContent').scrollTop=0;wirePanel();}
async function copy(text){if(!text)return toast('Nothing to copy on this topic.');try{await navigator.clipboard.writeText(text);toast('Copied');}catch{showDialog('Copy the text below',`<div class="small-content"><textarea aria-label="Text to copy" style="width:100%;min-height:260px" readonly>${esc(text)}</textarea></div>`,{small:true});$('.small-content textarea').select();}}

function showHow(){showDialog('How a saved reel becomes useful',`<div class="small-content prose"><p>Kiln turns interesting posts into practical research you can revisit, copy and build from.</p><div class="about-step"><span>01</span><div><strong>Muse prepares the source dossier</strong>Muse, Meta’s personal agent, produces a README with the original URL, transcript or visual notes, named tools and uncertainties. Its Instagram integration makes it a practical first reader. Access and transcript accuracy still depend on the source.</div></div><div class="about-step"><span>02</span><div><strong>Kiln researches what comes next</strong>The README is preserved locally. Kiln checks current sources, finds official resources and application links, explains installation and usage, and develops prompts, PDFs and project ideas where useful.</div></div><div class="about-step"><span>03</span><div><strong>Related evidence becomes one topic</strong>Incoming sources are compared with the library. Confident duplicates can be combined; ambiguous matches are reviewed. A unified guide keeps all original reel links and distinct approaches.</div></div><div class="about-step"><span>04</span><div><strong>Publish, verify, then archive</strong>The public export is checked for private data. After the live result and downloads are verified, the completed README moves from researched to Kilned and handled URLs leave the links document.</div></div><div class="comparison"><div><h4>On the public website</h4><ul><li>Search and filter topics, tags and sections</li><li>Read guides and original source links</li><li>Copy prompts and commands</li><li>Download PDFs and other files</li><li>See published project progress</li><li>Save bookmarks on your own device</li><li>Share a direct topic or filtered library link</li></ul></div><div><h4>In the local workspace</h4><ul><li>Import and research new READMEs</li><li>Edit tags, sections and progress</li><li>Review, merge or separate sources</li><li>Manage research failures and retries</li><li>Queue builds and answer decision cards</li><li>Keep credentials, raw dossiers and personal notes private</li></ul></div></div><p>The public site is a static snapshot. It has no write server, account credentials or access to the owner’s computer. Research, Drive cleanup and builds need those private capabilities, so they run locally. Public bookmarks are browser storage and do not change the owner’s library. Local changes appear after publishing.</p><p>“Ready” means the research can be used. “In progress” means the owner is working with it. “Made” records a completed outcome, not simply a completed read.</p><p>${link('https://github.com/muhammad-musa-ml/kiln','Read the source code and exact workflow on GitHub')}</p><p>${link('https://ai.meta.com/muse/','About Meta Muse')} · ${link('https://dev.meta.ai/docs/video-understanding','Meta’s video and audio documentation')}</p>${window.KILN_BUILT?'<p>Published snapshot: '+esc(window.KILN_BUILT)+'.</p>':''}</div>`,{small:true});}
function showImport(){showDialog('Import a Muse README',`<div class="small-content"><p class="lede">Add the researched dossier. Include the original reel or video URL near the top. Kiln will handle current research and useful deliverables.</p><form id="importForm"><label class="field">Choose Markdown files<input type="file" id="mdFiles" accept=".md,.markdown,text/markdown" multiple><small>Up to 50 files, 2 MB each. Originals are preserved locally.</small></label><label class="field">Or paste the README<textarea id="mdText" rows="10" placeholder="# Topic\nOriginal reel: https://www.instagram.com/reel/…\n\n## Transcript\n…"></textarea></label><div id="importError" class="error" role="alert"></div><button class="button primary" type="submit">Import and research</button></form></div>`,{small:true});$('#importForm').onsubmit=async ev=>{ev.preventDefault();const btn=ev.submitter;btn.disabled=true;try{const files=[];for(const f of $('#mdFiles').files){if(f.size>2000000)throw Error(f.name+' exceeds 2 MB.');files.push({name:f.name,text:await f.text()});}if($('#mdText').value.trim())files.push({name:'README.md',text:$('#mdText').value});if(!files.length)throw Error('Choose a Markdown file or paste its text.');const r=await post('/api/import',{files});closeDialog();toast(`${r.queued.length} README${r.queued.length===1?'':'s'} imported`);load();}catch(e){$('#importError').textContent=e.message;btn.disabled=false;}};}
async function showInbox(){
 showDialog('Research inbox','<div class="small-content"><span class="spinner"></span>Loading</div>',{small:true});
 try{const r=await api('/api/research');showDialog('Research inbox',`<div class="small-content"><p class="lede">Pending files stay in researched. Completed files move to Kilned only after live publication is verified.</p>${(r.documents||[]).map(d=>`<div class="file"><span class="badge">${esc(d.state)}</span><div><strong style="font-size:12px">${esc(d.name)}</strong>${d.error?`<small class="error">${esc(d.error)}</small><button class="button" data-retry="${esc(d.item_id)}">Retry research</button>`:''}</div></div>`).join('')||empty('No imported READMEs yet.')}<h3 style="margin-top:22px">Possible matches</h3><p class="lede" style="font-size:11px">Suggestions are not automatic merges. Open both topics to compare their scope before combining.</p>${(r.matches||[]).map(m=>`<div class="notice"><p>${esc(m.reason)} · ${Math.round(m.score*100)}% lexical match</p><div class="actions"><button class="button" data-open="${esc(m.item_id)}">New source</button><button class="button" data-open="${esc(m.candidate_id)}">Existing topic</button><button class="button" data-dismiss="${esc(m.item_id)}" data-candidate="${esc(m.candidate_id)}">Keep separate</button></div></div>`).join('')||empty('No unresolved matching suggestions.')}</div>`,{small:true});}catch(e){toast(e.message);}
}
async function showCombine(){const current=state.item;const r=await api('/api/items?limit=10000');showDialog('Combine matching topics',`<div class="small-content"><p class="lede">The result is a single synthesized guide. All source URLs and existing files are retained.</p><label class="field">Topic title<input id="combinedTitle" value="${esc(current.title)}"></label><label class="field">Combine with<select id="combineId">${r.items.filter(i=>i.id!==current.id).map(i=>`<option value="${i.id}">${esc(i.title)}</option>`).join('')}</select></label><button class="button primary" id="combineNow">Synthesize and combine</button><p id="combineState" class="lede" style="margin-top:12px"></p></div>`,{small:true});$('#combineNow').onclick=async()=>{const btn=$('#combineNow');btn.disabled=true;$('#combineState').textContent='Synthesizing the evidence. Original tiles remain available until the guide is ready…';try{const r=await post('/api/topics/merge',{ids:[current.id,$('#combineId').value],title:$('#combinedTitle').value});await load();openItem(r.id);}catch(e){$('#combineState').textContent=e.message;btn.disabled=false;}};}

async function localAction(action,button){const it=state.item;if(!it)return;button.disabled=true;try{
 if(action==='save-status'){await post('/api/status',{id:it.id,status:$('#itemStatus').value});toast('Progress saved');}
 if(action==='save-tags'){await post('/api/organize',{id:it.id,tags:$('#editTags').value.split(',').map(s=>s.trim()).filter(Boolean)});toast('Tags saved');}
 if(action==='save-sections'){await post('/api/organize',{id:it.id,sections:$$('#sectionChecks input:checked').map(i=>i.value),new_section:$('#newSection').value.trim()});toast('Sections saved');}
 if(action==='refresh'){await post('/api/reprocess',{id:it.id});toast('Research refresh queued');return load();}
 if(action==='split'){const r=await post('/api/topics/split',{id:it.id});await load();return openItem(r.ids[0]);}
 if(action==='build-queue'){const r=await post('/api/build',{id:it.id,target:'local'});$('#buildOut').innerHTML=`<p class="notice">${r.already?'Already queued.':'Project queued.'} A decision card lets you choose when to build. Research completion does not start a build.</p>`;return asks();}
 await load();await openItem(it.id,'organize');
 }catch(e){toast(e.message);}finally{button.disabled=false;}}
async function asks(){if(!LOCAL)return;try{const r=await api('/api/questions');$('#asks').innerHTML=(r.open||[]).map(q=>`<section class="notice" data-question="${esc(q.id)}"><h3>${esc(q.title||'A decision is waiting')}</h3><pre>${esc(q.detail||'')}</pre>${q.kind==='queue'?(q.projects||[]).map(p=>`<label class="field"><span><input type="checkbox" data-pick="${esc(p.job_id)}"> ${esc(p.what||p.repo||p.job_id)} · about ${esc(p.minutes)} min</span></label>`).join(''):''}<div class="actions">${(q.kind==='queue'?['all','some','none']:q.options||[]).map(o=>`<button class="button" data-answer="${esc(o)}">${esc(q.kind==='queue'?{all:'Build all',some:'Build selected',none:'None this time'}[o]:o)}</button>`).join('')}</div></section>`).join('');}catch{}}

document.addEventListener('click',async ev=>{
 const b=ev.target.closest('button,a[data-jump]');if(!b)return;
 if(b.dataset.open)return openItem(b.dataset.open);
 if(b.dataset.save)return toggleSaved(b.dataset.save);
 if(b.dataset.filter)return filter(b.dataset.filter,b.dataset.value);
 if(b.dataset.removeFilter){delete state.filters[b.dataset.removeFilter];return load();}
 if(b.hasAttribute('data-stage')){state.filters.stage=b.dataset.stage;return load();}
 if(b.dataset.tab){if(!state.item)return;return selectTab(b.dataset.tab);}
 if(b.dataset.jump){ev.preventDefault();document.getElementById(b.dataset.jump)?.scrollIntoView({block:'start'});return;}
 if(b.dataset.topicLink){closeDialog();state.filters.topic=b.dataset.topicLink;return load();}
 if(b.hasAttribute('data-copy-command')){const n=state.item.note||{};return copy((n.commands?.length?n.commands:n.code_snippets||[])[Number(b.dataset.copyCommand)]);}
 if(b.hasAttribute('data-copy-prompt'))return copy(state.item.note.prompts[Number(b.dataset.copyPrompt)].detail);
 if(b.dataset.retry){try{await post('/api/reprocess',{id:b.dataset.retry});toast('Retry queued');closeDialog();load();}catch(e){toast(e.message);}return;}
 if(b.dataset.dismiss){try{await post('/api/topics/dismiss',{id:b.dataset.dismiss,candidate_id:b.dataset.candidate});showInbox();}catch(e){toast(e.message);}return;}
 if(b.dataset.answer){const card=b.closest('[data-question]');const picked=[...card.querySelectorAll('[data-pick]:checked')].map(i=>i.dataset.pick);if(b.dataset.answer==='some'&&!picked.length)return toast('Choose at least one project.');try{await post('/api/questions/answer',{id:card.dataset.question,choice:b.dataset.answer,picked});toast('Decision saved');asks();}catch(e){toast(e.message);}return;}
 switch(b.dataset.action){case'close':return closeDialog();case'clear':return clearFilters();case'retry':return load();case'share':return copy(location.href);case'build-copy':return copy(state.item.build_prompt);case'copy-install':return copy(state.item.enrich.install.command);case'combine':return showCombine();default:if(b.dataset.action&&LOCAL)return localAction(b.dataset.action,b);}
});
$('#modal').addEventListener('click',ev=>{if(ev.target.classList.contains('backdrop'))closeDialog();});
document.addEventListener('keydown',ev=>{
 if(ev.key==='Escape'&&$('#modal').hasChildNodes())return closeDialog();
 if(ev.key==='/'&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)&&!$('#modal').hasChildNodes()){ev.preventDefault();$('#q').focus();}
 const dialog=$('.dialog');if(!dialog)return;
 if(ev.key==='Tab'){const all=[...dialog.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),textarea,select,summary,[tabindex="0"]')].filter(e=>e.offsetParent!==null);const first=all[0],last=all.at(-1);if(ev.shiftKey&&document.activeElement===first){ev.preventDefault();last.focus();}else if(!ev.shiftKey&&document.activeElement===last){ev.preventDefault();first.focus();}}
 if(['ArrowDown','ArrowRight','ArrowUp','ArrowLeft'].includes(ev.key)&&document.activeElement.matches('.detail-nav [role=tab]')){ev.preventDefault();const tabs=$$('.detail-nav [role=tab]'),i=tabs.indexOf(document.activeElement),j=(i+(['ArrowDown','ArrowRight'].includes(ev.key)?1:-1)+tabs.length)%tabs.length;selectTab(tabs[j].dataset.tab);tabs[j].focus();}
});
$('#q').oninput=ev=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.q=ev.target.value.trim();load();},230);};
$('#sort').onchange=ev=>{state.sort=ev.target.value;renderShelf();syncUrl();};
$('#clear').onclick=$('#everything').onclick=clearFilters;
$('#savedBtn').onclick=()=>{state.saved=!state.saved;load();};
$('#mobileFilters').onclick=()=>{const expanded=$('#rail').classList.toggle('expanded');$('#mobileFilters').setAttribute('aria-expanded',String(expanded));};
$('#howBtn').onclick=$('#footerHow').onclick=showHow;
$('#mode').textContent=LOCAL?'● Local workspace':'○ Public snapshot';$('#built').textContent=window.KILN_BUILT?'Published '+window.KILN_BUILT:'';
if(LOCAL){$('#importBtn').hidden=false;$('#inboxBtn').hidden=false;$('#importBtn').onclick=showImport;$('#inboxBtn').onclick=showInbox;}
$('#shelf').innerHTML='<div class="skeleton"></div>'.repeat(4);
load().then(()=>{const match=location.hash.match(/^#item=([a-f0-9]+)$/);if(match)openItem(match[1]);});asks();
setInterval(()=>{if(LOCAL&&Object.values(state.jobs).some(j=>['working','queued','followup'].includes(j.stage)))load();},4000);
if(LOCAL)setInterval(asks,60000);
