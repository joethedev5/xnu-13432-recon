#!/usr/bin/env python3
"""Index struct/union/enum definitions in a public xnu tree with tree-sitter."""
import argparse
import json
import os
import sqlite3
import sys

import tree_sitter_c, tree_sitter_cpp
from tree_sitter import Language, Parser

LANGS = {".c": Language(tree_sitter_c.language()), ".h": Language(tree_sitter_c.language()),
         ".cpp": Language(tree_sitter_cpp.language()), ".hpp": Language(tree_sitter_cpp.language()),
         ".m": Language(tree_sitter_c.language()), ".mm": Language(tree_sitter_cpp.language())}
INCLUDE_DIRS = ("bsd", "osfmk", "iokit", "libkern", "libsa", "pexpert", "security", "san", "libkdd", "config")


def text(src, node):
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def decl_name(src, node):
    d = node
    seen = 0
    while d is not None and seen < 12:
        seen += 1
        if d.type in ("field_identifier", "identifier", "type_identifier"):
            return text(src, d)
        nxt = d.child_by_field_name("declarator")
        if nxt is None:
            named = [c for c in d.named_children
                     if c.type not in ("attribute_specifier", "bitfield_clause", "parameter_list")]
            nxt = named[0] if named else None
        d = nxt
    return None


def fields_of(src, body):
    fields = []
    stack = [body]
    while stack:
        n = stack.pop(0)
        if n.type == "field_declaration":
            type_node = n.child_by_field_name("type")
            ttext = text(src, type_node) if type_node else ""
            declarators = [c for c in n.named_children if c.type in
                           ("declarator", "field_identifier", "pointer_declarator",
                            "array_declarator", "function_declarator", "parenthesized_declarator")]
            if not declarators:
                fields.append({"name": "<anon>", "type": ttext, "bits": None})
            for d in declarators:
                name = decl_name(src, d)
                bits = n.child_by_field_name("bitfield_clause") if hasattr(n, "child_by_field_name") else None
                bits_txt = None
                for c in n.named_children:
                    if c.type == "bitfield_clause":
                        bits_txt = text(src, c).strip()
                fields.append({"name": name or "<anon>", "type": ttext, "bits": bits_txt})
        elif n.type in ("preproc_if", "preproc_ifdef", "preproc_else", "preproc_elif"):
            for c in n.named_children:
                if c.type in ("field_declaration_list", "field_declaration") or c.type.startswith("preproc_"):
                    stack.append(c)
        elif n.type == "field_declaration_list":
            stack[0:0] = list(n.named_children)
    return fields


def enums_of(src, body):
    out = []
    for n in body.named_children:
        if n.type == "enumerator":
            name_node = n.child_by_field_name("name") or (n.named_children[0] if n.named_children else None)
            val = n.child_by_field_name("value")
            out.append({"name": text(src, name_node) if name_node else "?", "value": text(src, val) if val else None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("out", nargs="?", default="analysis/public-types.json")
    args = ap.parse_args()
    out = []
    files = 0
    for inc in INCLUDE_DIRS:
        rootdir = os.path.join(args.tree, inc)
        if not os.path.isdir(rootdir):
            continue
        for root, dirs, fnames in os.walk(rootdir):
            dirs[:] = [d for d in dirs if d not in (".git", "build")]
            for fn in fnames:
                lang = LANGS.get(os.path.splitext(fn)[1])
                if lang is None:
                    continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, args.tree)
                try:
                    src = open(path, "rb").read()
                    tree = Parser(lang).parse(src)
                except Exception as e:
                    print("parse fail", rel, e, file=sys.stderr)
                    continue
                files += 1
                stack = [tree.root_node]
                while stack:
                    n = stack.pop()
                    if n.type in ("struct_specifier", "union_specifier", "enum_specifier"):
                        name_node = n.child_by_field_name("name")
                        body = None
                        for c in n.named_children:
                            if c.type in ("field_declaration_list", "enumerator_list"):
                                body = c
                        if body is None:
                            continue
                        kind = n.type.split("_")[0]
                        name = text(src, name_node) if name_node else "<anon>"
                        entry = {"kind": kind, "name": name, "file": rel,
                                 "line": n.start_point[0] + 1, "end_line": n.end_point[0] + 1}
                        if kind == "enum":
                            entry["enumerators"] = enums_of(src, body)
                        else:
                            entry["fields"] = fields_of(src, body)
                        out.append(entry)
                    stack.extend(n.children)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=0)
    print("indexed %d files, %d type definitions" % (files, len(out)))


if __name__ == "__main__":
    main()
