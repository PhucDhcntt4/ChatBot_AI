const $ = (id) => document.getElementById(id);
let activeName=null, originalContent="";
async function json(response){ const data=await response.json().catch(()=>({})); if(!response.ok) throw new Error(data.detail||"Yêu cầu thất bại"); return data; }
function notice(message,error=false){ const el=$("promptNotice"); el.textContent=message; el.className=`notice show${error?" error":""}`; }
function dirty(){ const changed=activeName && $("promptEditor").value!==originalContent; $("saveState").textContent=changed?"Có thay đổi chưa lưu":"Đã đồng bộ"; }
async function loadFile(name){
  const data=await json(await fetch(`/admin/prompts/api/files/${encodeURIComponent(name)}`)); activeName=name; originalContent=data.content; $("promptEditor").value=data.content; $("promptEditor").disabled=false; $("promptTitle").textContent=data.label; $("promptMeta").textContent=data.name; $("savePrompt").disabled=false; $("reloadPrompt").disabled=false; document.querySelectorAll(".prompt-item").forEach(el=>el.classList.toggle("active",el.dataset.name===name)); dirty();
}
async function loadList(){ const data=await json(await fetch("/admin/prompts/api/files")); $("promptList").innerHTML=data.files.map(file=>`<button class="prompt-item" type="button" data-name="${file.name}"><b>${file.label}</b><br><span class="editor-meta">${file.name}</span></button>`).join(""); document.querySelectorAll(".prompt-item").forEach(el=>el.onclick=()=>loadFile(el.dataset.name).catch(e=>notice(e.message,true))); if(data.files.length) loadFile(data.files[0].name); }
$("promptEditor").oninput=dirty;
$("reloadPrompt").onclick=()=>{ if(activeName) loadFile(activeName).catch(e=>notice(e.message,true)); };
$("savePrompt").onclick=async()=>{ if(!activeName)return; $("savePrompt").disabled=true; try{ await json(await fetch(`/admin/prompts/api/files/${encodeURIComponent(activeName)}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:$("promptEditor").value})})); originalContent=$("promptEditor").value; dirty(); notice("Đã lưu file TXT, tạo bản dự phòng và áp dụng cho chatbot."); }catch(error){ notice(error.message,true); }finally{$("savePrompt").disabled=false;} };
window.addEventListener("beforeunload",event=>{ if(activeName && $("promptEditor").value!==originalContent){event.preventDefault();event.returnValue="";} });
loadList().catch(e=>notice(e.message,true));
