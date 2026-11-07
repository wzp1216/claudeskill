#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normal-work 计划文件管理脚本。

纯标准库实现（系统 /usr/bin/python3 运行），负责每日计划 Markdown 文件的
机械操作：初始化、未完成项滚动、计划项增改查、生成块替换、待提醒清单刷新、
发送审计日志。语义判断（通知归类、建议项、邮件措辞）由 Claude 完成，本脚本
不参与。

命令：
  init           初始化指定日期的计划文件（幂等）
  rollover       把近 N 天内未完成计划项滚入指定日期文件（幂等）
  add            向"今日计划"追加一条计划项
  update         按 ID 修改计划项（状态/字段）
  list           列出指定日期文件中的计划项
  replace-block  整体替换门户/OA 生成块内容
  reminders      刷新"待提醒清单"小节
  log-send       追加一封邮件的发送审计日志（jsonl）

计划项行格式：
  - [ ] `T-20261107-01` 事项标题
    - 优先级：高
    - 截止：2026-11-10
    - 涉及人员：张三（教务处）
    - OA提醒：未生成
    - 来源：门户通知《xxx》
    - 来源ID：portal-xxx
    - 链接：https://...
    - 备注：
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_ROOT = "/media/data/AAAwork/claude/normal-work"

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

SECTION_NAMES = {
    "portal": "一、门户信息",
    "oa": "二、OA 邮件摘要",
    "rollover": "三、昨日未完成（滚动）",
    "today": "四、今日计划",
    "reminders": "五、待提醒清单",
    "notes": "六、备注",
}

ITEM_RE = re.compile(r"^- \[([ xX-])\] `(T-\d{8}-\d{2,})`\s*(.*)$")
FIELD_RE = re.compile(r"^  - ([^：]+)：\s*(.*)$")
SECTION_RE = re.compile(r"^## (.+)$")
BLOCK_START_RE = re.compile(r"^<!-- normal-work:(\w+):start -->$")
BLOCK_END_RE = re.compile(r"^<!-- normal-work:(\w+):end -->$")
UPDATED_RE = re.compile(r"^(> 最近更新：).*$")
DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

# 计划项中允许出现的字段名（规范化显示顺序）
FIELD_ORDER = ["优先级", "截止", "涉及人员", "OA提醒", "来源", "来源ID",
               "来源日", "滚动次数", "原计划日", "链接", "备注"]


class PlanError(Exception):
    """计划文件操作错误。"""


# ---------------------------------------------------------------- 基础工具

def load_config():
    """读取 data/config.json（不存在则用默认值）。"""
    cfg_path = os.path.join(SKILL_DIR, "data", "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    return cfg


def resolve_root(root_arg):
    """--root 优先，其次 config.json 的 runtime_root，最后默认值。"""
    if root_arg:
        return root_arg
    cfg = load_config()
    return cfg.get("paths", {}).get("runtime_root", DEFAULT_ROOT)


def plan_path(root, date):
    return os.path.join(root, "plan", "%s.md" % date)


def today_str():
    return datetime.date.today().isoformat()


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def weekday_cn(date_str):
    d = datetime.date.fromisoformat(date_str)
    return WEEKDAYS[d.weekday()]


def norm_title(t):
    """规范化标题用于去重：去空白。"""
    return re.sub(r"\s+", "", t or "")


class FileLock:
    """plan 目录级排它锁。"""

    def __init__(self, root):
        self.path = os.path.join(root, "plan", ".lock")
        self.fp = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fp = open(self.path, "w")
        fcntl.flock(self.fp, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fp, fcntl.LOCK_UN)
        self.fp.close()


def read_lines(path):
    if not os.path.exists(path):
        raise PlanError("计划文件不存在：%s" % path)
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def write_lines(path, lines):
    """原子写入：同目录临时文件 + os.replace。"""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".plan-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def touch_updated(lines):
    """把文件头的"最近更新"行改为当前时间。"""
    for i, ln in enumerate(lines):
        if UPDATED_RE.match(ln):
            lines[i] = "> 最近更新：%s" % now_str()
            return
    # 没有该行则不动（模板外文件不强制改写）


# ---------------------------------------------------------------- 结构定位

def find_section(lines, section_name):
    """返回小节头行之后的起始行号与下一小节前的结束行号（均为索引）。
    找不到小节时返回 (None, None)。"""
    start = None
    for i, ln in enumerate(lines):
        m = SECTION_RE.match(ln)
        if m and m.group(1).strip() == section_name:
            start = i
            continue
        if start is not None and m:
            return start + 1, i
    if start is not None:
        return start + 1, len(lines)
    return None, None


def find_block(lines, name):
    """返回生成块内容区间的起止索引（不含标记行本身），找不到返回 None。"""
    start = end = None
    for i, ln in enumerate(lines):
        if BLOCK_START_RE.match(ln) and BLOCK_START_RE.match(ln).group(1) == name:
            start = i
        elif start is not None and BLOCK_END_RE.match(ln) \
                and BLOCK_END_RE.match(ln).group(1) == name:
            end = i
            break
    if start is not None and end is not None:
        return start + 1, end
    return None


def parse_item(lines, i):
    """从行 i（计划项起始行）解析整条计划项。
    返回 dict(id, title, status, fields(有序列表), start, end)。"""
    m = ITEM_RE.match(lines[i])
    if not m:
        raise PlanError("第 %d 行不是计划项起始行" % (i + 1))
    item = {
        "id": m.group(2),
        "status": m.group(1),
        "title": m.group(3).strip(),
        "fields": [],
        "start": i,
        "end": i + 1,
    }
    j = i + 1
    while j < len(lines):
        fm = FIELD_RE.match(lines[j])
        if fm:
            item["fields"].append([fm.group(1).strip(), fm.group(2).strip()])
            j += 1
            continue
        break  # 空行/新条目/小节头都不属于该项，停止
    item["end"] = j
    return item


def iter_items(lines):
    """遍历文件中所有计划项（任意小节内）。"""
    for i, ln in enumerate(lines):
        if ITEM_RE.match(ln):
            yield parse_item(lines, i)


def field_value(item, name):
    for k, v in item["fields"]:
        if k == name:
            return v
    return None


def item_to_lines(item, status=None):
    """把计划项 dict 渲染为行列表（status 为 None 时用原状态）。"""
    st = item["status"] if status is None else status
    out = ["- [%s] `%s` %s" % (st, item["id"], item["title"])]
    for k, v in item["fields"]:
        out.append("  - %s：%s" % (k, v))
    return out


def insert_item_block(lines, section_name, item):
    """向小节末尾插入计划项；若小节内有"（无）"占位行则替换之。"""
    start, end = find_section(lines, section_name)
    if start is None:
        raise PlanError("计划文件缺少小节：%s" % section_name)
    block = item_to_lines(item)
    for i in range(start, end):
        if lines[i].strip() == "（无）":
            lines[i:i + 1] = block
            return
    # 无占位行：插入到小节末尾（end 之前）
    lines[end:end] = block


def remove_placeholder(lines, section_name):
    """删除小节中的"（无）"占位行（有实际内容后）。"""
    start, end = find_section(lines, section_name)
    if start is None:
        return
    idx = [i for i in range(start, end) if lines[i].strip() == "（无）"]
    for i in reversed(idx):
        lines.pop(i)


# ---------------------------------------------------------------- 模板

def template_lines(date):
    now = now_str()
    wd = weekday_cn(date)
    return [
        "# %s（%s）工作计划" % (date, wd),
        "",
        "> 生成：%s ｜ 最近更新：%s" % (now, now),
        "> 数据源：融合门户 [未读取] ｜ 通达OA [未读取]",
        "> 标记：[ ] 待办 ｜ [x] 完成 ｜ [-] 取消",
        "",
        "## 一、门户信息",
        "<!-- normal-work:portal:start -->",
        "### 1.1 校内通知",
        "（未读取）",
        "### 1.2 会议公告",
        "（未读取）",
        "### 1.3 本周会议安排",
        "（未读取）",
        "<!-- normal-work:portal:end -->",
        "",
        "## 二、OA 邮件摘要",
        "<!-- normal-work:oa:start -->",
        "（未读取）",
        "<!-- normal-work:oa:end -->",
        "",
        "## 三、昨日未完成（滚动）",
        "（无）",
        "",
        "## 四、今日计划",
        "（无）",
        "",
        "## 五、待提醒清单",
        "（暂无待提醒事项）",
        "",
        "## 六、备注",
        "",
    ]


# ---------------------------------------------------------------- 命令实现

def cmd_init(args):
    root = resolve_root(args.root)
    date = args.date
    path = plan_path(root, date)
    if os.path.exists(path) and not args.overwrite:
        print("已存在，跳过：%s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with FileLock(root):
        write_lines(path, template_lines(date))
    print("已初始化：%s" % path)


def cmd_rollover(args):
    root = resolve_root(args.root)
    date = args.date
    lookback = args.lookback
    plan_dir = os.path.join(root, "plan")
    target = plan_path(root, date)
    if not os.path.exists(target):
        raise PlanError("目标计划文件不存在，先运行 init：%s" % target)

    today_lines = read_lines(target)
    existing_ids = {it["id"] for it in iter_items(today_lines)}
    existing_titles = {norm_title(it["title"]) for it in iter_items(today_lines)}

    # 收集近 N 天内（不含当日）各文件中的计划项，最新状态覆盖旧状态
    dates = sorted(
        f[:-3] for f in os.listdir(plan_dir)
        if DATE_FILE_RE.match(f) and f[:-3] != date
    )
    dates = dates[-lookback:] if lookback > 0 else []
    latest = {}  # id -> dict(item, file_date)
    for d in dates:
        lines = read_lines(plan_path(root, d))
        for it in iter_items(lines):
            latest[it["id"]] = {"item": it, "file_date": d}

    added = []
    for iid, rec in latest.items():
        it = rec["item"]
        if it["status"] not in (" ", "x", "X", "-"):
            continue
        if it["status"] != " ":  # 完成/取消不滚动
            continue
        if iid in existing_ids or norm_title(it["title"]) in existing_titles:
            continue
        # 构建滚动后的字段
        fields = []
        for k, v in it["fields"]:
            if k == "滚动次数":
                fields.append([k, str(int(v or 0) + 1)])
            elif k == "原计划日" or k == "来源日":
                fields.append([k, v])
            elif k in FIELD_ORDER:
                fields.append([k, v])
        if field_value(it, "滚动次数") is None:
            fields.append(["滚动次数", "1"])
        if field_value(it, "来源日") is None:
            fields.append(["来源日", rec["file_date"]])
        elif field_value(it, "原计划日") is None \
                and field_value(it, "来源日") != rec["file_date"]:
            fields.append(["原计划日", rec["file_date"]])
        rolled = {"id": iid, "status": " ", "title": it["title"],
                  "fields": sorted(fields, key=lambda kv: FIELD_ORDER.index(kv[0])
                                   if kv[0] in FIELD_ORDER else 99)}
        with FileLock(root):
            lines = read_lines(target)
            insert_item_block(lines, SECTION_NAMES["rollover"], rolled)
            remove_placeholder(lines, SECTION_NAMES["rollover"])
            touch_updated(lines)
            write_lines(target, lines)
        added.append(iid)
        existing_ids.add(iid)

    print("滚动 %d 项：%s" % (len(added), "、".join(added) if added else "无新滚动项"))


def next_id(lines, date):
    used = [it["id"] for it in iter_items(lines)]
    nums = [int(iid.split("-")[-1]) for iid in used
            if iid.startswith("T-%s-" % date.replace("-", ""))]
    n = max(nums) + 1 if nums else 1
    return "T-%s-%02d" % (date.replace("-", ""), n)


def cmd_add(args):
    root = resolve_root(args.root)
    date = args.date
    target = plan_path(root, date)
    if not os.path.exists(target):
        raise PlanError("目标计划文件不存在，先运行 init：%s" % target)
    fields = []
    if args.priority:
        fields.append(["优先级", args.priority])
    if args.deadline:
        fields.append(["截止", args.deadline])
    if args.people:
        fields.append(["涉及人员", args.people])
    if args.reminder:
        fields.append(["OA提醒", args.reminder])
    if args.source:
        fields.append(["来源", args.source])
    if args.source_id:
        fields.append(["来源ID", args.source_id])
    if args.link:
        fields.append(["链接", args.link])
    if args.note:
        fields.append(["备注", args.note])
    with FileLock(root):
        lines = read_lines(target)
        iid = next_id(lines, date)
        item = {"id": iid, "status": " ", "title": args.title, "fields": fields}
        insert_item_block(lines, SECTION_NAMES["today"], item)
        remove_placeholder(lines, SECTION_NAMES["today"])
        touch_updated(lines)
        write_lines(target, lines)
    print(iid)
    print(json.dumps(item, ensure_ascii=False))


def cmd_update(args):
    root = resolve_root(args.root)
    target = plan_path(root, args.date)
    if not os.path.exists(target):
        raise PlanError("目标计划文件不存在：%s" % target)
    if args.id is None:
        raise PlanError("update 必须指定 --id")
    with FileLock(root):
        lines = read_lines(target)
        items = [it for it in iter_items(lines)]
        hit = [it for it in items if it["id"] == args.id]
        if not hit:
            raise PlanError("未找到计划项 ID：%s" % args.id)
        it = hit[0]
        new_status = None
        if args.status:
            new_status = {"todo": " ", "done": "x", "cancelled": "-"}.get(args.status)
            if new_status is None:
                raise PlanError("--status 只能是 todo/done/cancelled")
        if args.title is not None:
            it["title"] = args.title
        for fname, fval in (("优先级", args.priority), ("截止", args.deadline),
                            ("涉及人员", args.people), ("OA提醒", args.reminder),
                            ("来源", args.source), ("来源ID", args.source_id),
                            ("链接", args.link), ("备注", args.note)):
            if fval is None:
                continue
            for kv in it["fields"]:
                if kv[0] == fname:
                    kv[1] = fval
                    break
            else:
                it["fields"].append([fname, fval])
        it["fields"] = sorted(it["fields"],
                              key=lambda kv: FIELD_ORDER.index(kv[0])
                              if kv[0] in FIELD_ORDER else 99)
        new_lines = lines[:it["start"]] + item_to_lines(it, new_status) \
            + lines[it["end"]:]
        touch_updated(new_lines)
        write_lines(target, new_lines)
    print("已更新 %s：%s" % (args.id, it["title"]))


def cmd_list(args):
    root = resolve_root(args.root)
    target = plan_path(root, args.date)
    if not os.path.exists(target):
        print("[]")
        return
    lines = read_lines(target)
    items = list(iter_items(lines))
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    for it in items:
        fields = " ".join("%s=%s" % (k, v) for k, v in it["fields"])
        print("[%s] %s %s %s" % (it["status"], it["id"], it["title"], fields))


def cmd_replace_block(args):
    root = resolve_root(args.root)
    target = plan_path(root, args.date)
    if not os.path.exists(target):
        raise PlanError("目标计划文件不存在：%s" % target)
    if not os.path.exists(args.content_file):
        raise PlanError("内容文件不存在：%s" % args.content_file)
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().splitlines()
    # 去掉首尾空行
    while content and not content[0].strip():
        content.pop(0)
    while content and not content[-1].strip():
        content.pop()
    with FileLock(root):
        lines = read_lines(target)
        span = find_block(lines, args.name)
        if span is None:
            raise PlanError("计划文件缺少生成块：%s" % args.name)
        start, end = span
        lines[start:end] = content
        touch_updated(lines)
        write_lines(target, lines)
    print("已替换生成块 %s（%d 行）" % (args.name, len(content)))


def cmd_reminders(args):
    root = resolve_root(args.root)
    target = plan_path(root, args.date)
    if not os.path.exists(target):
        raise PlanError("目标计划文件不存在：%s" % target)
    with FileLock(root):
        lines = read_lines(target)
        start, end = find_section(lines, SECTION_NAMES["reminders"])
        if start is None:
            raise PlanError("计划文件缺少小节：%s" % SECTION_NAMES["reminders"])
        rows = []
        for it in iter_items(lines):
            status = field_value(it, "OA提醒") or ""
            if not status or status == "无需":
                continue
            people = field_value(it, "涉及人员") or "—"
            subject = "【工作提醒】%s" % it["title"]
            rows.append("| %s | %s | %s | %s | %s |"
                        % (it["id"], it["title"], people, subject, status))
        if rows:
            content = ["| 计划项 | 事项 | 收件人 | 提醒主题 | 状态 |",
                       "|---|---|---|---|---|"] + rows
        else:
            content = ["（暂无待提醒事项）"]
        content.append("")  # 保留小节后空行
        lines[start:end] = content
        touch_updated(lines)
        write_lines(target, lines)
    print("待提醒清单已刷新（%d 项）" % len(rows))


def cmd_log_send(args):
    root = resolve_root(args.root)
    logs_dir = os.path.join(root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    recipients = []
    for seg in (args.to or "").split(";"):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split("|")
        recipients.append({
            "name": parts[0] if len(parts) > 0 else "",
            "dept": parts[1] if len(parts) > 1 else "",
            "oa_user_id": parts[2] if len(parts) > 2 else "",
        })
    record = {
        "time": now_str(),
        "item_id": args.item_id,
        "to": recipients,
        "cc": (args.cc or "").split(";") if args.cc else [],
        "subject": args.subject,
        "result": args.result,
        "verify": args.verify,
        "draft_path": args.draft_path,
    }
    with open(os.path.join(logs_dir, "sent-emails.jsonl"), "a",
              encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("已记录审计日志")


# ---------------------------------------------------------------- 入口

def add_common(sp):
    """给子命令也加上 --root/--date（子命令前后均可写）。"""
    sp.add_argument("--root", help="运行时根目录（默认取 config.json，无则 "
                                   "/media/data/AAAwork/claude/normal-work）")
    sp.add_argument("--date", default=today_str(),
                    help="计划日期 YYYY-MM-DD（默认今天）")


def main():
    p = argparse.ArgumentParser(description="normal-work 计划文件管理脚本")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="初始化计划文件")
    add_common(sp)
    sp.add_argument("--overwrite", action="store_true", help="覆盖已有文件")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("rollover", help="滚动未完成计划项")
    add_common(sp)
    sp.add_argument("--lookback", type=int, default=7, help="回看天数（默认 7）")
    sp.set_defaults(func=cmd_rollover)

    sp = sub.add_parser("add", help="追加计划项")
    add_common(sp)
    sp.add_argument("--title", required=True)
    sp.add_argument("--priority", choices=["高", "中", "低"])
    sp.add_argument("--deadline")
    sp.add_argument("--people")
    sp.add_argument("--reminder", help="OA提醒状态，如 无需/未生成")
    sp.add_argument("--source")
    sp.add_argument("--source-id")
    sp.add_argument("--link")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("update", help="按 ID 修改计划项")
    add_common(sp)
    sp.add_argument("--id", required=True)
    sp.add_argument("--status", choices=["todo", "done", "cancelled"])
    sp.add_argument("--title")
    sp.add_argument("--priority", choices=["高", "中", "低"])
    sp.add_argument("--deadline")
    sp.add_argument("--people")
    sp.add_argument("--reminder")
    sp.add_argument("--source")
    sp.add_argument("--source-id")
    sp.add_argument("--link")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("list", help="列出计划项")
    add_common(sp)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("replace-block", help="替换生成块")
    add_common(sp)
    sp.add_argument("--name", choices=["portal", "oa"], required=True)
    sp.add_argument("--content-file", required=True)
    sp.set_defaults(func=cmd_replace_block)

    sp = sub.add_parser("reminders", help="刷新待提醒清单")
    add_common(sp)
    sp.set_defaults(func=cmd_reminders)

    sp = sub.add_parser("log-send", help="记录发送审计日志")
    add_common(sp)
    sp.add_argument("--item-id", required=True)
    sp.add_argument("--to", help="收件人，格式 name|dept|oa_user_id，多个用 ; 分隔")
    sp.add_argument("--cc")
    sp.add_argument("--subject")
    sp.add_argument("--result", choices=["sent", "failed", "uncertain"],
                    default="uncertain")
    sp.add_argument("--verify")
    sp.add_argument("--draft-path")
    sp.set_defaults(func=cmd_log_send)

    args = p.parse_args()
    try:
        args.func(args)
    except PlanError as e:
        print("错误：%s" % e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
