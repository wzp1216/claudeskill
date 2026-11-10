# 通达 OA 读取适配（check-oa 30 天窗口）

通达 OA = "浙江工业职业技术学院_网络智能办公系统"（xt.zjipc.cn）。服务端渲染
PHP 页面，浏览器自动化读取，不逆向接口。**本文件沿用 normal-work
`references/oa-tongda.md` 的实测链路（2026-11-08/11-10 校准），仅扩展
30 天窗口读取与行动词判定。**

## 入口与登录（复用实测结果）

| 项 | 值 |
|---|---|
| **首选路径** | 融合门户首页"我的系统"→ **"OA办公"卡片**（`li.nav-bar-item[title="OA办公"]`）→ 新标签页 SSO 直达 `https://xt.zjipc.cn/general/` |
| 直接路径 | `https://xt.zjipc.cn/general/`（登录态跨会话复用，无跳转即已登录；出现"用户未登录"则回门户 SSO） |
| 登录凭据 | 本 skill `data/config.json`（user 字段：job_number/password；本机使用） |
| 收件箱 | `https://xt.zjipc.cn/general/email/inbox/?BOX_ID=0&boxname=inbox0&boxid=0` |
| 读信 | `/general/email/inbox/read_email/read_email.php?PAGE_START=&EMAIL_ID=<id>&BOX_ID=0&CURSOR_ID=<n>&BODY_ID=<n>&BTN_CLOSE=2` |
| 公告详情 | `/general/notify/show/read_notify.php?NOTIFY_ID=<id>` |
| 公告完整列表 | `/general/notify/show/` —— **路径未现场校准**；首次运行先试桌面面板 + 完整列表页，失败按降级标注并回填本表 |
| 我的工作详情 | `/general/approve_center/list/input_form/?RUN_ID=<id>&...`（**不打开**：有接收副作用） |

**不要用** `http://192.168.0.8`（邮件模块 503，异常节点）。curl 不可达不代表
浏览器不可达，以浏览器导航结果为准。

## 桌面面板三列表（近 N 条 + 未读徽标）

链路与 normal-work oa-tongda.md"桌面面板读取链路"一致：
进入 `/general/` → iframe `iframe[name="tabs_portal_5_iframe"]` 的
contentDocument → 图标桌面 `li.block[data-url]` → **点击块**后才动态创建弹窗
`div#dialogPanel` 并 AJAX 加载 → 点 tab 切换 → **用表头第一列文本校验**
（内部邮件="发件人"、公告="发布人"、我的工作="状态"）防读到陈旧表格 →
`#panel_content table.TableList`（`tr.TableLine1/2`，a[title] 完整标题、
a[onclick] 含 EMAIL_ID/NOTIFY_ID/RUN_ID）。**读列表无已读副作用。**

提取脚本模板直接复用 oa-tongda.md 的实测脚本（复制后按需裁剪）。
我的工作行状态看第一列 img 的 alt（"已接收"/"未接收"）。

## 30 天窗口读取

1. 桌面面板三列表先读一遍（当前待办 + 最近邮件/公告）
2. **邮件**：导航完整收件箱 `/general/email/inbox/?BOX_ID=0&boxname=inbox0&boxid=0`
   （主框架内），列表按日期分组（"星期五/11-6"式），未读图标
   `/static/images/email/2013/unread.png`；收集**近 30 天**全部邮件条目
   （主题/发件人/时间/未读状态/EMAIL_ID，从行内链接 onclick 取 EMAIL_ID）
3. **公告**：桌面面板列表 + 尝试完整列表页（未校准，见上）
4. **我的工作**：桌面面板即全部待办（历史已办结不在面板，无需回溯）

## 行动词判定（候选条目）

标题或正文出现以下词之一 → 候选（需打开正文确认要求与截止）：
报送、提交、上报、申报、反馈、填写、填报、汇总、统计、截止、完成、落实、
送审、审核、审批、传阅、征询、意见征求、交材料、报送材料。
我的工作面板条目**全部**为候选，但**不打开详情**（接收副作用），直接以
列表信息（流水号/工作名称/步骤名称/状态）生成任务项，截止取工作名称中的
日期（如"20261020 关于…"）或标"截止未明确"。

## 打开正文（提取发布人/要求/截止）

- 每封：主题、发件人 h3（description=部门）、时间、正文纯文本前 800 字
- **截止时间提取**：正文中的"11月11日（周三）中午前"→ `2026-11-11 12:00`；
  "11月15日前"→ `2026-11-15`；"本周五下班前"→ 计算具体日期；年份缺失用
  当前年份；跨年（12月-1月）按实际推断。**无法确定则不加截止，标"截止未明确"**
- 已读副作用：打开即已读；**每次运行最多 20 封**（未读优先、时间倒序），
  摘要注明"本次读取已读 N 封"

## 来源 ID 与去重

- 邮件 `oa-mail-<EMAIL_ID>`、公告 `oa-notice-<NOTIFY_ID>`、
  我的工作 `oa-approve-<流水号>`
- `task_manager.py add` 自动跳过任务文件与归档文件中已存在的同来源 ID
- 手动项用 `manual-<YYYYMMDD>-<自增>` 作来源 ID

## 提取失败判定与降级标注

- 三面板任一 `{err}`/表头不匹配/rows 空且 badge 缺失 → **不得当作"无任务"**；
  标注"未读取（提取失败：<原因>）"，恢复后请重跑 check-oa
- 页面可达但结构变化 → 停止脚本、重新快照、回填本表，**不要盲改选择器**

## 校准记录

- 2026-11-10（第 1 次）：创建。SSO 链路、桌面面板三列表、读信/公告详情 URL、
  收件箱分组结构沿用 normal-work 2026-11-08/11-10 实测；30 天窗口与行动词
  判定为本技能新增。
- 尚未实测：公告完整列表页路径（`/general/notify/show/`）、读信页正文容器
  选择器（沿用"body.innerText + iframe 文本"兜底）。首次运行现场校准后回填。
