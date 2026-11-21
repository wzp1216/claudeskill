---
name: showtask
description: OA 任务看板。当用户说"查看OA任务/显示OA任务/showtask/任务看板/打开任务清单/看下任务"时使用。运行时先自动调用 check-oa 技能刷新任务（check-oa 自带 2 小时频控，刚查过则几秒返回），再把 /media/data/AAAwork/OA任务.md 渲染为 /media/data/AAAwork/task.html 任务看板（按紧急度分组、多选框勾选完成、划线置灰移入"已完成"分组），并启动本地小服务（127.0.0.1:8642）：页面勾选/取消即自动回写 OA任务.md（[ ]↔[x]），与 check-oa 的归档流程无缝衔接。纯 Python 标准库实现，无新依赖。
---

# showtask — OA 任务看板

万志平（教务处）的 OA 任务可视化看板：`OA任务.md` → `task.html`，网页勾选完成，
勾选结果即时回写 md，下次运行 check-oa 时自动归档到 `已完成任务.md`。

## 一、能力边界

| 能做 | 不做 |
|---|---|
| 解析 OA任务.md（紧急度分组 + 任务 ID + 动词/标题 + 发布人/要求/截止/来源/链接/备注） | 不修改任务内容本身，只改 `[ ]`↔`[x]` 完成标志 |
| 生成 `/media/data/AAAwork/task.html` 看板：多选框、进度条、按紧急度彩色分组、截止徽标（已超期红/今天橙） | 不新增、不删除、不重排 md 中的任务 |
| 启动本地回写服务（仅绑定 127.0.0.1）：勾选即回写 md 并刷新 task.html | 不处理归档——归档是 check-oa 的职责 |
| 静态模式（gen）：双击 task.html 也可用，勾选状态存浏览器 localStorage，页底提示条说明未回写 | 服务不开公网端口；凭据/页面均不涉及登录态 |

## 二、环境与路径（写死，与 cwd 无关）

| 项 | 路径/值 |
|---|---|
| 源文件 | `/media/data/AAAwork/OA任务.md` |
| 生成看板 | `/media/data/AAAwork/task.html` |
| 脚本 | `~/.claude/skills/showtask/scripts/showtask.py` |
| 回写服务 | `http://127.0.0.1:8642`（被占用自动顺延 8643~8661） |
| Python | `/media/data/claudewzp/venv-doc/bin/python`（或任意 python3，仅标准库） |

## 三、执行流程

1. **先刷新任务**：用 Skill 工具调用 `check-oa` 技能（无参数 = 近 10 天窗口，
   也可按需带 `-x天`/`-f`），等它输出摘要后再继续。check-oa 自带 2 小时频控：
   距上次检查不足 2 小时会跳过 OA/门户扫描、只做本地归档 [x] 与分桶刷新，
   几秒即返回。
2. 后台启动服务（Bash `run_in_background`）：
   ```bash
   /media/data/claudewzp/venv-doc/bin/python ~/.claude/skills/showtask/scripts/showtask.py serve
   ```
3. 把输出中的 URL 告诉用户：浏览器打开 `http://127.0.0.1:8642`。
4. 若输出"服务已在运行"，说明上一轮服务还活着，直接复用该 URL，不重复启动。
5. 用户勾选/取消勾选 → 页面即时划线置灰并移入/移出底部"已完成"分组，md 同步回写，无需刷新。
6. 提醒用户：勾成 `[x]` 后，下次运行 `/check-oa` 会自动把这些项归档到 `已完成任务.md`。
7. 用户不需要看板时，用 TaskStop 停掉后台服务任务。

## 四、子命令

- `serve`（缺省）：生成 task.html + 启动回写服务。每次 GET 都从 md 现渲染，页面永远与 md 同步。
- `gen`：仅生成静态 task.html。双击即可打开看板，但勾选不回写 md（页面底会出现黄色提示条，localStorage 暂存勾选状态，接入服务后自动尝试同步）。
- 服务已在跑时再执行 `serve`：打印"服务已在运行"并退出，不重复占用端口。

## 五、与 check-oa 的分工

- check-oa：从 OA/融合门户扫描新任务 → 写 `OA任务.md`；顺带把 `[x]` 项归档到 `已完成任务.md`。
- showtask：只读 md 渲染看板 + 回写完成标志，是 check-oa 与用户之间的"勾选界面"。
- showtask 每次运行**先调 check-oa 刷新任务**（频控内复用最近一次扫描结果），再渲染看板；serve 每次 GET 都从 md 现渲染，两技能无需共享状态。
- 两技能对 md 的约定格式（`- [ ] \`ID\` 动词：标题` + 两空格缩进子项）保持一致；showtask 只按任务 ID 精确定位该行改 `[ ]`↔`[x]`，其余内容一字不动。
- 手动个人任务（无 `OA-` ID，如 `## 个人任务` 分节里的项）照常显示在看板上，
  可勾选回写：页面用 `manual:<标题>` 作标识，回写时按整行标题定位，其余内容一字不动。
