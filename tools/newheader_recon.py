#!/usr/bin/env python3
"""Generate xnu-13432 header reconstructions from the KDK DWARF SQLite model.

Usage:
  python3 newheader_recon.py --db analysis/xnu-13432.dwarf.db \
      --public /path/to/xnu-12377.121.6 --out /path/to/worktree [--only HEADER ...]
"""
import argparse,json,os,re,sqlite3,sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dwarf_signatures import SigResolver

class Gen:
    def __init__(self,db):
        self.db=db; self.cache={}
    def t(self,off):
        if off not in self.cache:
            self.cache[off]=self.db.execute("select * from type where die_offset=? limit 1",(off,)).fetchone()
        return self.cache[off]
    def members(self,tid):
        return self.db.execute("select * from member where type_id=? order by byte_offset,bit_offset",(tid,)).fetchall()
    def enums(self,tid):
        return self.db.execute("select * from enumerator where type_id=? order by value",(tid,)).fetchall()
    def name(self,off,depth=0):
        if not off or depth>10: return "void *"
        t=self.t(off)
        if not t: return "void *"
        tag,name=t["tag"],t["name"]
        if tag=="DW_TAG_base_type": return name or "int"
        if tag=="DW_TAG_typedef":
            if name and "::" not in name and not name.startswith("__bounds_safety"):
                return name
            return self.name(t["type_offset"],depth+1)
        if tag=="DW_TAG_pointer_type":
            inner=self.name(t["type_offset"],depth+1)
            return inner if inner.endswith("*") else inner+" *"
        if tag=="DW_TAG_const_type": return "const "+self.name(t["type_offset"],depth+1)
        if tag=="DW_TAG_volatile_type": return "volatile "+self.name(t["type_offset"],depth+1)
        if tag=="DW_TAG_restrict_type": return self.name(t["type_offset"],depth+1)+" restrict"
        if tag=="DW_TAG_array_type":
            n=t["array_count"]
            return self.name(t["type_offset"],depth+1)+("[%d]"%n if n else "[]")
        if tag=="DW_TAG_subroutine_type": return "void (*)()"
        if tag in ("DW_TAG_structure_type","DW_TAG_union_type","DW_TAG_enumeration_type"):
            kw={"DW_TAG_structure_type":"struct","DW_TAG_union_type":"union","DW_TAG_enumeration_type":"enum"}[tag]
            return kw+" "+(name or "anon")
        return name or "void *"
    def decl(self,off,name,depth=0):
        if not off or depth>10:
            return "void *"+(" "+name if name else "")
        t=self.t(off)
        if not t:
            return "void *"+(" "+name if name else "")
        tag=t["tag"]
        if tag=="DW_TAG_array_type":
            n=t["array_count"]
            return self.decl(t["type_offset"],name+("[%d]"%n if n else "[]"),depth+1)
        if tag=="DW_TAG_pointer_type":
            return self.decl(t["type_offset"],"*"+name if name else "*",depth+1)
        if tag=="DW_TAG_const_type": return "const "+self.decl(t["type_offset"],name,depth+1)
        if tag=="DW_TAG_volatile_type": return "volatile "+self.decl(t["type_offset"],name,depth+1)
        if tag=="DW_TAG_subroutine_type":
            return "void (*%s)()"%name if name else "void (*)()"
        base=self.name(off,depth+1)
        return base+(" "+name if name else "")
    def define(self,t,depth=0):
        if not t: return None
        tag,name=t["tag"],t["name"]
        if tag=="DW_TAG_enumeration_type":
            es=self.enums(t["id"])
            if not es: return None
            body=",\n".join("\t%s = %s"%(e["name"],e["value"]) for e in es)
            return "enum %s {\n%s\n};"%(name or "",body)
        if tag in ("DW_TAG_structure_type","DW_TAG_union_type"):
            kw="struct" if tag=="DW_TAG_structure_type" else "union"
            ms=self.members(t["id"])
            if not ms: return None
            lines=[]
            for m in ms:
                nm=m["name"]
                if not nm and self.name(m["type_offset"],depth+1)=="void *":
                    lines.append("\t/* unresolved anonymous member at offset %d */"%(m["byte_offset"] or 0))
                    continue
                d=self.decl(m["type_offset"],nm or "",depth+1)
                if m["bit_size"] is not None:
                    lines.append("\t%s : %d;"%(d,m["bit_size"]))
                else:
                    lines.append("\t%s;"%d)
            head=("%s %s {"%(kw,name)) if name else "%s {"%kw
            return "%s\n%s\n};"%(head,"\n".join(lines))
        return None
    def typedef_def(self,t):
        u=self.t(t["type_offset"])
        if u and u["tag"] in ("DW_TAG_structure_type","DW_TAG_union_type","DW_TAG_enumeration_type") and not u["name"]:
            body=self.define(u)
            if body:
                body=body.rstrip(";")
                body=body.replace("struct  {","struct {").replace("union  {","union {").replace("enum  {","enum {")
                return "typedef %s %s;"%(body,t["name"])
        return "typedef %s;"%self.decl(t["type_offset"],t["name"])

def gather(db,header):
    gen=Gen(db)
    rows=db.execute("""select t.* from type t join source_file s on s.cu_id=t.cu_id and s.idx=t.decl_file
                       where s.path like ? and t.name is not null and t.name!='?'""",('%/'+header,)).fetchall()
    best={}
    for t in rows:
        key=(t["tag"],t["name"])
        score=len(gen.members(t["id"]))+len(gen.enums(t["id"]))
        if key not in best or score>best[key][0] or (score==best[key][0] and (t["decl_line"] or 0)<(best[key][1]["decl_line"] or 0)):
            best[key]=(score,t)
    funcs=db.execute("""select f.* from func f join source_file s on s.cu_id=f.cu_id and s.idx=f.decl_file
                        where s.path like ? and f.name is not null and f.name!='?'
                        and (f.declaration=1 or f.low_pc is null)""",('%/'+header,)).fetchall()
    return gen,best,funcs

DEF_TAGS=("DW_TAG_enumeration_type","DW_TAG_structure_type","DW_TAG_union_type")

def render(db,header):
    gen,best,funcs=gather(db,header)
    guard='XNU13432_'+re.sub(r'[^A-Za-z0-9]','_',header).upper()
    out=['/*',' * Reconstruction of %s from the xnu-13432 reference kernel.'%header,' *',
         ' * Declarations are derived from the KDK 27.0.1 DWARF.  Include order and',
         ' * macros used by the original header are not recovered here.',' */',
         '#ifndef '+guard,'#define '+guard,'']
    items=[]
    for (tag,name),(score,t) in best.items():
        items.append(t)
    items.sort(key=lambda t:(t["decl_line"] if t["decl_line"] is not None else 1<<30, t["tag"], t["name"] or ""))
    # order struct/union/enum definitions so by-value dependencies precede users
    defs=[t for t in items if t["tag"] in DEF_TAGS and gen.define(t)]
    names={t["name"]:t for t in defs if t["name"]}
    deps={t["id"]:set() for t in defs}
    for t in defs:
        for m in gen.members(t["id"]):
            mt=gen.t(m["type_offset"])
            if not mt: continue
            # walk through const/array/volatile wrappers but stop at pointers
            seen=0
            while mt and mt["tag"] in ("DW_TAG_const_type","DW_TAG_volatile_type","DW_TAG_array_type") and seen<8:
                mt=gen.t(mt["type_offset"]); seen+=1
            if mt and mt["tag"] in ("DW_TAG_structure_type","DW_TAG_union_type") and mt["name"] in names and mt["name"]!=t["name"]:
                deps[t["id"]].add(names[mt["name"]]["id"])
    ordered=[]; placed=set()
    pending=[t for t in defs]
    while pending:
        progressed=False
        for t in list(pending):
            if deps[t["id"]]<=placed:
                ordered.append(t); placed.add(t["id"]); pending.remove(t); progressed=True
        if not progressed:
            ordered.extend(pending); break
    body=[]; emitted=set()
    for t in items:
        key=(t["tag"],t["name"])
        if t["tag"]=="DW_TAG_typedef":
            if key in emitted: continue
            emitted.add(key); body.append(gen.typedef_def(t))
        elif t["tag"] in DEF_TAGS:
            d=gen.define(t)
            if d:
                if key in emitted: continue
                emitted.add(key); body.append(d)
            elif t["name"]:
                kw={"DW_TAG_structure_type":"struct","DW_TAG_union_type":"union","DW_TAG_enumeration_type":"enum"}[t["tag"]]
                line="%s %s;"%(kw,t["name"])
                if line not in body: body.append(line)
    skipped=[]
    if funcs:
        body.append("")
        seen=set(); r=SigResolver(db)
        for f in sorted(funcs,key=lambda f:(f["decl_line"] or 0,f["name"])):
            name=f["name"]
            if name in seen: continue
            seen.add(name)
            if name.startswith("~") or "operator" in name:
                skipped.append(name); continue
            plist=[]
            for p in db.execute("select name,type_offset from func_param where func_id=? order by ordinal",(f["id"],)):
                plist.append((p["name"],r.name(p["type_offset"])))
            ret=r.name(f["type_offset"])
            if plist and all(n for n,_ in plist) and len(set(n for n,_ in plist))==len(plist):
                params=", ".join("%s %s"%(t,n) for n,t in plist)
            else:
                params=", ".join(t for _,t in plist) or "void"
            body.append("%s %s(%s);"%(ret,name,params))
        if skipped:
            body.append("")
            body.append("/* C++-specific declarations not reconstructed as free functions: %s */"%
                        ", ".join(sorted(set(skipped))))
    out+=body+['','#endif /* %s */'%guard,'']
    return '\n'.join(out)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--db',required=True); ap.add_argument('--out',required=True)
    ap.add_argument('--public',required=True); ap.add_argument('--only',nargs='*')
    ap.add_argument('--missing-json')
    a=ap.parse_args()
    db=sqlite3.connect(a.db); db.row_factory=sqlite3.Row
    missing=json.load(open(a.missing_json)) if a.missing_json else []
    if not missing:
        paths=set(r[0] for r in db.execute("select distinct path from source_file"))
        for p in paths:
            if '/Sources/xnu/' not in p: continue
            rel=p.split('/Sources/xnu/',1)[1]
            if rel.endswith(('.h','.hpp')) and not os.path.exists(os.path.join(a.public,rel)):
                missing.append(rel)
    if a.only: missing=[m for m in missing if m in a.only or any(m.endswith('/'+o) for o in a.only)]
    for h in sorted(missing):
        dest=os.path.join(a.out,h)
        os.makedirs(os.path.dirname(dest),exist_ok=True)
        open(dest,'w').write(render(db,h))
        print('wrote',h)

if __name__=="__main__":
    main()
