#!/usr/bin/env python3
"""Generate reconstruction skeletons for source files that exist in the
xnu-13432 DWARF but not in the public tree.

For every function declared in the target file, the tool emits the exact
DWARF signature.  When a function with the same name has a unique definition
in the public tree, its body is moved into the new file (with --move) and
removed from the public file.  All other functions become stubs marked
RECON(13432).
"""
import argparse
import json
import os
import re
import sqlite3

AP = argparse.ArgumentParser()
AP.add_argument("--db", default="analysis/xnu-13432.dwarf.db")
AP.add_argument("--public-funcs", default="analysis/public-funcs.db")
AP.add_argument("--source-set", default="analysis/source-set-12377.121.6.json")
AP.add_argument("--public", required=True, help="public xnu tree to read/move from")
AP.add_argument("--out", required=True, help="output tree root")
AP.add_argument("--move", action="store_true", help="move public bodies into new files")
AP.add_argument("--only", nargs="*", help="limit to these source paths")
AP.add_argument("--report", help="write JSON report here")
ARGS = AP.parse_args()

db = sqlite3.connect(ARGS.db)
db.row_factory = sqlite3.Row
pub = sqlite3.connect(ARGS.public_funcs)
pub.row_factory = sqlite3.Row
missing = json.load(open(ARGS.source_set))["missing_from_public"]
PUB = ARGS.public
tcache={}
def trow(off):
    if off not in tcache:
        tcache[off]=db.execute("select * from type where die_offset=? limit 1",(off,)).fetchone()
    return tcache[off]

def tname(off, depth=0):
    if not off or depth>8: return 'void'
    t=trow(off)
    if not t: return 'void'
    tag=t['tag']; name=t['name']
    if tag=='DW_TAG_typedef':
        return name or tname(t['type_offset'],depth+1)
    if tag=='DW_TAG_pointer_type':
        inner=tname(t['type_offset'],depth+1)
        return inner if inner.endswith('*') else inner+' *'
    if tag=='DW_TAG_const_type':
        return 'const '+tname(t['type_offset'],depth+1)
    if tag=='DW_TAG_volatile_type':
        return 'volatile '+tname(t['type_offset'],depth+1)
    if tag=='DW_TAG_restrict_type':
        return tname(t['type_offset'],depth+1)+' restrict'
    if tag=='DW_TAG_array_type':
        n=t['array_count']
        return tname(t['type_offset'],depth+1)+('['+str(n)+']' if n else '[]')
    if tag=='DW_TAG_subroutine_type':
        return 'void (*)()'
    if name:
        if tag=='DW_TAG_structure_type' and not name.startswith('struct '): return 'struct '+name
        if tag=='DW_TAG_union_type' and not name.startswith('union '): return 'union '+name
        if tag=='DW_TAG_enumeration_type' and not name.startswith('enum '): return 'enum '+name
        return name
    if tag=='DW_TAG_structure_type': return 'struct <anon>'
    if tag=='DW_TAG_union_type': return 'union <anon>'
    if tag=='DW_TAG_enumeration_type': return 'enum <anon>'
    return 'void'

def params(fid):
    out=[]
    for p in db.execute("select name,type_offset from func_param where func_id=? order by ordinal",(fid,)):
        nm=p['name'] or 'arg'
        out.append((tname(p['type_offset']), nm))
    return out

def fmt_sig(f):
    ret=tname(f['type_offset'])
    ps=', '.join(('%s %s'%(t,n)).strip() for t,n in params(f['id']))
    if not ps: ps='void'
    return ret, ps

def funcs_for(file):
    rows=db.execute("select f.*, c.name as cu_name, s.path as src_path from func f join cu c on c.id=f.cu_id left join source_file s on s.cu_id=f.cu_id and s.idx=f.decl_file where c.name like ? and f.name is not null and f.name!='?' and (f.declaration=0 or f.low_pc is not null) order by f.decl_line",('%/'+file,)).fetchall()
    seen={}
    for r in rows:
        # only functions actually declared in this source file (not header inlines)
        if not r['src_path'] or not r['src_path'].endswith('/'+file):
            continue
        n=r['name']
        # prefer a record with code and a decl line
        score=(r['low_pc'] is not None, r['decl_line'] is not None, r['linkage_name'] is not None)
        if n not in seen or score>seen[n][0]:
            seen[n]=(score,r)
    return [v[1] for v in seen.values()]

def public_def(name):
    rows=pub.execute("select * from func where name=? order by (end_line-line) desc",(name,)).fetchall()
    return rows[0] if rows else None

def sig_param_count_ok(text, nparams):
    try:
        head=text.split('{',1)[0]
        lp=head.index('('); depth=0; cnt=0; seen=False
        for ch in head[lp+1:]:
            if ch=='(' or ch=='[': depth+=1
            elif ch==')':
                if depth==0:
                    break
                depth-=1
            elif ch==',' and depth==0:
                cnt+=1
            elif not ch.isspace():
                seen=True
        total=cnt+1 if seen else 0
        return total==nparams
    except ValueError:
        return False

def extract_public(rec):
    path=os.path.join(PUB,rec['file'])
    try: lines=open(path, errors='replace').read().split('\n')
    except OSError: return None
    start=rec['line']-1; end=rec['end_line']-1
    if start<0 or end>=len(lines): return None
    name_re=re.compile(r'\b' + re.escape(rec['name']) + r'\s*\(')
    if not any(name_re.search(lines[j]) for j in range(start, min(start+5, len(lines)))):
        return None
    s=lines[start].strip()
    if not s or s.startswith('/*') or s.startswith('*') or s.startswith('//') or s.startswith('#') or s.endswith('}') or s.endswith(';'):
        return None
    # sanity: extracted text must contain the name and braces
    text='\n'.join(lines[start:end+1])
    if rec['name'] not in text or '{' not in text: return None
    return start, end, text

MOVED=set()
EXCLUDE={'operator new','operator delete','operator new[]','operator delete[]','strlen','strncmp','strcmp','strlcpy','memcpy','memmove','memset','bzero','bcopy','min','max','abs','roundup','powerof2','fls','ffs','clz','imax','imin','qmax','qmin'}

DELETIONS={}

def emit(file, outdir, move=False):
    fs=funcs_for(file)
    parts=[]; moved=[]; stubbed=[]; skipped=[]
    used=set()
    for f in fs:
        if f['name'] in used: continue
        used.add(f['name'])
        ret, ps = fmt_sig(f)
        prec=public_def(f['name'])
        text=None; loc=None
        if prec and prec['file']!=file and prec['file'].endswith(('.c','.cpp')) and f['name'] not in EXCLUDE:
            # only move functions with a single definition in the public tree
            ndef=pub.execute("select count(*) from func where name=?",(f['name'],)).fetchone()[0]
            ex=extract_public(prec) if ndef==1 else None
            if ex and not sig_param_count_ok(ex[2], len(params(f['id']))):
                ex=None
            if ex:
                loc, endline, text=ex
                # adjust static to match KDK linkage
                if f['linkage_name'] is None:
                    if not re.search(r'\bstatic\b', text.split('(')[0]):
                        text=re.sub(r'^(\s*)', r'\1static ', text, count=1)
                else:
                    text=re.sub(r'^(\s*)static\s+', r'\1', text, count=1)
                if move and (prec['file'], loc, endline) not in MOVED:
                    MOVED.add((prec['file'], loc, endline))
                    DELETIONS.setdefault(prec['file'], []).append((loc, endline))
                moved.append((f['name'], prec['file'], prec['line']))
        if text is None:
            body='''{
	/* RECON(13432): body not recovered from the reference kernel yet. */
	panic("reconstructed stub: %s");
}''' % f['name']
            text='%s\n%s(%s)\n%s' % (ret, f['name'], ps, body)
            stubbed.append(f['name'])
        parts.append('/* %s:%s */\n%s' % (file, f['decl_line'], text))
    base=os.path.basename(file)
    guard='RECON_'+re.sub(r'[^A-Za-z0-9]','_',file).upper()
    includes=['#include <sys/param.h>','#include <sys/systm.h>','#include <sys/kernel.h>']
    if file.startswith('osfmk/'):
        includes=['#include <kern/kern_types.h>','#include <kern/assert.h>','#include <kern/debug.h>','#include <kern/zalloc.h>','#include <sys/systm.h>']
    elif file.startswith('iokit/'):
        includes=['#include <IOKit/IOService.h>','#include <IOKit/IOLib.h>','#include <sys/systm.h>']
    elif file.startswith('libkern/'):
        includes=['#include <libkern/libkern.h>','#include <sys/systm.h>']
    elif file.startswith('pexpert/'):
        includes=['#include <pexpert/pexpert.h>','#include <sys/systm.h>']
    hdr='''/*
 * Reconstruction of %s from the xnu-13432 reference kernel.
 *
 * Function signatures and ordering are derived from the KDK 27.0.1
 * DWARF.  Functions marked RECON were moved from the public xnu source
 * when the reference kernel placed them in this file; bodies marked
 * "body not recovered" are still stubs.
 */
%s

#define %s 1

''' % (file, '\n'.join(includes), guard)
    dst=os.path.join(outdir,file)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst,'w').write(hdr+'\n\n'.join(parts)+'\n')
    return {'file':file,'funcs':len(fs),'moved':moved,'stubs':stubbed}

def main():
    outdir = ARGS.out
    only = ARGS.only or missing
    report = []
    for f in only:
        r = emit(f, outdir, move=ARGS.move)
        report.append(r)
        print("%-60s funcs=%3d moved=%3d stubs=%3d" % (
            f, r["funcs"], len(r["moved"]), len(r["stubs"])))
    if ARGS.move:
        for path, ranges in DELETIONS.items():
            full = os.path.join(PUB, path)
            lines = open(full, errors="replace").read().split("\n")
            for a, b in sorted(ranges, reverse=True):
                if b + 1 < len(lines) and lines[b + 1].strip() == "":
                    b += 1
                del lines[a:b + 1]
            open(full, "w").write("\n".join(lines))
        print("deleted ranges from", len(DELETIONS), "public files")
    if ARGS.report:
        json.dump({"report": report, "deletions": DELETIONS},
                  open(ARGS.report, "w"), indent=1)


if __name__ == "__main__":
    main()
