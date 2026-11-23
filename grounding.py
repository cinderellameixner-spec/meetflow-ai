"""Conservative field checks. Uncertain assignments remain visible for review."""
import re

# Split only where a new assignee or speaker begins. Keep vocatives and dates.
CLAUSES = re.compile(r"[;；。\n]+|(?:[,，]\s*|\s+and\s+)(?=(?:[A-Za-z][\w-]*\s+(?:to|will)\b|[\u3400-\u9fff]{1,6}(?:负责|負責|来做|來做)))", re.I)
DATE = re.compile(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d+|\d+月\s*\d+[日号號]|(?:周|週|星期)[一二三四五六日天]", re.I)
DEADLINE = re.compile(r"(?:\bby\s+(?:the\s+)?|截止(?:到|于|於)?\s*|最[迟遲]\s*)$",re.I)
STOP = {'the','to','of','for','and','in','on','a','an','will','own','quickly','with','by','from','this','that','task'}


def words(s):
    english={w[:4] for w in re.findall('[a-z]+',s.lower()) if w not in STOP and len(w)>2}
    han=re.findall(r'[\u3400-\u9fff]+',s)
    return english | {w[i:i+2] for w in han for i in range(len(w)-1)}


def locate(source, quote, near=None):
    pos=source.find(quote)
    if pos<0:
        return None
    if near is not None:
        pos=min((m.start() for m in re.finditer(re.escape(quote),source)),key=lambda p:abs(p-near))
    return {'quote':quote,'start':pos,'end':pos+len(quote),'line':source.count('\n',0,pos)+1}


def supported(task, source, raw, near=None):
    ev=task['evidence']
    anchor=locate(source,ev,near)
    refs={'action':anchor}
    warnings=[]
    chunks=[v.strip() for v in CLAUSES.split(ev) if v.strip()]
    tokens=words(task['action'])
    ranking=[len(words(c)&tokens) for c in chunks]
    # A single explicit assignment can recover an omitted name. The field
    # still passes the same clause/evidence checks as a model-supplied name.
    assignment=re.fullmatch(r'\s*[-*]?\s*(@?[A-Za-z][\w-]*)\s+(?:to|will)\s+([^\n]+)',ev)
    if task['owner'] is None and assignment and len(chunks)==1 and tokens & words(assignment[2]):
        if assignment[1].lower() not in {'we','i','they','he','she','team','someone','how','need','going'}:
            task['owner']=assignment[1]
    for field,label in [('owner','负责人'),('due','期限')]:
        value=task[field]
        if value is None:
            continue
        quote=raw.get(field+'_evidence') or ev
        ref=locate(source,quote,anchor['start']) if isinstance(quote,str) and quote.strip() else None
        contained=bool(ref and (quote in ev or ev in quote))
        term=re.escape(value)
        if value.isascii() and value[0].isalnum() and value[-1].isalnum():
            term=r'(?<!\w)'+term+r'(?!\w)'
        good=bool(contained and len(quote)<=len(ev)+160 and re.search(term,quote,re.I))
        if good and field=='owner':
            direct=[j for j,c in enumerate(chunks) if re.search(term,c,re.I)]
            if len(chunks)==1 and re.search(term+r'\s+(?:to|will)\s+',ev,re.I):
                verbs=[w[:4] for w in re.findall('[a-z]+',task['action'].lower()) if len(w)>2 and w not in STOP]
                if verbs and verbs[0] not in words(ev) and not re.match(term+r'\s+(?:to|will)\b',task['action'],re.I):
                    good=False
            if direct and len(chunks)>1:
                best=max(ranking)
                good=best>0 and any(ranking[j]==best for j in direct)
                # Prefer the action verb when several named people share a sentence.
                leads=[w[:4] for w in re.findall('[a-z]+',task['action'].lower()) if len(w)>2 and w not in STOP]
                verb_hits=[j for j,c in enumerate(chunks) if leads and leads[0] in words(c)]
                if verb_hits:
                    good=len(verb_hits)==1 and verb_hits[0] in direct
                if not good and any(re.fullmatch(r'[#*\s]*'+term+r'[：:]?',chunks[j],re.I) and
                                    j+1<len(chunks) and re.match(r'^(我|I\b)',chunks[j+1],re.I) for j in direct):
                    good=True
            elif not direct:
                # A larger quotation may supply the preceding first-person speaker.
                speaker=r'(?:^|\n)[#*\s]*'+term+r'\s*[：:]\s*(?:我|I\b)'
                good=bool(re.search(speaker,quote,re.I) and len(quote)-len(ev)<120)
            if good and re.search(term+r'\s*[：:]\s*(?:请|請)?(?!我)[\u3400-\u9fff]{2,5}(?:负责|負責)',ev,re.I):
                good=False
        if good and field=='due' and not re.search(term,ev,re.I):
            good=False
        if good and field=='due' and len(DATE.findall(ev))>1:
            at=ev.lower().find(value.lower())
            good=at>=0 and bool(DEADLINE.search(ev[:at]) or re.match(r'by\b|最[迟遲]|截止',value,re.I) or
                                re.search(r'前|以前|之前|截止',ev[at:at+len(value)+3]))
        if good:
            refs[field]=ref
        else:
            task[field]=None
            warnings.append(label+'与行动的原文依据待复核')
    if warnings:
        task['review']=warnings
    task['citations']=refs
    return task

