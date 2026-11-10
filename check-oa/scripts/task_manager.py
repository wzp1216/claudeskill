#!/usr/bin/python3
"""check-oa 任务文件管理脚本（纯标准库，系统 /usr/bin/python3）

管理文件：
  <root>/OA任务.md      待办任务清单（按截止紧急度分桶排序）
  <root>/已完成任务.md  已完成归档（每次运行把 OA任务.md 中 [x] 项移入）

命令：
  init           确保运行时目录与两个 md 文件存在（幂等）
  add            追加任务项（--source-id 去重：任务文件与归档文件都已存在则跳过）
  archive        把 OA任务.md 中 [x] 项移入 已完成任务.md（记录完成日期，幂等）
  list           列出任务清单（--json 输出结构化数据）
  touch          刷新"最近更新"时间戳
"""

import argparse
import datetime
import json
import os
import re
import sys
import unicodedata

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "data", "config.json")
DEFAULT_ROOT = "/media/data/AAAwork/claude/check-oa"

TASK_FILE = "OA任务.md"
DONE_FILE = "已完成任务.md"

# 分桶（排序权重）：已超期 → 今天截止 → 3 天内 → 一周内 → 更远 → 截止未明确
BUCKETS = ["已超期", "今天截止", "3 天内", "一周内", "更远", "截止未明确"]

ITEM_RE = re.compile(r"^- \[([ xX-])\] `(OA-\d{8}-\d+)`\s*(.*)$")
FIELD_RE = re.compile(r"^  - (\S+?)：\s*(.*)$")
DEADLINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?$")


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def today():
    return datetime.date.today()


def resolve_root(opt_root):
    if opt_root:
        return opt_root
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            root = cfg.get("paths", {}).get("runtime_root")
            if root:
                return root
        except Exception:
            pass
    return DEFAULT_ROOT


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def write_lines(path, lines):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 计划项解析

def parse_items(lines):
    """解析文件中的计划项块。返回 [{id,status,title,fields,start,end}]。"""
    items = []
    i = 0
    while i < len(lines):
        m = ITEM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        status = "x" if m.group(1).lower() == "x" else " "
        item = {"id": m.group(2), "status": status,
                "title": m.group(3).strip(), "fields": [],
                "start": i, "end": None}
        j = i + 1
        while j < len(lines):
            if ITEM_RE.match(lines[j]) or lines[j].startswith("#"):
                break
            fm = FIELD_RE.match(lines[j])
            if fm:
                item["fields"].append([fm.group(1), fm.group(2).strip()])
            j += 1
        item["end"] = j
        items.append(item)
        i = j
    return items


def get_field(item, name):
    for k, v in item["fields"]:
        if k == name:
            return v
    return None


def item_to_lines(item):
    out = ["- [%s] `%s` %s" % ("x" if item["status"] == "x" else " ",
                                item["id"], item["title"])]
    for k, v in item["fields"]:
        out.append("  - %s：%s" % (k, v))
    return out


def parse_deadline(item):
    v = get_field(item, "截止")
    if not v or v == "未明确":
        return None
    m = DEADLINE_RE.match(v)
    if not m:
        return None
    d = m.group(1)
    t = m.group(2) or "23:59"
    return datetime.datetime.strptime("%s %s" % (d, t), "%Y-%m-%d %H:%M")


def bucket_of(item, now):
    dl = parse_deadline(item)
    if dl is None:
        return "截止未明确"
    if dl < now:
        return "已超期"
    days = (dl.date() - now.date()).days
    if days == 0:
        return "今天截止"
    if days <= 3:
        return "3 天内"
    if days <= 7:
        return "一周内"
    return "更远"


# ---------------------------------------------------------------- 文件结构

def _touch(lines):
    """把文件头'最近更新'行改为当前时间（支持独立行与合并行两种形态）。"""
    for i, ln in enumerate(lines):
        if ln.startswith("> 最近更新："):
            lines[i] = "> 最近更新：%s" % now_str()
            return
        if ln.startswith("> 生成："):
            lines[i] = re.sub(r"最近更新：[^｜]*", "最近更新：%s" % now_str(), ln)
            return


def ensure_headers(lines, kind):
    """kind: 'task' 或 'done'，返回带规范头部的行（保留已有'生成'时间，头部不重复）。"""
    out = list(lines)
    title = "# OA 任务清单" if kind == "task" else "# 已完成任务归档"
    if not out or not out[0].startswith(title):
        out.insert(0, title)
    gen = None
    for ln in out[:12]:
        if ln.startswith("> 生成："):
            gen = ln
            break
    header = ["",
              gen if gen else "> 生成：%s" % now_str(),
              "> 最近更新：%s" % now_str()]
    if kind == "task":
        header.append("> 用法：完成某项后把该项的 [ ] 改成 [x]，下次运行 check-oa 自动归档到\"已完成任务.md\"")
        header.append("> 说明：按截止时间紧急程度排序（已超期 → 今天截止 → 3 天内 → 一周内 → 更远 → 截止未明确）")
    else:
        header.append("> 说明：OA任务.md 中勾选 [x] 的项在每次运行 check-oa 时自动归档到这里（带完成日期）")
    merged = [out[0]]
    merged.extend(header)
    rest = out[1:]
    # 剥掉旧的头部行与空行（> 开头或空行），保留正文内容
    while rest and (rest[0].startswith(">") or not rest[0].strip()):
        rest.pop(0)
    return merged + rest


def split_sections(lines):
    """把文件按 '## ' 分节，返回 [(header_line, body_lines)]。"""
    sections = []
    cur_header = None
    cur_body = []
    for ln in lines:
        if ln.startswith("## "):
            if cur_header is not None:
                sections.append((cur_header, cur_body))
            cur_header = ln
            cur_body = []
        elif cur_header is not None:
            cur_body.append(ln)
    if cur_header is not None:
        sections.append((cur_header, cur_body))
    return sections


def rewrite_task_sections(lines, items):
    """重建任务文件分节：头部与注释保留，分节按 items 重新分桶排序。"""
    head = []
    for ln in lines:
        if ln.startswith("## "):
            break
        head.append(ln)
    now = datetime.datetime.now()
    by_bucket = {}
    for b in BUCKETS:
        by_bucket[b] = []
    for it in items:
        by_bucket[bucket_of(it, now)].append(it)
    out = list(head)
    for b in BUCKETS:
        lst = sorted(by_bucket[b],
                     key=lambda it: (parse_deadline(it)
                                     or datetime.datetime(9999, 12, 31),
                                     it["id"]))
        out.append("## %s" % b)
        if lst:
            for it in lst:
                out.extend(item_to_lines(it))
        else:
            out.append("（无）")
        out.append("")
    while out and not out[-1].strip():
        out.pop()
    return out


# ---------------------------------------------------------------- 命令

def cmd_init(args):
    root = resolve_root(args.root)
    os.makedirs(os.path.join(root, "tmp"), exist_ok=True)
    task_path = os.path.join(root, TASK_FILE)
    done_path = os.path.join(root, DONE_FILE)
    created = []
    if not os.path.exists(task_path):
        write_lines(task_path, ["# OA 任务清单"])
        created.append(task_path)
    if not os.path.exists(done_path):
        write_lines(done_path, ["# 已完成任务归档"])
        created.append(done_path)
    for p in (task_path, done_path):
        lines = read_lines(p)
        lines = ensure_headers(lines, "task" if p.endswith(TASK_FILE) else "done")
        _touch(lines)
        write_lines(p, lines)
    if created:
        for p in created:
            print("已创建：%s" % p)
    else:
        print("已存在，跳过：%s" % task_path)
        print("已存在，跳过：%s" % done_path)


def _load_all(root):
    task_path = os.path.join(root, TASK_FILE)
    done_path = os.path.join(root, DONE_FILE)
    return (read_lines(task_path), read_lines(done_path))


def cmd_add(args):
    if not args.source_id:
        raise SystemExit("add 必须带 --source-id（去重用）")
    root = resolve_root(args.root)
    task_lines, done_lines = _load_all(root)
    existing = parse_items(task_lines) + parse_items(done_lines)
    for it in existing:
        if get_field(it, "来源ID") == args.source_id:
            print("跳过：来源ID 已存在（%s %s）" % (it["id"], it["title"]))
            return
    # 分配 ID：当天已用最大序号 +1（跨两个文件）
    n = 0
    for it in existing:
        m = re.match(r"OA-(\d{8})-(\d+)$", it["id"])
        if m and m.group(1) == today().strftime("%Y%m%d"):
            n = max(n, int(m.group(2)))
    new_id = "OA-%s-%02d" % (today().strftime("%Y%m%d"), n + 1)
    fields = []
    for name, val in (("发布人", args.publisher), ("要求", args.requirement),
                      ("截止", args.deadline), ("来源", args.source),
                      ("来源ID", args.source_id), ("链接", args.link),
                      ("备注", args.note)):
        if val:
            fields.append([name, val])
    item = {"id": new_id, "status": " ", "title": args.title, "fields": fields}
    items = parse_items(task_lines) + [item]
    lines = rewrite_task_sections(ensure_headers(task_lines, "task"), items)
    write_lines(os.path.join(root, TASK_FILE), lines)
    print(new_id)
    print(json.dumps({"id": new_id, "status": " ", "title": args.title,
                      "fields": fields}, ensure_ascii=False))


def cmd_archive(args):
    root = resolve_root(args.root)
    task_path = os.path.join(root, TASK_FILE)
    done_path = os.path.join(root, DONE_FILE)
    task_lines = read_lines(task_path)
    done_lines = read_lines(done_path)
    done_items = parse_items(done_lines)
    done_ids = {it["id"] for it in done_items}
    items = parse_items(task_lines)
    to_archive = [it for it in items if it["status"] == "x"]
    remaining = [it for it in items if it["status"] != "x"]
    date_str = args.date or today().strftime("%Y-%m-%d")
    moved = 0
    if to_archive:
        new_lines = list(done_lines)
        for it in to_archive:
            if it["id"] in done_ids:
                continue
            rec = {"id": it["id"], "status": "x",
                   "title": "%s（完成日期：%s）" % (it["title"], date_str),
                   "fields": it["fields"]}
            new_lines.extend(item_to_lines(rec))
            new_lines.append("")
            moved += 1
        if moved:
            new_lines = ensure_headers(new_lines, "done")
            write_lines(done_path, new_lines)
    if moved:
        write_lines(task_path, rewrite_task_sections(task_lines, remaining))
    print("归档 %d 项" % moved)


def cmd_list(args):
    root = resolve_root(args.root)
    task_lines, done_lines = _load_all(root)
    items = parse_items(task_lines)
    now = datetime.datetime.now()
    if args.json:
        out = []
        for it in items:
            dl = parse_deadline(it)
            out.append({"id": it["id"], "status": it["status"],
                        "title": it["title"],
                        "deadline": dl.strftime("%Y-%m-%d %H:%M") if dl else None,
                        "bucket": bucket_of(it, now),
                        "publisher": get_field(it, "发布人"),
                        "requirement": get_field(it, "要求"),
                        "source": get_field(it, "来源"),
                        "source_id": get_field(it, "来源ID"),
                        "link": get_field(it, "链接"),
                        "note": get_field(it, "备注")})
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not items:
        print("（无任务）")
        return
    for b in BUCKETS:
        lst = [it for it in items if bucket_of(it, now) == b]
        if not lst:
            continue
        print("## %s" % b)
        for it in lst:
            dl = parse_deadline(it)
            dl_s = dl.strftime("%m-%d %H:%M") if dl else "未明确"
            print("  [%s] %s %s｜截止 %s" % (it["status"], it["id"],
                                             it["title"], dl_s))


def cmd_touch(args):
    root = resolve_root(args.root)
    for name in (TASK_FILE, DONE_FILE):
        p = os.path.join(root, name)
        lines = read_lines(p)
        if lines:
            _touch(lines)
            write_lines(p, lines)
    print("已刷新时间戳")


# ---------------------------------------------------------------- 入口

def main():
    p = argparse.ArgumentParser(description="check-oa 任务文件管理脚本")
    p.add_argument("--root", help="运行时根目录（隔离调试用，默认取 config.json）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化 OA任务.md / 已完成任务.md")

    a = sub.add_parser("add", help="追加任务项")
    a.add_argument("--title", required=True)
    a.add_argument("--publisher")
    a.add_argument("--requirement")
    a.add_argument("--deadline", help="YYYY-MM-DD 或 YYYY-MM-DD HH:MM；未明确则省略")
    a.add_argument("--source")
    a.add_argument("--source-id", required=True)
    a.add_argument("--link")
    a.add_argument("--note")

    ar = sub.add_parser("archive", help="把 [x] 项归档到 已完成任务.md")
    ar.add_argument("--date", help="完成日期 YYYY-MM-DD（默认今天）")

    l = sub.add_parser("list", help="列出任务清单")
    l.add_argument("--json", action="store_true")

    sub.add_parser("touch", help="刷新时间戳")

    args = p.parse_args()
    {"init": cmd_init, "add": cmd_add, "archive": cmd_archive,
     "list": cmd_list, "touch": cmd_touch}[args.cmd](args)


if __name__ == "__main__":
    main()
