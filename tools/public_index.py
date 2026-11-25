#!/usr/bin/env python3
"""Index function definitions in a public xnu tree with tree-sitter."""
import argparse
import os
import sqlite3
import sys

import tree_sitter
import tree_sitter_c
import tree_sitter_cpp
from tree_sitter import Language, Parser

LANGS = {
    ".c": Language(tree_sitter_c.language()),
    ".h": Language(tree_sitter_c.language()),
    ".m": Language(tree_sitter_c.language()),
    ".cpp": Language(tree_sitter_cpp.language()),
    ".hpp": Language(tree_sitter_cpp.language()),
    ".cc": Language(tree_sitter_cpp.language()),
    ".mm": Language(tree_sitter_cpp.language()),
}
INCLUDE_DIRS = ("bsd", "osfmk", "iokit", "libkern", "libsa", "pexpert",
                "security", "san", "libkdd", "config")


def text(src, node):
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def func_name(src, node):
    d = node.child_by_field_name("declarator")
    seen = 0
    while d is not None and seen < 16:
        seen += 1
        if d.type in ("identifier", "field_identifier", "qualified_identifier",
                      "operator_name", "destructor_name", "type_identifier"):
            return text(src, d)
        nxt = d.child_by_field_name("declarator")
        if nxt is None:
            named = [c for c in d.named_children if c.type not in ("parameter_list", "attribute_specifier")]
            nxt = named[0] if named else None
        d = nxt
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("out", default="analysis/public-funcs.db", nargs="?")
    args = ap.parse_args()
    if os.path.exists(args.out):
        os.remove(args.out)
    db = sqlite3.connect(args.out)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("CREATE TABLE func (name TEXT, file TEXT, line INTEGER, end_line INTEGER,"
               " ret TEXT, storage TEXT)")
    db.execute("CREATE INDEX idx_name ON func(name)")
    db.execute("CREATE INDEX idx_file ON func(file)")
    nfiles = nfunc = 0
    for inc in INCLUDE_DIRS:
        rootdir = os.path.join(args.tree, inc)
        if not os.path.isdir(rootdir):
            continue
        for root, dirs, files in os.walk(rootdir):
            dirs[:] = [d for d in dirs if d not in (".git", "build")]
            for fn in files:
                ext = os.path.splitext(fn)[1]
                lang = LANGS.get(ext)
                if lang is None:
                    continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, args.tree)
                try:
                    src = open(path, "rb").read()
                    parser = Parser(lang)
                    tree = parser.parse(src)
                except Exception as e:
                    print("parse fail", rel, e, file=sys.stderr)
                    continue
                nfiles += 1
                stack = [tree.root_node]
                while stack:
                    node = stack.pop()
                    if node.type == "function_definition":
                        name = func_name(src, node)
                        if name:
                            ret = node.child_by_field_name("type")
                            storage = " ".join(text(src, c) for c in node.children
                                               if c.type in ("storage_class_specifier", "type_qualifier"))
                            db.execute("INSERT INTO func VALUES (?,?,?,?,?,?)",
                                       (name, rel, node.start_point[0] + 1,
                                        node.end_point[0] + 1,
                                        text(src, ret) if ret else None, storage))
                            nfunc += 1
                    stack.extend(node.children)
    db.commit()
    print("indexed %d files, %d function definitions" % (nfiles, nfunc))
    print(db.execute("select count(*) from func").fetchone()[0])
    for row in db.execute("select file,count(*) c from func group by file order by c desc limit 10"):
        print(row)


if __name__ == "__main__":
    main()
