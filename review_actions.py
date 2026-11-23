"""Conservative review candidates derived from source locations, never auto-assigned."""
import re

from grounding import locate, words

ISSUE = re.compile(r'\b(?:[\w.-]+)#\d+\b')
HEADING = re.compile(r'(?m)^#{1,6} (.+)$')


def issue_context(source, start):
    for line in reversed(source[:start].splitlines()[:-1]):
        match=ISSUE.search(line)
        if match and re.match(r'^\s*(?:#{1,6}|[-*])\s+',line):
            return match[0]
        if line.startswith("#"):
            break
    return ""


def enrich(item, source):
    anchor=item["citations"]["action"]
    before=source[:anchor["start"]]
    group=re.fullmatch(r'([A-Za-z][\w -]{0,45}\bteam)\s+(?:needs? to|to|will|MCP to)\s+.+',item["evidence"],re.I)
    if group and not item["owner"]:
        item["owner"]=group[1]
        item["citations"]["owner"]=locate(source,group[1],anchor["start"])
    # An indented bullet can inherit a single explicit assignee from its
    # enclosing bullet. Stop at the first unindented line or section break.
    line_start=before.rfind("\n")+1
    prefix=before[line_start:]
    if not item["owner"] and re.fullmatch(r'[ \t]+[-*] ',prefix):
        for line in reversed(source[:line_start].splitlines()):
            if not line.strip() or line.startswith("#"):
                break
            if len(line)-len(line.lstrip()) >= len(prefix)-2:
                continue
            parent=re.fullmatch(r'\s*[-*] (@?[A-Za-z][\w-]*) (?:to|will) [^:]+:\s*',line)
            if parent:
                item["owner"]=parent[1]
                item["citations"]["owner"]=locate(source,line.strip(),anchor["start"])
            break
    # An explicit question addressing a named person immediately precedes a
    # bare acknowledgement. Keep both lines and the nearest issue identifier.
    if re.fullmatch(r'(?:jup|yep|yes|sure|ok)[, ]+will do[.!]?',item["evidence"],re.I):
        ask=re.search(r'(?im)^[^\n]*?\bshould we ([a-z]+),\s*(@?[\w-]+)\?\s*\n[ \t*-]*\Z',before)
        if ask and item["action"].lower()==ask[1].lower():
            issue=issue_context(source,ask.start())
            if issue:
                item["action"]+=" "+issue
                item["owner"]=ask[2]
                quote=source[ask.start():anchor["end"]]
                item["evidence"]=quote
                ref=locate(source,quote,ask.start())
                item["citations"].update(action=ref,owner=ref)
                item["topic"]=issue
    return item


def local_candidates(source, summary, tasks, validate):
    candidates=[]
    summary_words=words(" ".join([summary["overview"],*summary["decisions"],*summary["open_questions"]]))
    # Recover explicit, summary-supported next steps and anchored deadline
    # clauses. Ambiguous items remain candidates for human confirmation.
    for m in re.finditer(r'(?m)^.*\S.*$',source):
        line=m[0].strip().lstrip("-* ").strip()
        next_step=re.match(r'(?:one outcome|next step|行动项|下一步)[：:]\s*(.+)',line,re.I)
        deadline=re.search(r'\bto be (?:decided|confirmed|submitted|completed)\b.*?\bby\s+([A-Za-z]+\.? \d{1,2})\b',line,re.I)
        if not (next_step or deadline) or len(summary_words & words(line))<2:
            continue
        if re.search(r'\b(?:maybe|perhaps|if|cancelled|canceled|done)\b|已取消|如果',line,re.I):
            continue
        candidates.append(dict(action=next_step[1] if next_step else line,owner=None,
                               due=deadline[1] if deadline else None,evidence=line,
                               evidence_line=source.count("\n",0,m.start())+1))
    for t in tasks:
        ev=t["evidence"]
        if not (re.fullmatch(r'@?[\w-]+ (?:to|will) .+',ev) and source.count(ev)>1):
            continue
        first=t.get("citations",{}).get("action")
        if not first:
            continue
        for m in re.finditer(re.escape(ev),source):
            if m.start()==first["start"]:
                continue
            headings=list(HEADING.finditer(source,0,m.start()))
            topic=headings[-1][1] if headings else ""
            if topic and topic!=t.get("topic") and ISSUE.search(topic):
                candidates.append(dict(t,evidence_line=source.count("\n",0,m.start())+1))
    return validate({"tasks":candidates},"tasks",source)["tasks"]


def unseen(existing,candidates):
    accepted=list(existing)
    new=[]
    for item in candidates:
        ref=item.get("citations",{}).get("action",{})
        duplicate=False
        for old in accepted:
            other=old.get("citations",{}).get("action",{})
            if ref and other:
                overlaps=ref["start"]<other["end"] and other["start"]<ref["end"]
            else:
                overlaps=item["evidence"]==old["evidence"]
            if overlaps:
                a,b=words(item["action"]),words(old["action"])
                if item["action"].casefold()==old["action"].casefold() or (a and b and len(a & b)/min(len(a),len(b))>=0.65 and item.get("owner")==old.get("owner")):
                    duplicate=True
                    break
        if not duplicate:
            new.append(item)
            accepted.append(item)
    return new

