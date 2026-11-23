async function mountMeetFlow() {
  let root = document.querySelector("#meetflow");
  for (let i = 0; !root && i < 100; i++) {
    await new Promise(resolve => setTimeout(resolve, 50));
    root = document.querySelector("#meetflow");
  }
  if (!root || root.dataset.ready) return;
  root.dataset.ready = "true";
  const $ = id => root.querySelector("#" + id);
  const create = (tag, value, cls) => {
    const el = document.createElement(tag);
    if (value !== undefined) el.textContent = value;
    if (cls) el.className = cls;
    return el;
  };
  const sample = __MEETFLOW_SAMPLE__;
  let result = null, tab = "summary", isSample = false, busy = false;
  let serverKey = false;
  let unfinished=false, editingSource=false;
  const setNotice = text => { $("notice").textContent = text; };
  const count = () => { $("count").textContent = [...$("source").value].length.toLocaleString() + " 字符"; };
  function box(name, lines, style) {
    const section = create("section", undefined, "summarybox " + style);
    section.append(create("h4", name));
    const list = create("ul");
    lines.forEach(s => list.append(create("li", s)));
    section.append(list);
    return section;
  }
  function render() {
    clearHighlight();
    const view = $("view");
    view.replaceChildren();
    $("stab").setAttribute("aria-selected", tab === "summary");
    $("ttab").setAttribute("aria-selected", tab === "tasks");
    view.setAttribute("aria-labelledby", tab === "summary" ? "stab" : "ttab");
    syncControls();
    $("n").textContent = result ? result.tasks.filter(t=>t.state!=="dismissed").length : "–";
    $("copy").disabled = !result || busy || unfinished;
    $("run").disabled = !!savedId || busy || !$("source").value.trim();
    $("mode").textContent = busy ? (result?.summary && result.tasksReady ? "交叉核对中" : "整理中") :
      unfinished ? "整理中断" : isSample ? "示例预览" : savedId ? "历史会议" : result?.review_warning ? "核对未完成" : result ? "已整理" : "待整理";
    $("meta").textContent = isSample ? "预置示例 · 产品周会" : result ?
      savedId ? "已保存 · " + $("meetingDay").value : result.cached ? "已复用核对结果 · "+result.elapsed.toFixed(2)+" 秒" :
      "首项 "+result.first.toFixed(2)+" 秒"+(unfinished ? "" : " · 完整 "+result.elapsed.toFixed(2)+" 秒") : "";
    if (!result) {
      view.append(create("p", busy ? "正在生成摘要并核对待办原文…" : "整理完成后，会议摘要和待办会显示在这里。", "empty"));
      return;
    }
    if (result.review_warning) view.append(create("p",result.review_warning,"reviewnote"));
    if ((tab==="summary" && !result.summary) || (tab==="tasks" && unfinished && !result.tasksReady)){
      view.append(create("p",busy?"这一部分正在整理…":"这一部分未完成，可重新整理。","empty"));
      return;
    }
    const pending = result.tasks.filter(t=>t.state==="suggested").length;
    if (tab === "summary" && pending) view.append(button("核对发现 "+pending+" 项可能遗漏的行动，查看",()=>$("ttab").click()));
    if (tab === "summary") {
      const s = result.summary;
      view.append(create("h3", s.title), create("p", s.overview, "overview"));
      if (s.decisions.length) view.append(box("已确认结论", s.decisions, ""));
      if (s.open_questions.length) view.append(box("待确认问题", s.open_questions, "openbox"));
    } else {
      const active=result.tasks.filter(t=>t.state==="active");
      view.append(create("p","已完成 "+active.filter(t=>t.completed).length+" / "+active.length,"progress"));
      if (!active.length && !pending) view.append(create("p","本次会议未提取到待办事项。","empty"));
      for (const t of result.tasks.filter(t=>t.state!=="dismissed")) view.append(taskCard(t));
    }
  }
  function loadSample() {
    editingSource=false; unfinished=false;
    $("source").value = sample.text;
    savedId=null; result=prepare(sample); tab="summary"; isSample=true; $("meetingDay").value=today();
    count(); render(); setNotice("");
  }
  function openSettings() { $("dialog").showModal(); $("key").focus(); }
  $("settings").onclick = openSettings;
  const post = async (path,payload) => {
    const res=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const body=await res.json();
    if (!res.ok) throw Error(body.error || "本地服务请求失败");
    return body;
  };
  const resetConnection=()=>{ $("connection").textContent=$("key").value.trim() ?
    "已填写当前页面密钥 · 尚未验证" : serverKey ? "检测到环境变量 · 尚未验证" : "请填写密钥"; };
  $("key").oninput=resetConnection;
  $("checkkey").onclick=async()=>{
    $("checkkey").disabled=true; $("key").disabled=true; $("connection").textContent="正在验证模型…";
    try { const data=await post("/api/check",{key:$("key").value.trim()});
      $("connection").textContent="已验证 · "+data.model; }
    catch(e){ $("connection").textContent=e.message; }
    finally { $("checkkey").disabled=false; $("key").disabled=false; }
  };
  let poll;
  async function batchStatus() {
    clearTimeout(poll);
    try {
      const res=await fetch("/api/batch-status"); if(!res.ok) throw Error();
      const info=await res.json();
      $("batchrun").disabled=!!info.running;
      if(info.total) $("batchstate").textContent=info.message+" · 已处理 "+info.done+"/"+info.total+
        "，成功 "+info.success+"。结果目录："+info.folder;
      if(info.running) poll=setTimeout(batchStatus,1500);
    } catch { $("batchstate").textContent="暂时无法读取进度，正在重连。"; poll=setTimeout(batchStatus,3000); }
  }
  $("batchrun").onclick=async()=>{
    const suite=$("suite").value;
    $("batchrun").disabled=true;
    try { await post("/api/batch",{key:$("key").value.trim(),dataset:suite==="compare"?"zh":suite,compare:suite==="compare"});
      await batchStatus(); }
    catch(e){ $("batchstate").textContent=e.message; $("batchrun").disabled=false; }
  };
  $("savekey").onclick = () => { $("dialog").close(); setNotice(""); };
  $("example").onclick = () => {
    if ($("source").value.trim() && $("source").value !== sample.text &&
        !window.confirm("用产品周会示例替换当前原文？")) return;
    loadSample();
  };
  $("source").oninput = () => { savedId=null; result=null; isSample=false; unfinished=false; count(); render(); setNotice(""); };
  $("editSource").onclick=()=>{
    editingSource=true;syncControls();$("source").readOnly=false;$("source").focus();
  };
  $("clear").onclick = () => { $("source").value = ""; $("source").oninput(); $("source").focus(); };
  $("stab").onclick = () => { tab = "summary"; render(); };
  $("ttab").onclick = () => { tab = "tasks"; render(); };
  root.querySelector(".tabs").onkeydown = e => {
    if (!["ArrowLeft","ArrowRight","Home","End"].includes(e.key)) return;
    e.preventDefault();
    const target = e.key === "Home" ? $("stab") : e.key === "End" ? $("ttab") : tab === "summary" ? $("ttab") : $("stab");
    target.click(); target.focus();
  };
  $("copy").onclick = async () => {
    if (!result) return;
    const s = result.summary;
    const lines = [s.title, s.overview, "", "已确认结论", ...s.decisions, "", "待确认问题", ...s.open_questions, "", "待办清单",
      ...result.tasks.filter(t=>t.state==="active").map(t => (t.completed ? "[x] " : "[ ] ") + t.action + "｜负责人：" + (t.owner || "待确认") + "｜期限：" + (t.deadline || t.due || "待确认") + "\n   原文：" + t.original.evidence)];
    try { await navigator.clipboard.writeText(lines.join("\n")); setNotice("已复制会议摘要和待办清单。"); }
    catch { setNotice("浏览器尚未允许复制，请选中结果后按 Ctrl+C。"); }
  };
  async function runAnalysis(force) {
    if (busy || !$("source").value.trim()) return;
    if(force && !savedId && result?.tasks.some(t=>t.completed || t.action!==t.original.action ||
       t.owner!==(t.original.owner||"") || t.due!==(t.original.due||"") || t.deadline!==undefined || t.reminder!=="auto") &&
       !window.confirm("重新整理会替换当前未保存的修订，继续吗？")) return;
    const previous={result,savedId,isSample,unfinished};
    busy=true; unfinished=true; editingSource=false; result=null; savedId=null; isSample=false;
    $("run").textContent = "正在整理…";
    ["example","clear","source","settings"].forEach(id => { $(id).disabled = true; });
    setNotice(""); render();
    const start = performance.now();
    try {
      const response=await fetch("/api/analyze-stream",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({text:$("source").value,key:$("key").value.trim(),force})});
      if(!response.ok) throw Error("整理请求失败（"+response.status+"）。");
      const reader=response.body.getReader(), decoder=new TextDecoder();
      let buffer="", completed=false;
      function receive(msg){
        const elapsed=(performance.now()-start)/1000;
        if(msg.event==="error"){
          if(msg.code==="key") openSettings();
          throw Error(msg.message);
        }
        if(msg.event==="complete"){
          const final=prepare(msg.result);
          // Retain draft objects (including an open edit form) while adding verified candidates.
          if(result?.tasksReady) final.tasks=[...result.tasks,...final.tasks.filter(t=>t.state==="suggested")];
          if(!result) tab="summary";
          final.first=result?.first??elapsed;final.elapsed=elapsed;final.cached=msg.cached;
          result=final; unfinished=false;completed=true;return;
        }
        if(!["summary","tasks"].includes(msg.event)) return;
        if(!result){result={summary:null,tasks:[],tasksReady:false,first:elapsed};tab=msg.event;}
        if(msg.event==="summary") result.summary=msg.value;
        else {result.tasks=prepare(msg.value).tasks;result.tasksReady=true;}
        render();
      }
      try{
        while(!completed){
          const chunk=await reader.read();
          buffer+=decoder.decode(chunk.value,{stream:!chunk.done});
          const lines=buffer.split("\n");buffer=lines.pop();
          for(const line of lines) if(line.trim()) receive(JSON.parse(line));
          if(chunk.done) break;
        }
      }finally{reader.releaseLock();}
      if(!completed) throw Error("连接提前结束，请重新整理。");
    } catch (e) {
      if(!result) ({result,savedId,isSample,unfinished}=previous);
      setNotice(e.message || "请求失败，请检查本地服务。");
    }
    finally {
      busy = false;
      ["example","clear","source","settings"].forEach(id => { $(id).disabled = false; });
      $("run").textContent = "整理会议 ↗"; render();
    }
  }
  $("run").onclick=()=>runAnalysis(false);
  $("rerun").onclick=()=>runAnalysis(true);
  for (let i=0; i<43; i++) {
    const bar = create("i"); bar.style.height = (4 + 30 * Math.abs(Math.sin(i*.56)*Math.cos(i*.16))) + "px";
    root.querySelector(".wave").append(bar);
  }
  /* workspace controls */
  loadSample();
  await refresh().catch(e=>setNotice(e.message));
  try {
    const res = await fetch("/api/status"); serverKey = (await res.json()).configured === true;
    if (serverKey) $("keynote").textContent = "本机已配置密钥。留空使用原密钥，粘贴新密钥可仅供当前页面使用。";
    resetConnection(); await batchStatus();
  } catch { setNotice("本地服务连接异常，请刷新页面。"); }
  if(new URLSearchParams(location.search).get("settings")==="1") openSettings();
}

