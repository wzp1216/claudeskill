#!/usr/bin/env python3
"""showtask — 把 OA任务.md 渲染为 task.html 任务看板，并可启动本地服务回写完成状态。

用法：
  showtask.py serve [端口]   生成 task.html 并启动回写服务（缺省 127.0.0.1:8642）
  showtask.py gen            仅生成静态 task.html（双击可开，勾选不回写 md）

依赖：仅 Python 标准库。
"""
import html
import json
import re
import socket
import sys
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "/media/data/AAAwork"
MD_PATH = f"{BASE}/OA任务.md"
HTML_PATH = f"{BASE}/task.html"
DEFAULT_PORT = 8642

# 各紧急度分组的徽标颜色
SECTION_COLORS = {
    "已超期": "#dc2626",
    "今天截止": "#ea580c",
    "3 天内": "#d97706",
    "一周内": "#ca8a04",
    "更远": "#2563eb",
    "截止未明确": "#64748b",
}

# 任务行：`- [ ] `OA-20261110-05` 推进：标题`，或手动个人任务（无 ID）：`- [ ] 推进：标题`
TASK_RE = re.compile(r"^- \[([ xX])\]\s*(?:`([^`]+)`\s*)?(.*)$")
# 手动项（无 ID）在页面里用 "manual:<标题>" 作稳定标识
MANUAL_PREFIX = "manual:"
# 子项行：`  - 发布人：xxx`
META_RE = re.compile(r"^\s+-\s+([^：:]+)[：:]\s*(.*)$")


def parse_md(path=MD_PATH):
    """解析 OA任务.md，返回 (intro 行列表, 分组列表)。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    sections, intro, cur = [], [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            cur = {"title": line[3:].strip(), "tasks": []}
            sections.append(cur)
        elif line.startswith("> "):
            intro.append(line[2:].strip())
        elif cur is not None:
            m = TASK_RE.match(line)
            if m:
                rest = m.group(3).strip()
                task = {"id": m.group(2) or (MANUAL_PREFIX + rest),
                        "done": m.group(1).lower() == "x",
                        "verb": "", "title": "", "meta": {}}
                if "：" in rest:
                    verb, _, title = rest.partition("：")
                    task["verb"], task["title"] = verb.strip(), title.strip()
                else:
                    task["title"] = rest
                cur["tasks"].append(task)
                continue
            m2 = META_RE.match(line)
            if m2 and cur["tasks"]:
                cur["tasks"][-1]["meta"][m2.group(1).strip()] = m2.group(2).strip()
    return intro, sections


def deadline_badge(dl):
    """按截止日期给出徽标样式：已超期红 / 今天橙 / 未到灰。"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", dl)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        today = date.today()
        if d < today:
            return "overdue", f"截止 {dl}"
        if d == today:
            return "today", f"截止 {dl}"
    return "future", f"截止 {dl}"


def render_task_html(sec_idx, t):
    """渲染单条任务为 <li>；初始都放在原分组，已完成项由页面 JS 移入已完成分组。"""
    cls = ' class="task done"' if t["done"] else ' class="task"'
    checked = " checked" if t["done"] else ""
    verb = f'<span class="verb">{html.escape(t["verb"])}</span>' if t["verb"] else ""
    dl_html = ""
    dl = t["meta"].get("截止")
    if dl:
        c, label = deadline_badge(dl)
        dl_html = f'<span class="dl {c}">⏰ {html.escape(label)}</span>'
    meta_lines = []
    for key in ("发布人", "要求", "截止", "来源", "链接", "备注"):
        v = t["meta"].get(key)
        if not v:
            continue
        if key == "链接":
            v2 = (f'<a href="{html.escape(v, quote=True)}" target="_blank" '
                  f'rel="noopener">{html.escape(v)}</a>')
        else:
            v2 = html.escape(v)
        meta_lines.append(f"<div><b>{key}：</b>{v2}</div>")
    details = ""
    if meta_lines:
        details = ('<details><summary>详情</summary><div class="meta">'
                   + "".join(meta_lines) + "</div></details>")
    return f'''<li{cls} data-id="{html.escape(t["id"], quote=True)}" data-section="sec-{sec_idx}">
  <label class="row"><input type="checkbox"{checked}><span class="body">
    <span class="tline"><span class="title">{verb}{html.escape(t["title"])}</span>{dl_html}</span>
  </span></label>
  {details}
</li>'''


def render_html(intro=None, sections=None):
    """由 md 现渲染整页 HTML（intro/sections 缺省时从 md 读取）。"""
    if intro is None or sections is None:
        intro, sections = parse_md()
    parts = []
    for idx, sec in enumerate(sections):
        if not sec["tasks"]:
            continue  # 跳过"（无）"空分组
        color = SECTION_COLORS.get(sec["title"], "#64748b")
        active = sum(1 for t in sec["tasks"] if not t["done"])
        lis = "".join(render_task_html(idx, t) for t in sec["tasks"])
        parts.append(f'''<section class="group">
  <h2><span class="badge" style="background:{color}">{html.escape(sec["title"])}</span><span class="count">{active} 项待办</span></h2>
  <ul id="sec-{idx}" class="task-list">{lis}</ul>
</section>''')
    updated = next((l.split("：", 1)[-1] for l in intro if l.startswith("最近更新")), "")
    footer = "".join(f"<p>{html.escape(l)}</p>" for l in intro)
    page = PAGE.replace("__UPDATED__", html.escape(updated))
    page = page.replace("__SECTIONS__", "\n".join(parts))
    page = page.replace("__FOOTER__", footer)
    return page


def write_html():
    page = render_html()
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"[showtask] 已生成 {HTML_PATH}", flush=True)


def toggle_md(task_id, done):
    """把 md 中该任务的 [ ]/[x] 改为目标状态，返回 (是否成功, 新状态)。

    标准项按任务 ID（`OA-...`）定位；手动个人任务（id 形如 manual:<标题>）
    按整行标题定位。
    """
    try:
        with open(MD_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False, None
    if task_id.startswith(MANUAL_PREFIX):
        title = task_id[len(MANUAL_PREFIX):]
        pattern = re.compile(r"^(\s*-\s*)\[[ xX]\](\s*" + re.escape(title) + r"\s*)$", re.M)
    else:
        pattern = re.compile(r"^(\s*-\s*)\[[ xX]\](\s+`" + re.escape(task_id) + r"\b`)", re.M)
    if not pattern.search(text):
        return False, None
    marker = "[x]" if done else "[ ]"
    new = pattern.sub(lambda mm: mm.group(1) + marker + mm.group(2), text, count=1)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(new)
    return True, done


def probe(port):
    """探测端口上是否已有一个 showtask 服务在运行。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
            body = r.read(4000).decode("utf-8", "ignore")
            return r.status == 200 and "OA 任务清单" in body
    except Exception:
        return False


def find_port(start):
    for p in range(start, start + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit("[showtask] 找不到可用端口（8642~8661 均被占用）")


class Handler(BaseHTTPRequestHandler):
    server_version = "showtask/1.0"

    def do_GET(self):
        if self.path in ("/", "/index.html", "/task.html"):
            try:
                page = render_html()  # 每次现渲染，页面始终与 md 同步
                write_html()          # 同时刷新静态文件
            except Exception as e:
                body = f"渲染失败：{e}".encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            data = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/toggle":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            ok, state = toggle_md(str(req.get("id") or ""), bool(req.get("done")))
            if ok:
                write_html()  # 回写后刷新 task.html，保持两个文件同步
            body = json.dumps({"ok": ok, "done": state}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_error(400)

    def log_message(self, *args):  # 静默访问日志
        pass


def serve(start_port=DEFAULT_PORT):
    if probe(start_port):
        print(f"[showtask] 服务已在运行：http://127.0.0.1:{start_port} ，直接打开即可", flush=True)
        return
    port = find_port(start_port)
    write_html()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[showtask] 服务已启动：http://127.0.0.1:{port} （停止请中断本进程）", flush=True)
    print("[showtask] 页面勾选/取消勾选即自动回写 OA任务.md（[ ]↔[x]）", flush=True)
    httpd.serve_forever()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "gen":
        write_html()
    elif cmd in ("serve", "run"):
        serve(DEFAULT_PORT)
    else:
        print("用法：showtask.py serve [端口]  # 生成 task.html + 启动回写服务（缺省）\n"
              "      showtask.py gen            # 仅生成静态 task.html")


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OA 任务清单</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; background: #f3f4f6; color: #1f2937; line-height: 1.6; }
header { position: sticky; top: 0; z-index: 10; background: #fff; border-bottom: 1px solid #e5e7eb; padding: 14px 24px 12px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
header .wrap { max-width: 900px; margin: 0 auto; }
h1 { font-size: 20px; display: flex; align-items: center; gap: 8px; }
h1 .sub { font-size: 12px; color: #9ca3af; font-weight: 400; margin-left: auto; }
.progress { height: 6px; background: #e5e7eb; border-radius: 3px; margin-top: 10px; overflow: hidden; }
.progress .bar { height: 100%; width: 0; background: linear-gradient(90deg, #2563eb, #60a5fa); transition: width .3s; }
.stats { display: flex; gap: 10px; margin-top: 6px; font-size: 12px; color: #6b7280; }
main { max-width: 900px; margin: 20px auto 30px; padding: 0 16px; }
.group { margin-bottom: 26px; }
.group h2 { font-size: 15px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; color: #fff; font-size: 12px; font-weight: 500; }
.count { color: #9ca3af; font-size: 12px; font-weight: 400; }
.task-list { list-style: none; }
.task { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 16px; margin-bottom: 8px; transition: opacity .2s; }
.task.done { opacity: .55; }
.row { display: flex; gap: 10px; align-items: flex-start; cursor: pointer; }
.row input[type=checkbox] { width: 18px; height: 18px; margin-top: 3px; accent-color: #2563eb; cursor: pointer; flex: none; }
.body { flex: 1; min-width: 0; }
.tline { display: flex; align-items: baseline; gap: 10px; }
.title { font-size: 15px; }
.task.done .title { text-decoration: line-through; color: #9ca3af; }
.verb { display: inline-block; font-size: 12px; color: #2563eb; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 4px; padding: 0 6px; margin-right: 6px; }
.dl { font-size: 12px; color: #6b7280; white-space: nowrap; margin-left: auto; flex: none; }
.dl.overdue { color: #dc2626; font-weight: 600; }
.dl.today { color: #ea580c; font-weight: 600; }
details { margin: 6px 0 0 28px; }
summary { cursor: pointer; font-size: 12px; color: #9ca3af; user-select: none; }
.meta { margin-top: 6px; font-size: 13px; color: #4b5563; display: grid; gap: 3px; }
.meta a { color: #2563eb; word-break: break-all; }
.empty { color: #9ca3af; font-size: 13px; text-align: center; padding: 12px; }
footer { max-width: 900px; margin: 0 auto 60px; padding: 0 16px; font-size: 12px; color: #9ca3af; }
#banner { position: fixed; left: 0; right: 0; bottom: 0; background: #fef3c7; color: #92400e; font-size: 13px; padding: 8px 16px; text-align: center; }
#banner[hidden] { display: none; }
</style>
</head>
<body>
<header><div class="wrap">
  <h1>📋 OA 任务清单 <span class="sub">最近更新：__UPDATED__</span></h1>
  <div class="progress"><div class="bar" id="bar"></div></div>
  <div class="stats"><span id="stat-done">已完成 0 项</span><span>·</span><span id="stat-total">共 0 项</span><span id="stat-note">勾选即回写 OA任务.md</span></div>
</div></header>
<main>
__SECTIONS__
<section class="group">
  <h2><span class="badge" style="background:#16a34a">已完成</span><span class="count" id="done-count">0</span></h2>
  <ul id="done-list" class="task-list"></ul>
  <p class="empty" id="done-empty">暂无已完成任务</p>
</section>
</main>
<footer>
__FOOTER__
</footer>
<div id="banner" hidden>⚠️ 未连接本地回写服务：勾选仅保存在本页浏览器中，不会修改 OA任务.md。请运行 <code>/showtask</code> 启动服务后刷新本页。</div>
<script>
const LS_KEY = 'showtask-state-v1';
let saved = {};
try { saved = JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch (e) { saved = {}; }
const banner = document.getElementById('banner');
function save() { localStorage.setItem(LS_KEY, JSON.stringify(saved)); }
function postToggle(id, done) {
  fetch('/api/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id, done: done }) })
    .then(r => r.json())
    .then(res => { if (res.ok) { delete saved[id]; save(); banner.hidden = true; } else { banner.hidden = false; } })
    .catch(() => { banner.hidden = false; });
}
function moveTask(li, done) {
  const to = done ? document.getElementById('done-list') : document.getElementById(li.dataset.section);
  li.classList.toggle('done', done);
  to.appendChild(li);
  updateStats();
}
function updateStats() {
  const total = document.querySelectorAll('li.task').length;
  const done = document.querySelectorAll('#done-list li.task').length;
  document.getElementById('bar').style.width = (total ? done / total * 100 : 0) + '%';
  document.getElementById('stat-done').textContent = '已完成 ' + done + ' 项';
  document.getElementById('stat-total').textContent = '共 ' + total + ' 项';
  document.getElementById('done-count').textContent = done;
  document.getElementById('done-empty').style.display = done ? 'none' : '';
  document.querySelectorAll('main ul[id^="sec-"]').forEach(ul => {
    const c = ul.closest('.group').querySelector('.count');
    if (c) c.textContent = ul.querySelectorAll('li.task').length + ' 项待办';
  });
}
document.querySelectorAll('li.task input[type=checkbox]').forEach(cb => {
  cb.addEventListener('change', () => {
    const li = cb.closest('li.task'), id = li.dataset.id, done = cb.checked;
    moveTask(li, done);
    if (done) { saved[id] = true; } else { delete saved[id]; }
    save();
    postToggle(id, done);
  });
});
// 初始：已完成项（来自 md 或离线勾选）移入"已完成"分组
document.querySelectorAll('li.task input:checked').forEach(cb => moveTask(cb.closest('li.task'), true));
// 离线勾选状态的回放与同步尝试
Object.keys(saved).forEach(id => {
  const li = document.querySelector('li.task[data-id="' + id + '"]');
  if (li && !li.classList.contains('done')) { moveTask(li, true); postToggle(id, true); }
});
updateStats();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
