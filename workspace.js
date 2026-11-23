  let page="work", savedId=null, editing=null, saving=false, searchToken=0;
  let index={meetings:[],tasks:[],aliases:[]}, listSequence=0, searchIds=null;
  const ws=(op,data={})=>post("/api/workspace",{op,...data});
  const localStamp=(dt=new Date())=>new Date(dt.getTime()-dt.getTimezoneOffset()*60000).toISOString().slice(0,16);
  const today=()=>localStamp().slice(0,10);
  function button(label,handler) {
    const b=create("button",label,"textbtn");
    b.type="button";
    b.onclick=async()=>{b.disabled=true;try {await handler();} catch(e){setNotice(e.message);} finally {b.disabled=false;}};
    return b;
  }
  function prepare(data) {
    const wrap=(t,state)=>({action:t.action,owner:t.owner||"",due:t.due||"",reminder:"auto",completed:false,state,original:t});
    return {...data,tasks:[...data.tasks.map(t=>wrap(t,"active")),...(data.suggestions||[]).map(t=>wrap(t,"suggested"))]};
  }
  function syncControls() {
    $("saveMeeting").disabled=!result || busy || unfinished || saving || !!savedId;
    $("saveMeeting").textContent=savedId?"已保存":saving?"正在保存…":"保存会议";
    $("meetingDay").disabled=!!savedId || busy || saving;
    $("source").readOnly=!!savedId || saving;
    $("run").hidden=!!result && !isSample && !busy;
    $("rerun").hidden=!result || isSample || busy;
    $("rerun").disabled=saving;
    const reading=!!result && !editingSource;
    $("source").hidden=reading;
    $("sourceReader").hidden=!reading;
    $("editSource").hidden=!reading || busy;
    $("editSource").disabled=saving;
    if(reading && readerText!==($("source").value)){
      readerText=$("source").value;
      $("sourceReader").textContent=readerText;
      $("sourceReader").scrollTop=0;
    }
    for(const id of ["example","clear","source","settings"]) $(id).disabled=busy||saving;
  }
  const titleByPage={work:"MeetFlow",history:"历史会议",todos:"我的待办"};
  function show(p) {
    page=p;
    root.querySelector(".columns").hidden=p!=="work";
    $("archive").hidden=p!=="history"; $("planner").hidden=p!=="todos";
    $("pageTitle").textContent=titleByPage[p];
    $("subtitle").textContent={work:"从会议原文中提炼结论，理清每一项待办。",history:"按开会日期回看原文、摘要与办结进度。",todos:"按截止日期查看各场会议中的行动。"}[p];
    Object.keys(titleByPage).forEach(k=>$("nav-"+k).setAttribute("aria-current",k===p?"page":"false"));
    draw();
  }
  function adopt(m) {
    editingSource=false; unfinished=false;
    savedId=m.id; result=m; isSample=false;
    $("source").value=m.text; $("meetingDay").value=m.day;
    count(); render();
  }
  async function openMeeting(id,taskId=null) {
    if (busy||saving) throw Error("请等待本次整理或保存完成。");
    if (!savedId && result && !isSample && !confirm("打开历史会议会替换当前未保存的结果，继续吗？")) return;
    const data=await ws("open",{id});
    tab="tasks"; adopt(data.meeting); show("work"); setNotice("");
    if(taskId){
      const task=result.tasks.find(item=>item.id===taskId);
      if(task) showSource(task.original.citations?.action,true);
    }
  }
  function mine(t) {
    return !!t.owner && index.aliases.some(n=>n.toLowerCase()===t.owner.trim().toLowerCase());
  }
  const alarmTime=t=>t.reminder==="auto" ? t.deadline ? t.deadline+"T09:00":"" : t.reminder==="off"?"":t.reminder;
  function drawAlarms() {
    const now=localStamp();
    const items=index.tasks.filter(t=>t.state==="active" && !t.completed && mine(t) && alarmTime(t) && alarmTime(t)<=now && t.seen!==alarmTime(t));
    const panel=$("alarms");
    panel.hidden=!items.length;
    if (panel.dataset.version===JSON.stringify(items)) return;
    panel.dataset.version=JSON.stringify(items);
    panel.replaceChildren();
    if (items.length) panel.append(create("strong","到时提醒 · "+items.length));
    items.forEach(t=>{
      const row=create("div",undefined,"alarmrow");
      row.append(button(t.action,()=>openMeeting(t.meeting)),create("small",alarmTime(t).replace("T"," ")),
        button("知道了",()=>change(t,{ack:true})));
      panel.append(row);
    });
  }
  async function refresh() {
    const seq=++listSequence;
    const data=await ws("list");
    if(seq!==listSequence) return;
    const changed=JSON.stringify(index)!==JSON.stringify(data);
    index=data;
    if(changed && savedId && result?.tasks.some(t=>t.id && t.revision!==data.tasks.find(x=>x.id===t.id)?.revision)){
      const current=savedId, full=await ws("open",{id:current});
      if(seq===listSequence && current===savedId) adopt(full.meeting);
    }
    if(changed || draw.lastDay!==today()) draw();
    else drawAlarms();
  }
  let readerText=null, hoverTimer, fadeTimer;
  function clearHighlight(fade=false){
    clearTimeout(hoverTimer); clearTimeout(fadeTimer);
    const mark=$("sourceReader").querySelector("mark");
    if(!mark) return;
    if(fade){
      mark.classList.add("fading");
      fadeTimer=setTimeout(()=>clearHighlight(),140);
    }else{
      const pane=$("sourceReader"), top=pane.scrollTop;
      pane.textContent=readerText || ""; pane.scrollTop=top;
    }
  }
  function showSource(cite,reveal=false) {
    clearTimeout(hoverTimer); clearTimeout(fadeTimer);
    if(!cite) return;
    editingSource=false; syncControls();
    const pane=$("sourceReader"), chars=Array.from(readerText||"");
    if(chars.slice(cite.start,cite.end).join("")!==cite.quote){clearHighlight();setNotice("该引文与当前原文不一致。");return;}
    const top=pane.scrollTop,mark=create("mark",cite.quote);
    pane.replaceChildren(document.createTextNode(chars.slice(0,cite.start).join("")),mark,document.createTextNode(chars.slice(cite.end).join("")));
    pane.scrollTop=top;
    const area=pane.getBoundingClientRect(),hit=mark.getBoundingClientRect();
    if(hit.top<area.top || hit.bottom>area.bottom)
      pane.scrollTop+=hit.top-area.top-Math.max(0,(pane.clientHeight-hit.height)/2);
    if(reveal && (area.top<0 || area.bottom>window.innerHeight)) pane.scrollIntoView({block:"center"});
  }
  function titleButton(t,meeting){
    const b=create("button",undefined,"tasktitle");
    b.type="button";
    b.append(create(t.completed?"s":"strong",t.action));
    if(meeting){
      b.onclick=()=>openMeeting(meeting.id,t.id).catch(e=>setNotice(e.message));
    }else{
      const cite=t.original?.citations?.action;
      b.onpointerenter=e=>{
        if(e.pointerType==="touch") return;
        clearHighlight();
        hoverTimer=setTimeout(()=>{if(b.isConnected && page==="work") showSource(cite);},150);
      };
      b.onpointerleave=()=>clearHighlight(true);
      b.onfocus=()=>showSource(cite);
      b.onblur=()=>clearHighlight(true);
      b.onclick=()=>showSource(cite,true);
    }
    return b;
  }
  async function change(t,patch) {
    if (!t.id) {
      Object.assign(t,patch);
      if(patch.completed===true) t.completed=new Date().toISOString();
      render(); return;
    }
    try {
      const out=await ws("update",{id:t.id,revision:t.revision,change:patch});
      if(out.meeting.id===savedId) adopt(out.meeting);
    } catch(e) {
      if(savedId && savedId===t.meeting) adopt((await ws("open",{id:savedId})).meeting);
      throw e;
    } finally {await refresh();}
  }
  function checkbox(t,meeting) {
    const label=create("div",undefined,"checkline"), check=document.createElement("input");
    check.type="checkbox"; check.checked=!!t.completed;
    check.setAttribute("aria-label","办结："+t.action);
    check.onchange=async()=>{
      check.disabled=true;
      try {await change(t,{completed:check.checked});}
      catch(e){check.checked=!!t.completed;setNotice(e.message);}
      finally {check.disabled=false;}
    };
    label.append(check,titleButton(t,meeting));
    return label;
  }
  async function edit(t,day) {
    editing={t,day,dateEdited:false};
    $("editAction").value=t.action; $("editOwner").value=t.owner;
    $("editDue").value=t.due; $("editDate").value=t.deadline ?? (await ws("date",{day,due:t.due})).deadline;
    $("editMode").value=["auto","off"].includes(t.reminder)?t.reminder:"custom";
    $("editTime").value=$("editMode").value==="custom"?t.reminder:"";
    $("editMode").onchange(); $("editError").textContent=""; $("editTask").showModal();
  }
  $("editMode").onchange=()=>{
    $("timeLabel").hidden=$("editMode").value!=="custom";
    $("editTime").required=!$("timeLabel").hidden;
  };
  $("editDue").onchange=async()=>{
    const input=$("editDue").value, active=editing;
    active.dateEdited=false;
    try {
      const parsed=await ws("date",{due:input,day:active.day});
      if(editing===active && !active.dateEdited && $("editDue").value===input) $("editDate").value=parsed.deadline;
    } catch(e){$("editError").textContent=e.message;}
  };
  $("editDate").oninput=()=>{if(editing) editing.dateEdited=true;};
  $("editCancel").onclick=()=>$("editTask").close();
  $("editForm").onsubmit=async e=>{
    e.preventDefault(); const submit=e.submitter;
    if(submit) submit.disabled=true;
    try {
      const fields={action:$("editAction").value.trim(),owner:$("editOwner").value.trim(),due:$("editDue").value.trim(),
        deadline:$("editDate").value,reminder:$("editMode").value==="custom"?$("editTime").value:$("editMode").value};
      if(!fields.action) throw Error("请填写行动。");
      if(fields.due!==editing.t.due && !editing.dateEdited)
        fields.deadline=(await ws("date",{due:fields.due,day:editing.day})).deadline;
      if(editing.t.id && fields.deadline!==editing.t.deadline && fields.reminder===editing.t.reminder && $("editMode").value==="custom")
        fields.reminder="auto";
      await change(editing.t,fields); $("editTask").close();
    } catch(err){$("editError").textContent=err.message;}
    finally {if(submit) submit.disabled=false;}
  };
  function taskCard(t,meeting=null) {
    const card=create("article",undefined,"task"), suggested=t.state==="suggested";
    if(suggested) card.append(create("small","交叉核对 · 待确认"),titleButton(t,meeting));
    else card.append(checkbox(t,meeting));
    const tags=create("div",undefined,"tags");
    tags.append(create("span","负责人 · "+(t.owner||"待确认")),create("span","期限 · "+([t.due,t.deadline].filter(Boolean).filter((v,i,a)=>a.indexOf(v)===i).join(" / ")||"待确认")));
    if(t.completed) tags.append(create("span","办结 · "+new Date(t.completed).toLocaleDateString()));
    card.append(tags);
    if(meeting) card.append(button(meeting.title+" · "+meeting.day,()=>openMeeting(meeting.id)));
    if(t.original) {
      const orig=t.original;
      if(orig.topic) card.append(create("small",orig.topic));
      if(orig.review?.length) card.append(create("p",orig.review.join("；"),"reviewnote"));
      const evidence=create("details");
      evidence.append(create("summary","查看原文依据"));
      for(const [key,label] of [["action","行动"],["owner","负责人"],["due","期限"]]){
        const c=orig.citations?.[key];
        if(c) evidence.append(button(label+" · 第 "+c.line+" 行　"+c.quote,()=>showSource(c,true)));
      }
      if(["action","owner","due"].some(k=>(t[k]||"")!==(orig[k]||"")))
        evidence.append(create("p","提取时："+orig.action+" ｜ "+(orig.owner||"负责人待确认")+" ｜ "+(orig.due||"期限待确认")));
      card.append(evidence);
    }
    card.append(button("修订待办",()=>edit(t,meeting?.day||$("meetingDay").value)));
    if(suggested) card.append(button("加入待办",()=>change(t,{state:"active"})),button("忽略",()=>change(t,{state:"dismissed"})));
    if(meeting && !t.owner && index.aliases.length) card.append(button("我来认领",()=>change(t,{owner:index.aliases[0]})));
    return card;
  }
  function draw(){
    draw.lastDay=today();
    drawAlarms();
    if(page==="history"){
      const list=$("meetingList");list.replaceChildren();
      const items=index.meetings.filter(m=>!searchIds || searchIds.has(m.id));
      for(const m of items){
        const ts=index.tasks.filter(t=>t.meeting===m.id && t.state==="active");
        const row=create("div",undefined,"historyrow");
        row.append(create("small",m.day),button(m.title,()=>openMeeting(m.id)),create("span","已完成 "+ts.filter(t=>t.completed).length+"/"+ts.length));
        list.append(row);
      }
      if(!items.length) list.append(create("p",searchIds?"没有匹配的会议。":"还没有保存会议。","empty"));
    }
    if(page!=="todos") return;
    const list=$("todoList"), scope=$("scope").value;
    list.replaceChildren();
    if(scope==="mine" && !index.aliases.length) list.append(create("p","先设置你的姓名或会议昵称，即可匹配个人待办和到期提醒。","reviewnote"));
    const tasks=index.tasks.filter(t=>t.state==="active" && (scope==="all" || (scope==="mine"?mine(t):!t.owner)));
    const groups=new Map(["已逾期","今天","未来","无明确日期","已完成"].map(k=>[k,[]]));
    const day=today();
    for(const t of tasks.slice().sort((a,b)=>a.deadline.localeCompare(b.deadline))){
      const k=t.completed?"已完成":!t.deadline?"无明确日期":t.deadline<day?"已逾期":t.deadline===day?"今天":"未来";
      groups.get(k).push(t);
    }
    for(const [k,items] of groups){
      if(!items.length) continue;
      const area=create(k==="已完成"?"details":"section");
      area.append(create(k==="已完成"?"summary":"h3",k+" · "+items.length));
      items.forEach(t=>area.append(taskCard(t,index.meetings.find(m=>m.id===t.meeting))));
      list.append(area);
    }
    if(!tasks.length) list.append(create("p","当前范围没有待办。","empty"));
  }
  for(const k of Object.keys(titleByPage)) $("nav-"+k).onclick=async()=>{
    show(k); try{await refresh();}catch(e){setNotice(e.message);}
  };
  $("scope").onchange=draw;
  $("identity").onclick=()=>{$("names").value=index.aliases.join("，");$("nameDialog").showModal();};
  $("nameCancel").onclick=()=>$("nameDialog").close();
  $("nameForm").onsubmit=async e=>{
    e.preventDefault();
    try {await ws("profile",{aliases:$("names").value.split(/[,，、]/).map(v=>v.trim()).filter(Boolean)});await refresh();$("nameDialog").close();}
    catch(err){setNotice(err.message);}
  };
  $("searchMeet").oninput=async()=>{
    const seq=++searchToken, q=$("searchMeet").value.trim();
    try {
      const ids=q?(await ws("search",{q})).ids:null;
      if(seq===searchToken){searchIds=ids?new Set(ids):null;draw();}
    } catch(e){setNotice(e.message);}
  };
  $("newMeeting").onclick=()=>{
    if(busy||saving) return;
    if(!savedId && result && !isSample && !confirm("新建会议会替换尚未保存的结果，继续吗？")) return;
    savedId=null; $("source").value=""; $("meetingDay").value=today(); $("source").oninput();show("work");$("source").focus();
  };
  $("saveMeeting").onclick=async()=>{
    if(!result||savedId||saving||busy||unfinished||!$("meetingDay").reportValidity()) return;
    saving=true;syncControls();
    try {
      const out=await ws("save",{text:$("source").value,day:$("meetingDay").value,summary:result.summary,tasks:result.tasks,review_warning:result.review_warning||""});
      adopt(out.meeting);await refresh();setNotice(out.existing?"已打开同日同原文的已有记录，保留之前的修订。":"会议已保存，可在历史会议中查看。");
    } catch(e){setNotice(e.message);} finally{saving=false;syncControls();}
  };
  $("meetingDay").required=true;
  show("work");
  let polling=false;
  async function pollWorkspace(){
    if(document.hidden||polling||!root.isConnected) return;
    polling=true;try{await refresh();}catch(e){setNotice(e.message);}finally{polling=false;}
  }
  const tick=setInterval(()=>{if(root.isConnected) pollWorkspace();else clearInterval(tick);},15000);
  document.addEventListener("visibilitychange",pollWorkspace);

