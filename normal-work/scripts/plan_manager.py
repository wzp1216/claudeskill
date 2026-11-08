#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normal-work 计划文件管理脚本。

纯标准库实现（系统 /usr/bin/python3 运行），负责每日计划 Markdown 文件的
机械操作：初始化、未完成项滚动、计划项增改查、生成块替换、待提醒清单刷新、
发送审计日志。语义判断（通知归类、建议项、邮件措辞）由 Claude 完成，本脚本
不参与。

命令（加 --week 即操作周工作文件：init/rollover/add/update/list）：
  init           初始化指定日期的计划文件（幂等）
  rollover       把近 N 天内未完成计划项滚入指定日期文件（幂等）；
                 --week 模式把上一周文件未完成项滚入本周文件
  add            向"今日计划"追加一条计划项（带 --source-id 时自动跳过已存在项）；
                 --week 模式按 --category 追加到周文件分类小节
  update         按 ID 修改计划项（状态/字段）
  list           列出指定日期文件中的计划项
  replace-block  整体替换门户/OA 生成块内容（仅日文件）
  replace-section 整体替换周文件小节内容（--week --section 分类；用于写入
                 "未读取"等状态标注，内容可为 --content 或 --content-file）
  reminders      刷新"待提醒清单"小节（仅日文件）
  set-status     更新文件头"数据源"行中门户/OA 的读取状态（仅日文件）
  log-send       追加一封邮件的发送审计日志（jsonl，仅日文件）

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

# 周工作文件小节与分类子小节（"一、本周工作提示单"下）
WEEK_SECTION_NAMES = {
    "prompt": "一、本周工作提示单",
    "rollover": "二、上周未完成（滚动）",
    "notes": "三、备注",
}
WEEK_CATEGORIES = {
    "oa-mail": "### 1.1 OA 邮件",
    "oa-notice": "### 1.2 OA 公告",
    "oa-approve": "### 1.3 OA 我的工作",
    "portal-notice": "### 1.4 门户通知",
    "portal-meeting": "### 1.5 门户会议",
    "manual": "### 1.6 手动添加",
}

ITEM_RE = re.compile(r"^- \[([ xX-])\] `([TW]-\d{8}-\d{2,})`\s*(.*)$")
FIELD_RE = re.compile(r"^  - ([^：]+)：\s*(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
BLOCK_START_RE = re.compile(r"^<!-- normal-work:(\w+):start -->$")
BLOCK_END_RE = re.compile(r"^<!-- normal-work:(\w+):end -->$")
UPDATED_RE = re.compile(r"^(> 最近更新：).*$")
DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
WEEK_FILE_RE = re.compile(r"^week-(\d{4}-\d{2}-\d{2})\.md$")
SOURCE_STATUS_RE = re.compile(
    r"^(> 数据源：融合门户 \[)([^\]]*)(\] ｜ 通达OA \[)([^\]]*)(\].*)$")

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


def week_path(root, monday):
    """周工作文件路径：plan/week-<周一日期>.md。"""
    return os.path.join(root, "plan", "week-%s.md" % monday)


def monday_of(date_str):
    """返回 date_str 所在周的周一日期字符串。"""
    d = datetime.date.fromisoformat(date_str)
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def week_span(monday_str):
    """返回周一起始的周日期区间文本：2026-11-09 至 2026-11-15。"""
    d = datetime.date.fromisoformat(monday_str)
    end = d + datetime.timedelta(days=6)
    return "%s 至 %s" % (d.isoformat(), end.isoformat())


def today_str():
    return datetime.date.today().isoformat()


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def weekday_cn(date_str):
    d = datetime.date.fromisoformat(date_str)
    return WEEKDAYS[d.weekday()]


def valid_date(s):
    """argparse type：校验 YYYY-MM-DD，失败即报错退出。"""
    try:
        datetime.date.fromisoformat(s)
        return s
    except ValueError:
        raise argparse.ArgumentTypeError("日期格式应为 YYYY-MM-DD：%r" % s)


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

def find_section(lines, section_name, level=2):
    """返回小节头行之后的起始行号与下一小节前的结束行号（均为索引）。
    level 为小节标题级别（## = 2，### = 3）；同级或更高级标题为边界。
    section_name 可带"### "前缀（如周文件分类子小节），比较时剥掉。
    找不到小节时返回 (None, None)。"""
    target = re.sub(r"^#{1,6}\s+", "", section_name).strip()
    start = None
    for i, ln in enumerate(lines):
        m = HEADING_RE.match(ln)
        if m and m.group(2).strip() == target \
                and len(m.group(1)) == level:
            start = i
            continue
        if start is not None and m and len(m.group(1)) <= level:
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


def section_level(section_name):
    """小节标题级别：名称以"###"开头为 3 级（周文件分类子小节），否则 2 级。"""
    return 3 if section_name.startswith("### ") else 2


def insert_item_block(lines, section_name, item):
    """向小节末尾插入计划项；若小节内有"（无）"占位行则替换之。"""
    start, end = find_section(lines, section_name,
                              level=section_level(section_name))
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
    start, end = find_section(lines, section_name,
                              level=section_level(section_name))
    if start is None:
        return
    idx = [i for i in range(start, end) if lines[i].strip() == "（无）"]
    for i in reversed(idx):
        lines.pop(i)


def remove_status_note(lines, section_name):
    """删除小节中的"未读取（...）"状态标注行（有实际内容后，标注即失效）。
    周文件标注统一以"未读取"开头（可带"OA "前缀，格式见 plan-format.md）。"""
    start, end = find_section(lines, section_name,
                              level=section_level(section_name))
    if start is None:
        return
    idx = [i for i in range(start, end)
           if re.match(r"^(OA )?未读取", lines[i].strip())]
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


def week_template_lines(monday):
    """周工作文件模板（date 应为周一日期，非周一按所在周周一处理）。"""
    now = now_str()
    span = week_span(monday)
    return [
        "# %s 工作提示单" % span,
        "",
        "> 生成：%s ｜ 最近更新：%s" % (now, now),
        "> 标记：[ ] 待办 ｜ [x] 完成 ｜ [-] 取消",
        "",
        "## 一、本周工作提示单",
        "### 1.1 OA 邮件",
        "（无）",
        "### 1.2 OA 公告",
        "（无）",
        "### 1.3 OA 我的工作",
        "（无）",
        "### 1.4 门户通知",
        "（无）",
        "### 1.5 门户会议",
        "（无）",
        "### 1.6 手动添加",
        "（无）",
        "",
        "## 二、上周未完成（滚动）",
        "（无）",
        "",
        "## 三、备注",
        "",
    ]


# ---------------------------------------------------------------- 命令实现

def cmd_init(args):
    root = resolve_root(args.root)
    date = args.date
    if args.week:
        monday = monday_of(date)
        path = week_path(root, monday)
        maker = lambda: week_template_lines(monday)
    else:
        path = plan_path(root, date)
        maker = lambda: template_lines(date)
    if os.path.exists(path) and not args.overwrite:
        print("已存在，跳过：%s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with FileLock(root):
        write_lines(path, maker())
    print("已初始化：%s" % path)


def rolled_fields(it, file_date):
    """构建滚动后的计划项字段：滚动次数 +1；来源日保留；
    原计划日 = 最近一次所在日期（与来源日不同才写，每次滚动重算）。"""
    fields = []
    for k, v in it["fields"]:
        if k == "滚动次数":
            fields.append([k, str(int(v or 0) + 1)])
        elif k == "来源日":
            fields.append([k, v])
        elif k == "原计划日":
            continue
        elif k in FIELD_ORDER:
            fields.append([k, v])
    if field_value(it, "滚动次数") is None:
        fields.append(["滚动次数", "1"])
    src_day = field_value(it, "来源日")
    if src_day is None:
        fields.append(["来源日", file_date])
    elif file_date != src_day:
        fields.append(["原计划日", file_date])
    return sorted(fields,
                  key=lambda kv: FIELD_ORDER.index(kv[0])
                  if kv[0] in FIELD_ORDER else 99)


def roll_items_into(root, target, section_name, records):
    """把 records（[(item, file_date), ..]）滚入 target 文件的 section_name
    小节，按 ID/标题去重，幂等。返回滚动条数。"""
    if not records:
        return 0
    lines = read_lines(target)
    existing_ids = {it["id"] for it in iter_items(lines)}
    existing_titles = {norm_title(it["title"]) for it in iter_items(lines)}
    added = 0
    for it, file_date in records:
        if it["status"] != " ":  # 仅待办滚动；完成/取消不滚动
            continue
        if it["id"] in existing_ids \
                or norm_title(it["title"]) in existing_titles:
            continue
        rolled = {"id": it["id"], "status": " ",
                  "title": it["title"],
                  "fields": rolled_fields(it, file_date)}
        insert_item_block(lines, section_name, rolled)
        remove_placeholder(lines, section_name)
        existing_ids.add(it["id"])
        added += 1
    if added:
        touch_updated(lines)
        write_lines(target, lines)
    return added


def cmd_rollover(args):
    root = resolve_root(args.root)
    date = args.date
    plan_dir = os.path.join(root, "plan")
    if args.week:
        monday = monday_of(date)
        target = week_path(root, monday)
        if not os.path.exists(target):
            raise PlanError("目标周文件不存在，先运行 init --week：%s" % target)
        # 找上一个周文件（周一日期 < 本周一，取最近）
        prev = sorted(
            m.group(1) for f in os.listdir(plan_dir)
            for m in [WEEK_FILE_RE.match(f)] if m and m.group(1) < monday
        )
        records = []
        if prev:
            lines = read_lines(week_path(root, prev[-1]))
            records = [(it, prev[-1]) for it in iter_items(lines)]
        added = roll_items_into(root, target,
                                WEEK_SECTION_NAMES["rollover"], records)
        print("周滚动 %d 项（来自 %s）" % (added, prev[-1] if prev else "无上周文件"))
        return

    target = plan_path(root, date)
    if not os.path.exists(target):
        raise PlanError("目标计划文件不存在，先运行 init：%s" % target)

    # 收集近 N 天内（不含当日）各文件中的计划项，最新状态覆盖旧状态
    dates = sorted(
        f[:-3] for f in os.listdir(plan_dir)
        if DATE_FILE_RE.match(f) and f[:-3] != date
    )
    dates = dates[-args.lookback:] if args.lookback > 0 else []
    latest = {}  # id -> (item, file_date)
    for d in dates:
        lines = read_lines(plan_path(root, d))
        for it in iter_items(lines):
            latest[it["id"]] = (it, d)

    records = list(latest.values())
    with FileLock(root):
        added = roll_items_into(root, target,
                                SECTION_NAMES["rollover"], records)
    ids = "、".join(r[0]["id"] for r in records
                    if r[0]["status"] == " ") if added else "无新滚动项"
    print("滚动 %d 项：%s" % (added, ids))


def next_id(lines, date, prefix="T"):
    """分配计划项 ID：<prefix>-YYYYMMDD-NN（prefix 日文件 T / 周文件 W）。"""
    used = [it["id"] for it in iter_items(lines)]
    pfx = "%s-%s-" % (prefix, date.replace("-", ""))
    nums = [int(iid.split("-")[-1]) for iid in used
            if iid.startswith(pfx)]
    n = max(nums) + 1 if nums else 1
    return "%s-%s-%02d" % (prefix, date.replace("-", ""), n)


def cmd_add(args):
    root = resolve_root(args.root)
    date = args.date
    if args.week:
        monday = monday_of(date)
        target = week_path(root, monday)
        if not os.path.exists(target):
            raise PlanError("目标周文件不存在，先运行 init --week：%s" % target)
        section = WEEK_CATEGORIES[args.category]
        id_prefix = "W"
        id_date = monday
        fields = []
        if args.priority:
            fields.append(["优先级", args.priority])
        if args.deadline:
            fields.append(["截止", args.deadline])
        if args.people:
            fields.append(["涉及人员", args.people])
        if args.source:
            fields.append(["来源", args.source])
        if args.source_id:
            fields.append(["来源ID", args.source_id])
        if args.link:
            fields.append(["链接", args.link])
        if args.note:
            fields.append(["备注", args.note])
    else:
        target = plan_path(root, date)
        if not os.path.exists(target):
            raise PlanError("目标计划文件不存在，先运行 init：%s" % target)
        section = SECTION_NAMES["today"]
        id_prefix = "T"
        id_date = date
        fields = [["OA提醒", args.reminder or "无需"]]  # 默认无需
        if args.priority:
            fields.append(["优先级", args.priority])
        if args.deadline:
            fields.append(["截止", args.deadline])
        if args.people:
            fields.append(["涉及人员", args.people])
        if args.source:
            fields.append(["来源", args.source])
        if args.source_id:
            fields.append(["来源ID", args.source_id])
        if args.link:
            fields.append(["链接", args.link])
        if args.note:
            fields.append(["备注", args.note])
    fields = sorted(fields,
                    key=lambda kv: FIELD_ORDER.index(kv[0])
                    if kv[0] in FIELD_ORDER else 99)
    with FileLock(root):
        lines = read_lines(target)
        if args.source_id:
            for it in iter_items(lines):
                if field_value(it, "来源ID") == args.source_id:
                    print("跳过：来源ID 已存在（%s %s）"
                          % (it["id"], it["title"]))
                    return
        iid = next_id(lines, id_date, prefix=id_prefix)
        item = {"id": iid, "status": " ", "title": args.title, "fields": fields}
        insert_item_block(lines, section, item)
        remove_placeholder(lines, section)
        remove_status_note(lines, section)
        touch_updated(lines)
        write_lines(target, lines)
    print(iid)
    print(json.dumps(item, ensure_ascii=False))


def cmd_update(args):
    root = resolve_root(args.root)
    if args.week:
        target = week_path(root, monday_of(args.date))
    else:
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
    if args.week:
        target = week_path(root, monday_of(args.date))
    else:
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


def cmd_replace_section(args):
    """整体替换周文件小节内容（如把"（无）"占位换成"未读取（原因）"标注）。
    --section 用 WEEK_CATEGORIES 的分类名或 WEEK_SECTION_NAMES 的小节名；
    内容来自 --content（单行，含换行用 \\n）或 --content-file（多行）。"""
    root = resolve_root(args.root)
    target = week_path(root, monday_of(args.date))
    if not os.path.exists(target):
        raise PlanError("目标周文件不存在：%s" % target)
    if args.content is not None and args.content_file is not None:
        raise PlanError("--content 与 --content-file 不能同时给")
    if args.content is not None:
        content = args.content.replace("\\n", "\n").splitlines()
    elif args.content_file:
        if not os.path.exists(args.content_file):
            raise PlanError("内容文件不存在：%s" % args.content_file)
        with open(args.content_file, encoding="utf-8") as f:
            content = f.read().splitlines()
    else:
        raise PlanError("replace-section 至少需要 --content 或 --content-file")
    section_name = WEEK_CATEGORIES.get(args.section) \
        or WEEK_SECTION_NAMES.get(args.section)
    if section_name is None:
        raise PlanError("--section 仅支持周文件小节：%s / %s"
                        % ("、".join(sorted(WEEK_CATEGORIES)),
                           "、".join(sorted(WEEK_SECTION_NAMES))))
    level = 3 if section_name.startswith("### ") else 2
    with FileLock(root):
        lines = read_lines(target)
        span = find_section(lines, section_name, level=level)
        if span[0] is None:
            raise PlanError("周文件缺少小节：%s" % section_name)
        start, end = span
        lines[start:end] = content
        touch_updated(lines)
        write_lines(target, lines)
    print("已替换小节 %s（%d 行）" % (section_name, len(content)))


def cmd_set_status(args):
    """更新文件头"数据源"行：--portal/--oa 至少给一个，未给的一项保留原值。"""
    root = resolve_root(args.root)
    target = plan_path(root, args.date)
    if not os.path.exists(target):
        raise PlanError("目标计划文件不存在：%s" % target)
    if args.portal is None and args.oa is None:
        raise PlanError("set-status 至少需要 --portal 或 --oa 之一")
    with FileLock(root):
        lines = read_lines(target)
        idx = None
        for i, ln in enumerate(lines):
            if ln.startswith("> 数据源："):
                idx = i
                break
        if idx is None:
            raise PlanError("计划文件缺少数据源行")
        m = SOURCE_STATUS_RE.match(lines[idx])
        portal_state = args.portal if args.portal is not None \
            else (m.group(2) if m else "未读取")
        oa_state = args.oa if args.oa is not None \
            else (m.group(4) if m else "未读取")
        new_line = "> 数据源：融合门户 [%s] ｜ 通达OA [%s]" \
            % (portal_state, oa_state)
        if lines[idx] != new_line:
            lines[idx] = new_line
            touch_updated(lines)
            write_lines(target, lines)
        print(new_line)


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

def add_common(sp, week=True):
    """给子命令也加上 --root/--date（子命令前后均可写）。
    week=False 用于仅日文件的命令（replace-block/reminders/set-status/
    log-send）。"""
    sp.add_argument("--root", help="运行时根目录（默认取 config.json，无则 "
                                   "/media/data/AAAwork/claude/normal-work）")
    sp.add_argument("--date", type=valid_date, default=today_str(),
                    help="计划日期 YYYY-MM-DD（默认今天）")
    if week:
        sp.add_argument("--week", action="store_true",
                        help="操作周工作文件 plan/week-<周一日期>.md"
                             "（date 自动取所在周周一）")


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
    sp.add_argument("--category", choices=sorted(WEEK_CATEGORIES.keys()),
                    default="manual",
                    help="周文件分类（仅 --week 时使用，默认 manual）")
    sp.add_argument("--priority", choices=["高", "中", "低"])
    sp.add_argument("--deadline")
    sp.add_argument("--people")
    sp.add_argument("--reminder", help="OA提醒状态，如 无需/未生成（仅日文件）")
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
    add_common(sp, week=False)
    sp.add_argument("--name", choices=["portal", "oa"], required=True)
    sp.add_argument("--content-file", required=True)
    sp.set_defaults(func=cmd_replace_block)

    sp = sub.add_parser("replace-section", help="替换周文件小节内容")
    add_common(sp)
    sp.add_argument("--section", required=True,
                    help="周文件小节：oa-mail/oa-notice/oa-approve/"
                         "portal-notice/portal-meeting/manual/"
                         "prompt/rollover/notes")
    sp.add_argument("--content", help="小节新内容（单行，\\n 换行）")
    sp.add_argument("--content-file", help="小节新内容文件（多行）")
    sp.set_defaults(func=cmd_replace_section)

    sp = sub.add_parser("reminders", help="刷新待提醒清单")
    add_common(sp, week=False)
    sp.set_defaults(func=cmd_reminders)

    sp = sub.add_parser("set-status", help="更新数据源状态行")
    add_common(sp, week=False)
    sp.add_argument("--portal", help="融合门户状态，如 正常 / 未读取 / "
                                     "不可用：连接失败")
    sp.add_argument("--oa", help="通达OA状态，如 正常 / 未读取（可能维护中）")
    sp.set_defaults(func=cmd_set_status)

    sp = sub.add_parser("log-send", help="记录发送审计日志")
    add_common(sp, week=False)
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
