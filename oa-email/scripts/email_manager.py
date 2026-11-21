#!/usr/bin/python3
"""oa-email 邮件草稿管理与发送审计（纯标准库）。

命令：
  new       --date 2026-11-08 --type 通知 --recipient "张三（教务处）" \
            --subject "【通知】..." --body-file 正文.txt
                                                  分配编号并写入完整草稿文件
                                                  （编号按已存在草稿文件递增，不会撞号）
  update    --id E-20261108-01 --status 已确认待发送   改草稿状态并刷新更新时间
  list      [--date 2026-11-08] [--json]         列出草稿（按目录序）
  log-send  --id E-20261108-01 --result sent \
            --to "张三" --subject "【通知】..."   追加发送审计（不含正文）

所有命令支持 --root <目录> 指定运行时根目录做隔离调试
（默认 /media/data/AAAwork/claude/oa-email）。
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = "/media/data/AAAwork/claude/oa-email"
DRAFTS_DIRNAME = "drafts"
LOGS_DIRNAME = "logs"
LOG_FILENAME = "sent-emails.jsonl"

FILENAME_RE = re.compile(r"^E-(\d{8})-(\d{2,})(-|$)")
KV_RE = re.compile(r"^- ([^：:]+)[：:]\s*(.*)$")
SLUG_BAD_RE = re.compile(r"[^\w一-鿿-]+")


def slugify(s, limit=30):
    """文件名安全化：去空白与特殊字符，截断。"""
    s = SLUG_BAD_RE.sub("", (s or "").strip())
    return s[:limit] or None


def die(msg, code=1):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def root_of(args):
    return Path(args.root) if args.root else Path(DEFAULT_ROOT)


def date_of(args):
    return args.date or datetime.now().strftime("%Y-%m-%d")


def id_from_day(day):
    return "E-" + day.replace("-", "") + "-"


def read_front(path):
    """读草稿 frontmatter（前 12 行 '- 键：值'），返回 dict 或 None。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[:12]
    except OSError:
        return None
    info = {}
    for ln in lines:
        m = KV_RE.match(ln)
        if m:
            info[m.group(1).strip()] = m.group(2).strip()
    return info if info else None


def find_by_id(root, mail_id):
    """按文件名前缀或 frontmatter 的 邮件ID 定位草稿文件。"""
    base = root / DRAFTS_DIRNAME
    if not base.is_dir():
        return None
    for md in base.rglob("*.md"):
        if md.name.startswith(mail_id + "-"):
            return md
    for md in base.rglob("*.md"):
        info = read_front(md)
        if info and info.get("邮件ID") == mail_id:
            return md
    return None


def cmd_new(args):
    """分配编号并原子写入完整草稿文件（编号按已存在的草稿文件递增，不会撞号）。"""
    day = date_of(args)
    root = root_of(args)
    base = root / DRAFTS_DIRNAME
    max_n = 0
    daynum = day.replace("-", "")
    if base.is_dir():
        for md in base.rglob("*.md"):
            m = FILENAME_RE.match(md.name)
            if m and m.group(1) == daynum:
                max_n = max(max_n, int(m.group(2)))
    mail_id = id_from_day(day) + f"{max_n + 1:02d}"
    (base / day).mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = "（正文待填写）"
    if args.body_file:
        try:
            body = Path(args.body_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            die(f"读取正文文件失败：{e}")
    elif args.body:
        body = args.body
    name_part = slugify((args.recipient or "").split("（")[0])
    slug = slugify(args.slug or args.subject or "")
    fname = f"{mail_id}-{name_part}-{slug}.md" if (name_part or slug) else f"{mail_id}.md"
    path = base / day / fname
    path.write_text(
        f"# 邮件草稿 {mail_id}\n\n"
        f"- 邮件ID：{mail_id}\n"
        f"- 类型：{args.type or ''}\n"
        f"- 收件人：{args.recipient or ''}\n"
        f"- 抄送：{args.cc or ''}\n"
        f"- 附件：{args.attachments or ''}\n"
        f"- 主题：{args.subject or ''}\n"
        f"- 状态：待确认\n"
        f"- 创建：{now}\n"
        f"- 更新：{now}\n\n---\n\n{body}\n",
        encoding="utf-8",
    )
    print(json.dumps({"id": mail_id, "path": str(path)}, ensure_ascii=False))


def cmd_update(args):
    if not args.status:
        die("update 需要 --status <状态>")
    root = root_of(args)
    md = find_by_id(root, args.id)
    if md is None:
        die(f"未找到草稿 {args.id}（drafts 目录下按文件名或 frontmatter 匹配）")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = []
    for ln in md.read_text(encoding="utf-8").splitlines():
        if re.match(r"^- 状态[：:]", ln):
            out.append(f"- 状态：{args.status}")
        elif re.match(r"^- 更新[：:]", ln):
            out.append(f"- 更新：{now}")
        else:
            out.append(ln)
    md.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{args.id} 状态 → {args.status}")


def cmd_list(args):
    root = root_of(args)
    base = root / DRAFTS_DIRNAME
    items = []
    if base.is_dir():
        for md in sorted(base.rglob("*.md")):
            rel = md.relative_to(base)
            if args.date and not rel.parts[0].startswith(args.date):
                continue
            info = read_front(md)
            if not info:
                continue
            items.append({
                "id": info.get("邮件ID", md.name),
                "path": str(md),
                "status": info.get("状态", ""),
                "created": info.get("创建", ""),
            })
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    if not items:
        print("（无草稿）")
        return
    for it in items:
        print(f"{it['id']}  {it['status'] or '?'}  {it['created'] or ''}  {it['path']}")


def cmd_log_send(args):
    if not args.id or not args.result:
        die("log-send 需要 --id 与 --result（sent/待核实/失败）")
    root = root_of(args)
    logs = root / LOGS_DIRNAME
    logs.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "id": args.id,
        "result": args.result,
        "to": args.to or "",
        "subject": args.subject or "",
    }
    with (logs / LOG_FILENAME).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"已记录发送审计：{args.id} {args.result}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--root", help="运行时根目录（调试用，默认见文档）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("new", help="分配编号并写入完整草稿文件")
    sp.add_argument("--date")
    sp.add_argument("--type")
    sp.add_argument("--recipient")
    sp.add_argument("--cc")
    sp.add_argument("--attachments")
    sp.add_argument("--subject")
    sp.add_argument("--body")
    sp.add_argument("--body-file")
    sp.add_argument("--slug")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("update", help="修改草稿状态")
    sp.add_argument("--id", required=True)
    sp.add_argument("--status")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("list", help="列出草稿")
    sp.add_argument("--date")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("log-send", help="写发送审计（不含正文）")
    sp.add_argument("--id", required=True)
    sp.add_argument("--result", required=True)
    sp.add_argument("--to")
    sp.add_argument("--subject")
    sp.set_defaults(func=cmd_log_send)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
