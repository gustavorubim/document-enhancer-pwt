"""Self-contained interactive HTML visualization for one validated RAG graph snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast


def write_graph_html(
    snapshot: dict[str, object],
    output: Path,
    *,
    force: bool = False,
) -> dict[str, object]:
    """Write one dependency-free HTML graph observatory and return export metadata."""

    target = output.expanduser().resolve()
    if target.exists() and not force:
        raise ValueError(f"output already exists; pass --force to replace it: {target}")
    if target.exists() and not target.is_file():
        raise ValueError(f"output is not a regular file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    # Keep untrusted document labels and excerpts inert inside a script element.
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    html = _HTML.replace("__GRAPH_DATA__", encoded)
    target.write_text(html, encoding="utf-8")
    counts = cast(dict[str, object], snapshot.get("counts") or {})
    return {
        "schema_version": "document-enhancer.graph-html-export.v1",
        "output": str(target),
        "size_bytes": target.stat().st_size,
        "self_contained": True,
        "catalog_digest": snapshot.get("catalog_digest"),
        "counts": counts,
    }


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="color-scheme" content="dark">
<link rel="icon" href="data:,">
<title>Document Enhancer · Graph Observatory</title>
<style>
:root{--bg:#050711;--panel:rgba(13,18,36,.88);--line:rgba(132,158,255,.18);--text:#edf2ff;--muted:#8f9abc;--cyan:#5de5ff;--violet:#a78bfa;--pink:#ff77c8;--green:#58e6a9;--amber:#ffd166}
*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0;overflow:hidden;background:radial-gradient(circle at 50% 35%,#101936 0,#080b19 42%,#03040b 100%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
button,input,select{font:inherit;color:inherit}button,select,input{border:1px solid var(--line);background:rgba(8,12,27,.88);border-radius:9px}button{cursor:pointer;padding:8px 11px;transition:.2s}button:hover{border-color:var(--cyan);box-shadow:0 0 18px rgba(93,229,255,.12)}
#app{display:grid;grid-template-columns:278px 1fr 330px;grid-template-rows:66px 1fr;height:100%}.top{grid-column:1/-1;display:flex;align-items:center;gap:18px;padding:0 20px;border-bottom:1px solid var(--line);background:rgba(4,7,17,.78);backdrop-filter:blur(18px);z-index:4}.brand{display:flex;align-items:center;gap:12px;min-width:300px}.orb{width:34px;height:34px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#fff 0,#5de5ff 12%,#7467ff 43%,#16122c 72%);box-shadow:0 0 26px rgba(93,229,255,.45)}.brand h1{font-size:15px;letter-spacing:.12em;text-transform:uppercase;margin:0}.brand small{display:block;color:var(--muted);letter-spacing:.02em;text-transform:none;margin-top:3px}.metrics{display:flex;gap:8px;overflow:auto}.metric{white-space:nowrap;padding:7px 10px;border:1px solid var(--line);border-radius:9px;background:rgba(19,25,49,.58)}.metric b{color:var(--cyan);font-size:14px}.metric span{color:var(--muted);font-size:11px;margin-left:5px;text-transform:uppercase;letter-spacing:.08em}.top-actions{margin-left:auto;display:flex;gap:8px}
.panel{z-index:3;background:var(--panel);backdrop-filter:blur(16px);overflow:auto}.left{border-right:1px solid var(--line);padding:18px}.right{border-left:1px solid var(--line);padding:18px}.panel h2{font-size:11px;text-transform:uppercase;letter-spacing:.16em;color:#aeb9da;margin:4px 0 10px}.field{margin-bottom:15px}.field input,.field select{width:100%;padding:10px 11px;outline:none}.field input:focus,.field select:focus{border-color:var(--cyan);box-shadow:0 0 0 3px rgba(93,229,255,.08)}.hint{font-size:11px;line-height:1.55;color:var(--muted)}.row{display:flex;gap:8px}.row>*{flex:1}.switch{display:flex;align-items:center;justify-content:space-between;padding:9px 0;color:#cbd4ef;font-size:12px}.switch input{accent-color:#71dfff}.legend{display:grid;gap:7px;margin:8px 0 18px}.legend-item{display:flex;align-items:center;gap:8px;font-size:12px;color:#cbd4ef}.dot{width:9px;height:9px;border-radius:50%;box-shadow:0 0 9px currentColor}.kbd{border:1px solid var(--line);border-bottom-color:rgba(132,158,255,.4);border-radius:5px;padding:1px 5px;background:#11172b;color:#d8e1ff;font-size:10px}
.stage{position:relative;overflow:hidden;min-width:0}.stage:before{content:"";position:absolute;inset:0;background-image:radial-gradient(rgba(130,165,255,.35) .6px,transparent .6px);background-size:29px 29px;mask-image:linear-gradient(to bottom,rgba(0,0,0,.55),transparent 72%);pointer-events:none}canvas{display:block;width:100%;height:100%;cursor:grab;touch-action:none}canvas.dragging{cursor:grabbing}.hud{position:absolute;left:18px;bottom:16px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:rgba(6,9,21,.72);color:var(--muted);font-size:11px;backdrop-filter:blur(10px);pointer-events:none}.search-status{position:absolute;top:14px;left:50%;transform:translateX(-50%);padding:7px 11px;border:1px solid var(--line);border-radius:999px;background:rgba(6,9,21,.75);color:#cfd8f4;font-size:11px;opacity:0;transition:.2s;pointer-events:none}.search-status.show{opacity:1}
.empty{color:var(--muted);font-size:13px;line-height:1.65;margin-top:18px}.badge{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:4px 8px;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--cyan);margin:0 5px 6px 0}.node-title{font-size:20px;line-height:1.2;margin:8px 0 10px}.node-id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10px;color:#7f8aad;word-break:break-all;padding:8px;border:1px solid var(--line);border-radius:8px;background:rgba(4,7,17,.5)}.detail-section{margin-top:20px}.detail-section h3{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:#aeb9da;margin:0 0 9px}.evidence,.neighbor{border:1px solid var(--line);border-radius:10px;padding:10px;margin:8px 0;background:rgba(8,12,27,.55)}.evidence strong{display:block;color:#dce5ff;font-size:11px;margin-bottom:5px}.evidence p{color:#aeb9da;font-size:11px;line-height:1.5;margin:0}.neighbor{display:block;width:100%;text-align:left;color:#cfd8f4;font-size:11px}.neighbor span{color:var(--muted);float:right}.footer-digest{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9px;color:#66718f;word-break:break-all;margin-top:18px}
@media(max-width:1050px){#app{grid-template-columns:235px 1fr}.right{display:none}.brand{min-width:230px}.top-actions{display:none}}@media(max-width:720px){#app{grid-template-columns:1fr;grid-template-rows:58px 1fr}.left{position:absolute;z-index:8;top:58px;bottom:0;width:270px;transform:translateX(-100%);transition:.25s}.left.open{transform:translateX(0)}.brand small,.metrics{display:none}.top{padding:0 12px}.brand{min-width:0}.mobile-menu{display:block!important}.hud{font-size:10px}}.mobile-menu{display:none}
</style>
</head>
<body>
<div id="app">
  <header class="top">
    <button class="mobile-menu" id="menuBtn">☰</button>
    <div class="brand"><div class="orb"></div><div><h1>Graph Observatory</h1><small>Document Enhancer · self-contained 3D topology</small></div></div>
    <div class="metrics" id="metrics"></div>
    <div class="top-actions"><button id="resetBtn">Reset view</button><button id="fitBtn">Fit graph</button><button id="pauseBtn">Pause</button></div>
  </header>
  <aside class="panel left" id="leftPanel">
    <h2>Navigate</h2>
    <div class="field"><input id="search" autocomplete="off" placeholder="Search label, ID, type…"><div class="hint">Press Enter to jump through matches.</div></div>
    <div class="field"><label class="hint" for="docFilter">Document</label><select id="docFilter"><option value="">All documents</option></select></div>
    <div class="field"><label class="hint" for="typeFilter">Node type</label><select id="typeFilter"><option value="">All node types</option></select></div>
    <div class="field"><label class="hint" for="edgeFilter">Relationship</label><select id="edgeFilter"><option value="">All relationships</option></select></div>
    <div class="row"><button id="clearBtn">Clear filters</button><button id="reheatBtn">Reheat</button></div>
    <h2 style="margin-top:22px">Display</h2>
    <label class="switch"><span>Node labels</span><input id="labelsToggle" type="checkbox" checked></label>
    <label class="switch"><span>Flow particles</span><input id="particlesToggle" type="checkbox" checked></label>
    <label class="switch"><span>Color by document</span><input id="colorToggle" type="checkbox"></label>
    <h2 style="margin-top:18px">Legend</h2><div class="legend" id="legend"></div>
    <h2>Controls</h2>
    <div class="hint">Drag to rotate · <span class="kbd">Shift</span> + drag to pan · wheel/pinch to zoom · click a node for evidence · <span class="kbd">R</span> reset · <span class="kbd">Space</span> pause.</div>
  </aside>
  <main class="stage"><canvas id="graph" aria-label="Interactive 3D document graph"></canvas><div class="search-status" id="searchStatus"></div><div class="hud" id="hud"></div></main>
  <aside class="panel right" id="details"><h2>Node inspector</h2><div class="empty">Select a node to inspect its document, type, connected relationships, provenance, and linked evidence excerpts.</div></aside>
</div>
<script>
"use strict";
const DATA=__GRAPH_DATA__;
const TYPE_COLORS={Section:"#5de5ff",Control:"#ff77c8",Risk:"#ff6b6b",Evidence:"#58e6a9",Requirement:"#ffd166",Record:"#a78bfa",Role:"#70a1ff",Process:"#4dd4ac",Decision:"#f7b267",System:"#9b8afb",Dependency:"#ed8fff",EscalationPath:"#ff9f68"};
const DOC_COLORS=["#5de5ff","#ff77c8","#58e6a9","#ffd166","#a78bfa","#ff8c69","#69a7ff","#d5ff69","#ff6f91","#74f2ce"];
const $=id=>document.getElementById(id), canvas=$("graph"), ctx=canvas.getContext("2d",{alpha:true});
const docById=new Map(DATA.documents.map((d,i)=>[d.run_id,{...d,index:i}]));
function hash(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return h>>>0}
function random3(id){let h=hash(id);const r=()=>{h=(Math.imul(h,1664525)+1013904223)>>>0;return h/4294967296};return [r(),r(),r()]}
const nodes=DATA.nodes.map((n,i)=>{const r=random3(n.id),d=docById.get(n.run_id)||{index:0};const a=(d.index/Math.max(DATA.documents.length,1))*Math.PI*2,cluster=DATA.documents.length>1?135:0;return {...n,index:i,x:(r[0]-.5)*180+Math.cos(a)*cluster,y:(r[1]-.5)*180,z:(r[2]-.5)*180+Math.sin(a)*cluster,vx:0,vy:0,vz:0,visible:true,sx:0,sy:0,sz:0,sr:4}});
const byId=new Map(nodes.map(n=>[n.id,n]));
const edges=DATA.edges.map((e,i)=>({...e,index:i,sourceNode:byId.get(e.source),targetNode:byId.get(e.target)})).filter(e=>e.sourceNode&&e.targetNode);
const adjacency=new Map(nodes.map(n=>[n.id,[]]));edges.forEach(e=>{adjacency.get(e.source).push({node:e.targetNode,edge:e});adjacency.get(e.target).push({node:e.sourceNode,edge:e})});
let width=1,height=1,dpr=1,rotationX=-.22,rotationY=.32,zoom=1,panX=0,panY=0,paused=false,showLabels=true,showParticles=true,colorByDocument=false,selected=null,hovered=null,temperature=1,searchMatches=[],searchCursor=-1,lastTime=0;
const pointer={down:false,x:0,y:0,startX:0,startY:0,mode:"rotate",moved:false};
function populate(){DATA.documents.forEach(d=>$("docFilter").add(new Option(d.title,d.run_id)));[...new Set(nodes.map(n=>n.type))].sort().forEach(v=>$("typeFilter").add(new Option(v,v)));[...new Set(edges.map(e=>e.type))].sort().forEach(v=>$("edgeFilter").add(new Option(v,v)));$("metrics").innerHTML=[[DATA.counts.documents,"documents"],[DATA.counts.nodes,"nodes"],[DATA.counts.edges,"edges"],[DATA.counts.linked_nodes,"evidence-linked"]].map(([v,l])=>`<div class="metric"><b>${v}</b><span>${l}</span></div>`).join("");renderLegend()}
function renderLegend(){const counts={};nodes.filter(n=>n.visible).forEach(n=>counts[n.type]=(counts[n.type]||0)+1);$("legend").innerHTML=Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,12).map(([t,c])=>`<div class="legend-item" style="color:${typeColor(t)}"><span class="dot"></span><span>${escapeHtml(t)}</span><span style="margin-left:auto;color:#6f7a99">${c}</span></div>`).join("")}
function typeColor(t){return TYPE_COLORS[t]||`hsl(${hash(t)%360} 78% 68%)`}
function nodeColor(n){return colorByDocument?DOC_COLORS[(docById.get(n.run_id)?.index||0)%DOC_COLORS.length]:typeColor(n.type)}
function escapeHtml(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
function resize(){const rect=canvas.getBoundingClientRect();dpr=Math.min(devicePixelRatio||1,2);width=Math.max(1,rect.width);height=Math.max(1,rect.height);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0)}
function filters(){return {doc:$("docFilter").value,type:$("typeFilter").value,edge:$("edgeFilter").value,q:$("search").value.trim().toLowerCase()}}
function applyFilters(){const f=filters();nodes.forEach(n=>n.visible=(!f.doc||n.run_id===f.doc)&&(!f.type||n.type===f.type));searchMatches=f.q?nodes.filter(n=>{const evidence=n.evidence.map(e=>`${e.heading_path.join(" ")} ${e.excerpt}`).join(" ");return n.visible&&`${n.label} ${n.id} ${n.original_id} ${n.type} ${docById.get(n.run_id)?.title||""} ${n.provenance_span_ids.join(" ")} ${evidence}`.toLowerCase().includes(f.q)}):[];searchCursor=-1;renderLegend();temperature=Math.max(temperature,.35);const visible=nodes.filter(n=>n.visible).length;$("hud").textContent=`${visible} visible nodes · ${visibleEdges().length} relationships · ${paused?"paused":"live 3D layout"}`;showSearchStatus(f.q?`${searchMatches.length} search match${searchMatches.length===1?"":"es"}`:"")}
function visibleEdges(){const ef=$("edgeFilter").value;return edges.filter(e=>e.sourceNode.visible&&e.targetNode.visible&&(!ef||e.type===ef))}
function project(n){const cy=Math.cos(rotationY),sy=Math.sin(rotationY),cx=Math.cos(rotationX),sx=Math.sin(rotationX);const x1=n.x*cy-n.z*sy,z1=n.x*sy+n.z*cy,y1=n.y;const y2=y1*cx-z1*sx,z2=y1*sx+z1*cx;const p=700/Math.max(180,700+z2);n.sx=width/2+panX+x1*zoom*p;n.sy=height/2+panY+y2*zoom*p;n.sz=z2;n.sr=Math.max(2.3,(4+Math.min(n.evidence.length,4)*.65)*p*Math.sqrt(zoom));return n}
function simulate(){if(paused||temperature<.002)return;const visible=nodes.filter(n=>n.visible),n=visible.length;if(!n)return;const stride=n>450?Math.ceil(n/180):1;for(let i=0;i<n;i++){const a=visible[i];for(let j=i+1;j<n;j+=stride){const b=visible[j],dx=a.x-b.x,dy=a.y-b.y,dz=a.z-b.z,d2=dx*dx+dy*dy+dz*dz+45,force=1500*temperature/d2,inv=1/Math.sqrt(d2);a.vx+=dx*inv*force;a.vy+=dy*inv*force;a.vz+=dz*inv*force;b.vx-=dx*inv*force;b.vy-=dy*inv*force;b.vz-=dz*inv*force}}visibleEdges().forEach(e=>{const a=e.sourceNode,b=e.targetNode,dx=b.x-a.x,dy=b.y-a.y,dz=b.z-a.z,d=Math.sqrt(dx*dx+dy*dy+dz*dz)||1,f=(d-74)*.0022*temperature;a.vx+=dx/d*f;a.vy+=dy/d*f;a.vz+=dz/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f;b.vz-=dz/d*f});visible.forEach(a=>{const d=docById.get(a.run_id),angle=((d?.index||0)/Math.max(DATA.documents.length,1))*Math.PI*2,target=DATA.documents.length>1?110:0;a.vx+=(Math.cos(angle)*target-a.x)*.00045*temperature;a.vy+=-a.y*.0004*temperature;a.vz+=(Math.sin(angle)*target-a.z)*.00045*temperature;a.vx*=.88;a.vy*=.88;a.vz*=.88;a.x+=a.vx;a.y+=a.vy;a.z+=a.vz});temperature*=.992}
function draw(t){ctx.clearRect(0,0,width,height);const projected=nodes.filter(n=>n.visible).map(project),es=visibleEdges(),neighborIds=selected?new Set(adjacency.get(selected.id).map(v=>v.node.id)):new Set();ctx.lineCap="round";es.forEach(e=>{const a=e.sourceNode,b=e.targetNode,hot=selected&&(a===selected||b===selected);ctx.beginPath();ctx.moveTo(a.sx,a.sy);ctx.lineTo(b.sx,b.sy);ctx.strokeStyle=hot?"rgba(93,229,255,.72)":"rgba(119,139,203,.17)";ctx.lineWidth=hot?1.6:.65;ctx.stroke();if(showParticles&&es.length<1000){const phase=((t*.000055)+(hash(e.source+e.target)%997)/997)%1,px=a.sx+(b.sx-a.sx)*phase,py=a.sy+(b.sy-a.sy)*phase;ctx.fillStyle=hot?"#ffffff":"rgba(93,229,255,.5)";ctx.beginPath();ctx.arc(px,py,hot?2.1:1.15,0,Math.PI*2);ctx.fill()}});projected.sort((a,b)=>b.sz-a.sz).forEach(n=>{const match=searchMatches.includes(n),related=selected&&(n===selected||neighborIds.has(n.id)),dimmed=selected&&!related;const c=nodeColor(n),r=n.sr*(n===selected?1.85:hovered===n?1.4:match?1.3:1);ctx.globalAlpha=dimmed?.18:1;ctx.shadowColor=c;ctx.shadowBlur=n===selected?26:match?18:8;ctx.fillStyle=c;ctx.beginPath();ctx.arc(n.sx,n.sy,r,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;if(n===selected||match){ctx.strokeStyle=n===selected?"#fff":c;ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(n.sx,n.sy,r+4+(match?Math.sin(t*.006)*2:0),0,Math.PI*2);ctx.stroke()}if(showLabels&&(n===selected||match||hovered===n||projected.length<90)){ctx.font=`${n===selected?"600 ":""}${n===selected?12:10}px ui-sans-serif,system-ui`;ctx.textAlign="center";ctx.fillStyle=dimmed?"rgba(220,230,255,.2)":"rgba(230,238,255,.9)";ctx.fillText(n.label.length>34?n.label.slice(0,32)+"…":n.label,n.sx,n.sy-r-7)}ctx.globalAlpha=1})}
function frame(t){const dt=Math.min(32,t-lastTime||16);lastTime=t;for(let i=0;i<(dt>24?1:2);i++)simulate();draw(t);requestAnimationFrame(frame)}
function nearest(x,y){let best=null,dist=18;nodes.filter(n=>n.visible).forEach(n=>{const d=Math.hypot(n.sx-x,n.sy-y);if(d<Math.max(dist,n.sr+8)){best=n;dist=d}});return best}
function selectNode(n){selected=n;if(!n){renderDetails();return}renderDetails();showSearchStatus(`${n.label} · ${n.type}`)}
function renderDetails(){const box=$("details");if(!selected){box.innerHTML='<h2>Node inspector</h2><div class="empty">Select a node to inspect its document, type, connected relationships, provenance, and linked evidence excerpts.</div>';return}const doc=docById.get(selected.run_id),neighbors=adjacency.get(selected.id)||[];box.innerHTML=`<h2>Node inspector</h2><span class="badge">${escapeHtml(selected.type)}</span><span class="badge">${selected.evidence.length} evidence link${selected.evidence.length===1?"":"s"}</span><div class="node-title">${escapeHtml(selected.label)}</div><div class="hint">${escapeHtml(doc?.title||selected.run_id)}</div><div class="node-id">${escapeHtml(selected.id)}</div><div class="detail-section"><h3>Connected nodes · ${neighbors.length}</h3>${neighbors.length?neighbors.slice(0,40).map(v=>`<button class="neighbor" data-node="${escapeHtml(v.node.id)}">${escapeHtml(v.node.label)}<span>${escapeHtml(v.edge.type)}</span></button>`).join(""):'<div class="empty">No relationships.</div>'}</div><div class="detail-section"><h3>Linked evidence</h3>${selected.evidence.length?selected.evidence.map(e=>`<div class="evidence"><strong>${escapeHtml(e.heading_path.join(" › "))}</strong><p>${escapeHtml(e.excerpt)}</p></div>`).join(""):'<div class="empty">No final-document chunk is linked to this node.</div>'}</div><div class="detail-section"><h3>Provenance spans</h3><div class="node-id">${escapeHtml(selected.provenance_span_ids.join(", ")||"none")}</div></div><div class="footer-digest">Catalog ${escapeHtml(DATA.catalog_digest)}</div>`;box.querySelectorAll("[data-node]").forEach(btn=>btn.addEventListener("click",()=>focusNode(byId.get(btn.dataset.node))))}
function focusNode(n){if(!n)return;selected=n;const p=project(n);panX+=width/2-p.sx;panY+=height/2-p.sy;zoom=Math.max(zoom,1.15);renderDetails();showSearchStatus(`${n.label} · ${n.type}`)}
function resetView(){rotationX=-.22;rotationY=.32;zoom=1;panX=panY=0;selected=null;renderDetails();temperature=Math.max(temperature,.25)}
function fitGraph(){const visible=nodes.filter(n=>n.visible);if(!visible.length)return;const xs=visible.map(n=>n.x),ys=visible.map(n=>n.y),zs=visible.map(n=>n.z),span=Math.max(Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys),Math.max(...zs)-Math.min(...zs),100);zoom=Math.min(width,height)*.68/span;panX=panY=0}
function showSearchStatus(text){const s=$("searchStatus");s.textContent=text;s.classList.toggle("show",!!text);clearTimeout(showSearchStatus.timer);if(text)showSearchStatus.timer=setTimeout(()=>s.classList.remove("show"),2400)}
canvas.addEventListener("pointerdown",e=>{canvas.setPointerCapture(e.pointerId);pointer.down=true;pointer.startX=pointer.x=e.clientX;pointer.startY=pointer.y=e.clientY;pointer.mode=e.shiftKey||e.button===1?"pan":"rotate";pointer.moved=false;canvas.classList.add("dragging")});canvas.addEventListener("pointermove",e=>{const rect=canvas.getBoundingClientRect(),x=e.clientX,y=e.clientY;if(pointer.down){const dx=x-pointer.x,dy=y-pointer.y;if(Math.hypot(x-pointer.startX,y-pointer.startY)>4)pointer.moved=true;if(pointer.mode==="pan"){panX+=dx;panY+=dy}else{rotationY+=dx*.006;rotationX+=dy*.006}pointer.x=x;pointer.y=y}else{hovered=nearest(x-rect.left,y-rect.top)}});canvas.addEventListener("pointerup",e=>{const rect=canvas.getBoundingClientRect();if(!pointer.moved)selectNode(nearest(e.clientX-rect.left,e.clientY-rect.top));pointer.down=false;canvas.classList.remove("dragging")});canvas.addEventListener("wheel",e=>{e.preventDefault();zoom=Math.max(.18,Math.min(5,zoom*Math.exp(-e.deltaY*.001)))},{passive:false});canvas.addEventListener("dblclick",e=>{const rect=canvas.getBoundingClientRect();focusNode(nearest(e.clientX-rect.left,e.clientY-rect.top))});
[$("docFilter"),$("typeFilter"),$("edgeFilter")].forEach(el=>el.addEventListener("change",applyFilters));$("search").addEventListener("input",applyFilters);$("search").addEventListener("keydown",e=>{if(e.key==="Enter"&&searchMatches.length){searchCursor=(searchCursor+1)%searchMatches.length;focusNode(searchMatches[searchCursor])}});$("clearBtn").onclick=()=>{$("search").value=$("docFilter").value=$("typeFilter").value=$("edgeFilter").value="";applyFilters()};$("reheatBtn").onclick=()=>temperature=1;$("resetBtn").onclick=resetView;$("fitBtn").onclick=fitGraph;$("pauseBtn").onclick=()=>{paused=!paused;$("pauseBtn").textContent=paused?"Resume":"Pause";applyFilters()};$("labelsToggle").onchange=e=>showLabels=e.target.checked;$("particlesToggle").onchange=e=>showParticles=e.target.checked;$("colorToggle").onchange=e=>{colorByDocument=e.target.checked;renderLegend()};$("menuBtn").onclick=()=>$("leftPanel").classList.toggle("open");window.addEventListener("resize",resize);window.addEventListener("keydown",e=>{if(e.target.matches("input,select"))return;if(e.key.toLowerCase()==="r")resetView();if(e.code==="Space"){e.preventDefault();$("pauseBtn").click()}if(e.key.toLowerCase()==="l"){$("labelsToggle").click()}});
populate();resize();applyFilters();renderDetails();requestAnimationFrame(frame);
</script>
</body>
</html>
"""


__all__ = ["write_graph_html"]
