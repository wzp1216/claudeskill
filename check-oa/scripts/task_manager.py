#!/usr/bin/python3
"""check-oa 任务文件管理脚本（纯标准库，系统 /usr/bin/python3）

管理文件（路径优先取 config.json 的 paths.task_file / paths.done_file，
缺省退回 <runtime_root>/OA任务.md 与 <runtime_root>/已完成任务.md；
--root 时两者都在 --root 下，供隔离调试）：
  OA任务.md      待办任务清单（按截止紧急度分桶排序）
  已完成任务.md  已完成归档（每次运行把 OA任务.md 中 [x] 项移入）

命令：
  init           确保运行时目录与两个 md 文件存在（幂等）
  add            追加任务项（--source-id 去重：任务文件与归档文件都已存在则跳过）
  archive        把 OA任务.md 中 [x] 项移入 已完成任务.md（记录完成日期，幂等）；并重排任务文件分桶
  list           列出任务清单（--json 输出结构化数据）
  replace-portal 替换 OA任务.md 文末门户信息块（门户数据存档）
  touch          刷新"最近更新"时间戳
  last-check     2 小时频控：距上次检查不足 2 小时则退出码 1（跳过扫描）；
                 --mark 记录本次检查时间；--force 忽略频控；--window-hours 调窗口
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import unicodedata

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_DIR, "data", "config.json")
DEFAULT_ROOT = "/media/data/AAAwork/claude/check-oa"
# 上次检查时间记录（2 小时频控用，本机状态文件）
LAST_CHECK_FILE = os.path.join(SKILL_DIR, "data", "last_check.json")

TASK_FILE = "OA任务.md"
DONE_FILE = "已完成任务.md"

# 分桶（排序权重）：已超期 → 今天截止 → 3 天内 → 一周内 → 更远 → 截止未明确
BUCKETS = ["已超期", "今天截止", "3 天内", "一周内", "更远", "截止未明确"]

# 门户信息块标记：位于任务分桶之后，由 replace-portal 整体替换，
# 存档校内通知/会议公告/本周会议快照，重排/归档时原样保留
PORTAL_START = "<!-- check-oa:portal:start -->"
PORTAL_END = "<!-- check-oa:portal:end -->"

# 任务行：带 `OA-日期-序号` ID 的标准项，或不带 ID 的手动个人任务项
ITEM_RE = re.compile(r"^- \[([ xX-])\]\s*(?:`(OA-\d{8}-\d+)`\s*)?(.*)$")
FIELD_RE = re.compile(r"^  - (\S+?)：\s*(.*)$")
DEADLINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?$")


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def today():
    return datetime.date.today()


def last_check_path(opt_root):
    """频控状态文件位置：--root 时在 root 下，否则本 skill 的 data/ 目录。"""
    if opt_root:
        return os.path.join(opt_root, "last_check.json")
    return LAST_CHECK_FILE


def resolve_paths(opt_root):
    """返回 (task_path, done_path, tmp_dir)。

    --root 给定：三者都在 --root 下（隔离调试）。
    否则读 config.json：paths.task_file / paths.done_file / paths.tmp_dir，
    缺省退回 <runtime_root>/OA任务.md 等（runtime_root 缺省 DEFAULT_ROOT）。
    """
    if opt_root:
        return (os.path.join(opt_root, TASK_FILE),
                os.path.join(opt_root, DONE_FILE),
                os.path.join(opt_root, "tmp"))
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    paths = cfg.get("paths", {})
    root = paths.get("runtime_root") or DEFAULT_ROOT
    task = paths.get("task_file") or os.path.join(root, TASK_FILE)
    done = paths.get("done_file") or os.path.join(root, DONE_FILE)
    tmp = paths.get("tmp_dir") or os.path.join(root, "tmp")
    return task, done, tmp


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
    """解析文件中的计划项块。

    返回 [{id,status,title,fields,section,start,end}]：
    - 带 `OA-...` ID 的标准项 id 为 ID 字符串；手动个人任务（无 ID）id 为 None；
    - section 为该项所在的 `## ` 分节名（头部区域为 None）；
    - 门户信息块（PORTAL_START~PORTAL_END）内的行整体跳过，不当作任务解析。
    """
    items = []
    cur_section = None
    in_portal = False
    i = 0
    while i < len(lines):
        if lines[i] == PORTAL_START:
            in_portal = True
        elif lines[i] == PORTAL_END:
            in_portal = False
            i += 1
            continue
        if in_portal:
            i += 1
            continue
        if lines[i].startswith("## "):
            cur_section = lines[i][3:].strip()
            i += 1
            continue
        m = ITEM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        status = "x" if m.group(1).lower() == "x" else " "
        item = {"id": m.group(2), "status": status,
                "title": m.group(3).strip(), "fields": [],
                "section": cur_section, "start": i, "end": None}
        j = i + 1
        while j < len(lines):
            if (ITEM_RE.match(lines[j]) or lines[j].startswith("#")
                    or lines[j] == PORTAL_START):
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
    idpart = ("`%s` " % item["id"]) if item["id"] else ""
    out = ["- [%s] %s%s" % ("x" if item["status"] == "x" else " ",
                            idpart, item["title"])]
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


def strip_portal_block(lines):
    """去掉门户信息块（含标记行），返回剩余行。"""
    if PORTAL_START not in lines:
        return lines
    i = lines.index(PORTAL_START)
    j = lines.index(PORTAL_END, i) if PORTAL_END in lines[i:] else len(lines) - 1
    return lines[:i] + lines[j + 1:]


def extract_portal_block(lines):
    """返回门户信息块行（含标记行）；无则 None。"""
    if PORTAL_START not in lines:
        return None
    i = lines.index(PORTAL_START)
    j = lines.index(PORTAL_END, i) if PORTAL_END in lines[i:] else len(lines) - 1
    return lines[i:j + 1]


def append_portal_block(lines, portal):
    """把门户信息块追加回文件末尾（重排任务分桶后调用）。"""
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    out.extend([""] + portal)
    return out


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
    """重建任务文件分节。

    - 文件头部（第一个 `## ` 之前）与自定义分节（非 6 个标准桶名）**原样保留、
      不删除不挪位**——手动个人任务一般写在这里；
    - 6 个标准桶按 items 重新分桶排序，桶块放在原文件第一个标准桶的位置；
    - 标准桶重建只取 section 属于标准桶的 items（头部/自定义分节的项不参与）。
    """
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
        if it["section"] in BUCKETS:
            by_bucket[bucket_of(it, now)].append(it)
    out = list(head)
    emitted = False
    for header, body in split_sections(lines):
        name = header[len("## "):].strip()
        if name in BUCKETS:
            if emitted:
                continue
            for b in BUCKETS:
                lst = sorted(by_bucket[b],
                             key=lambda it: (parse_deadline(it)
                                             or datetime.datetime(9999, 12, 31),
                                             it["id"] or ""))
                out.append("## %s" % b)
                if lst:
                    for it in lst:
                        out.extend(item_to_lines(it))
                else:
                    out.append("（无）")
                out.append("")
            emitted = True
        else:
            out.append(header)
            out.extend(body)
            out.append("")
    if not emitted:
        # 文件中没有任何标准桶分节：仍补全 6 个空桶（与历史行为一致）
        for b in BUCKETS:
            out.append("## %s" % b)
            out.append("（无）")
            out.append("")
    while out and not out[-1].strip():
        out.pop()
    return out


# ---------------------------------------------------------------- 命令

def cmd_init(args):
    task_path, done_path, tmp_dir = resolve_paths(args.root)
    os.makedirs(tmp_dir, exist_ok=True)
    for p in (task_path, done_path):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
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


def _load_all(opt_root):
    task_path, done_path, _ = resolve_paths(opt_root)
    return (read_lines(task_path), read_lines(done_path))


def cmd_add(args):
    if not args.source_id:
        raise SystemExit("add 必须带 --source-id（去重用）")
    task_path, done_path, _ = resolve_paths(args.root)
    task_lines, done_lines = _load_all(args.root)
    existing = parse_items(task_lines) + parse_items(done_lines)
    for it in existing:
        if get_field(it, "来源ID") == args.source_id:
            print("跳过：来源ID 已存在（%s %s）" % (it["id"], it["title"]))
            return
    # 分配 ID：当天已用最大序号 +1（跨两个文件）
    n = 0
    for it in existing:
        m = re.match(r"OA-(\d{8})-(\d+)$", it["id"] or "")
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
    # section 置为标准桶名，使 rewrite 重建分桶时把它纳入 6 个标准桶
    item = {"id": new_id, "status": " ", "title": args.title, "fields": fields,
            "section": BUCKETS[0]}
    portal = extract_portal_block(task_lines)
    task_lines = strip_portal_block(task_lines)
    items = parse_items(task_lines) + [item]
    lines = rewrite_task_sections(ensure_headers(task_lines, "task"), items)
    if portal:
        lines = append_portal_block(lines, portal)
    write_lines(task_path, lines)
    print(new_id)
    print(json.dumps({"id": new_id, "status": " ", "title": args.title,
                      "fields": fields}, ensure_ascii=False))


def cmd_archive(args):
    task_path, done_path, _ = resolve_paths(args.root)
    task_lines = read_lines(task_path)
    done_lines = read_lines(done_path)
    done_items = parse_items(done_lines)
    done_ids = {it["id"] for it in done_items if it["id"]}
    done_manual_titles = {it["title"] for it in done_items if not it["id"]}
    items = parse_items(task_lines)
    to_archive = [it for it in items if it["status"] == "x"]
    remaining = [it for it in items if it["status"] != "x"]
    date_str = args.date or today().strftime("%Y-%m-%d")
    moved = 0
    if to_archive:
        new_lines = list(done_lines)
        for it in to_archive:
            if it["id"]:
                if it["id"] in done_ids:
                    continue
            elif it["title"] in done_manual_titles:
                # 手动项无 ID，按标题去重（避免重复归档）
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
    # 从任务文件中物理删除已归档项的行块（倒序删，避免索引偏移）。
    # 标准桶项本来就会被分桶重排丢弃，手动项位于头部/自定义分节必须显式删除
    for s, e in sorted(((it["start"], it["end"]) for it in to_archive),
                       reverse=True):
        del task_lines[s:e]
    # 无论是否归档，都重排任务文件分桶：截止随日期推移而变化
    # （如"今天截止"过一天即成"已超期"），保持紧急度排序始终正确
    portal = extract_portal_block(task_lines)
    task_lines = strip_portal_block(task_lines)
    lines = rewrite_task_sections(task_lines, remaining)
    if portal:
        lines = append_portal_block(lines, portal)
    write_lines(task_path, lines)
    print("归档 %d 项" % moved)


def cmd_list(args):
    task_lines, done_lines = _load_all(args.root)
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
            print("  [%s] %s %s｜截止 %s" % (it["status"], it["id"] or "手动项",
                                             it["title"], dl_s))


def cmd_replace_portal(args):
    """用内容文件整体替换 OA任务.md 文末的门户信息块（含标记行），刷新时间戳。"""
    task_path, _, _ = resolve_paths(args.root)
    lines = read_lines(task_path)
    lines = strip_portal_block(lines)
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().splitlines()
    block = [PORTAL_START] + content + [PORTAL_END]
    lines = append_portal_block(lines, block)
    _touch(lines)
    write_lines(task_path, lines)
    print("已替换门户信息块（%d 行）" % len(block))


def cmd_touch(args):
    for p in resolve_paths(args.root)[:2]:
        lines = read_lines(p)
        if lines:
            _touch(lines)
            write_lines(p, lines)
    print("已刷新时间戳")


def cmd_last_check(args):
    """2 小时频控：检查/记录上次扫描时间。

    - 无参数：距上次检查 < window 小时 → 打印"跳过"并退出码 1；否则退出码 0。
    - --mark：扫描成功后记录当前时间（频控跳过的运行不要 --mark）。
    - --force：忽略频控直接放行（不修改记录）。
    """
    path = last_check_path(args.root)
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    now = time.time()
    if args.mark:
        rec = {"last_check": now_str(), "epoch": now}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        print("已记录检查时间：%s" % rec["last_check"])
        return
    if args.force:
        print("强制检查：忽略 %g 小时频控" % args.window_hours)
        return
    prev = data.get("epoch")
    if prev is None:
        print("无上次检查记录（首次运行），执行扫描")
        return
    mins = (now - prev) / 60.0
    window_min = args.window_hours * 60.0
    if mins < window_min:
        print("距上次检查 %d 分钟（< %g 小时），跳过 OA/门户扫描" % (mins, args.window_hours))
        raise SystemExit(1)
    print("距上次检查 %d 分钟（≥ %g 小时），执行扫描" % (mins, args.window_hours))


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

    rp = sub.add_parser("replace-portal", help="替换 OA任务.md 文末门户信息块")
    rp.add_argument("--content-file", required=True, help="门户信息块内容文件（不含标记行）")

    sub.add_parser("touch", help="刷新时间戳")

    lc = sub.add_parser("last-check", help="2小时频控：检查/记录上次扫描时间")
    lc.add_argument("--mark", action="store_true",
                    help="扫描成功后记录本次检查时间")
    lc.add_argument("--force", action="store_true", help="忽略频控强制放行")
    lc.add_argument("--window-hours", type=float, default=2.0,
                    help="频控窗口（小时，默认 2）")

    args = p.parse_args()
    {"init": cmd_init, "add": cmd_add, "archive": cmd_archive,
     "list": cmd_list, "replace-portal": cmd_replace_portal,
     "touch": cmd_touch, "last-check": cmd_last_check}[args.cmd](args)


if __name__ == "__main__":
    main()
