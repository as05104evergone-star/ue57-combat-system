# -*- coding: utf-8 -*-
r"""KBaseUE / 知识库加载
=====================

把 ``Content/Knowledge/*.json`` 读成可检索的规则表。

这份知识库的形状是为"**一次调用就能回答一个问题**"设计的：调用方（人或模型）
不需要先读文档再自己推理，而是用关键词直接命中一条已经带结论、带源码行号、
带"我上次错在哪"的规则。

为什么要有它：引擎源码里同一个判定（``FunctionCanBePlacedAsEvent``）会在 5 个
不同位置影响 UI 表现，只读其中一处就会得出自相矛盾的结论。把这些拼图预先拼好，
比每次现场重新拼更不容易错。
"""

import json
import os

# __file__ = <plugin>/Content/Python/kbase.py  →  三次 dirname 得到插件根
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWLEDGE_DIR = os.path.join(PLUGIN_DIR, "Content", "Knowledge")

_CACHE = {}


def knowledge_dir():
    return KNOWLEDGE_DIR


def load_documents():
    """读入 Knowledge 目录下所有 JSON。结果按文件 mtime 失效。"""
    docs = []
    if not os.path.isdir(KNOWLEDGE_DIR):
        return docs
    for name in sorted(os.listdir(KNOWLEDGE_DIR)):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(KNOWLEDGE_DIR, name)
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        cached = _CACHE.get(path)
        if cached and cached[0] == stamp:
            docs.append(cached[1])
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        doc.setdefault("_file", name)
        _CACHE[path] = (stamp, doc)
        docs.append(doc)
    return docs


def all_rules():
    """展平成规则列表，附带所属文档标题。"""
    out = []
    for doc in load_documents():
        for rule in doc.get("rules") or []:
            item = dict(rule)
            item["_doc"] = doc.get("title")
            item["_engine"] = (doc.get("engine") or {}).get("version")
            out.append(item)
    return out


def get_rule(rule_id):
    for rule in all_rules():
        if rule.get("id") == rule_id:
            return rule
    return None


def topics():
    """目录：只给 id / 标题 / 关键词，用来省 token。"""
    out = []
    for rule in all_rules():
        out.append({
            "id": rule.get("id"),
            "title": rule.get("title"),
            "keywords": rule.get("keywords") or [],
            "sources": len(rule.get("sources") or []),
        })
    return out


def _score(rule, terms):
    """关键词命中打分。标题命中权重最高，源码路径不参与（否则路径里的
    常见词会盖过真正的话题词）。"""
    title = (rule.get("title") or "").lower()
    keywords = " ".join(rule.get("keywords") or []).lower()
    body = json.dumps(
        {k: v for k, v in rule.items() if not k.startswith("_") and k != "sources"},
        ensure_ascii=False).lower()

    score = 0
    for term in terms:
        if term in title:
            score += 8
        if term in keywords:
            score += 4
        if term in body:
            score += 1
    return score


def search(query, limit=3, full=False):
    """按关键词检索规则。

    ``full=False`` 时只返回结论与修复步骤（省 token）；``full=True`` 连源码行号
    与"上次错在哪"一起返回。
    """
    terms = [t for t in str(query or "").lower().replace("，", " ").replace(",", " ")
             .replace("。", " ").split() if t]
    if not terms:
        return []

    scored = []
    for rule in all_rules():
        s = _score(rule, terms)
        if s > 0:
            scored.append((s, rule))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("id") or ""))

    out = []
    for s, rule in scored[:max(1, int(limit))]:
        item = {
            "id": rule.get("id"),
            "title": rule.get("title"),
            "score": s,
            "verdict": rule.get("verdict"),
            "how_to_fix": rule.get("how_to_fix"),
            "details": rule.get("details"),
        }
        if full:
            item["ui_symptom"] = rule.get("ui_symptom")
            item["sources"] = rule.get("sources")
            item["false_leads"] = rule.get("false_leads")
            item["automatic_repair"] = rule.get("automatic_repair")
        else:
            item["sources"] = (rule.get("sources") or [])[:3]
        out.append(item)
    return out


def meta():
    docs = load_documents()
    return {
        "knowledge_dir": KNOWLEDGE_DIR,
        "documents": [{"file": d.get("_file"), "title": d.get("title"),
                       "rules": len(d.get("rules") or [])} for d in docs],
        "engine": (docs[0].get("engine") if docs else None),
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(meta(), ensure_ascii=False, indent=1))
    if len(sys.argv) > 1:
        print(json.dumps(search(" ".join(sys.argv[1:]), full=True),
                         ensure_ascii=False, indent=1))
