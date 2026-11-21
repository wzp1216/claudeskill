# 通达 OA 适配（xt.zjipc.cn）

通达 OA = "浙江工业职业技术学院_网络智能办公系统"。服务端渲染 PHP 页面，
浏览器自动化读取/填写即可，不逆向接口。

> **状态：2026-11-08 重新现场校准（含桌面面板读取链路全流程实测）。**
> 校准日期与变更记录见文末。**此前一版文档描述的桌面面板结构（进入即见
> dialogPanel/tab）有误，是导致 OA 内容提取为空的直接原因**，已废弃。

## 正确入口（2026-11-08 修正）

| 项 | 值 |
|---|---|
| **首选路径** | 融合门户首页"我的系统"→ **"OA办公"卡片** → SSO 直达 `https://xt.zjipc.cn/general/` |
| 直接路径 | `https://xt.zjipc.cn/general/`（浏览器登录态跨会话复用，无跳转即已登录） |
| 邮件模块 | `https://xt.zjipc.cn/general/email/` |
| 写邮件 | `https://xt.zjipc.cn/general/email/new/`（iframe 内） |
| 桌面面板 | `https://xt.zjipc.cn/portal/personal/`（OA 主框架 `iframe[name=tabs_portal_5_iframe]` 内） |

**不要用** `http://192.168.0.8`：该节点的邮件模块返回 503（上游服务状态异常，
旧地址/异常节点），主框架虽可开但功能不全。

**网络注意**：本机 curl 直连 xt.zjipc.cn 可能失败（No route to host，
本机在 10.88.x VPN 网段），但 **Chrome 内可达**。一切连通性判断以浏览器
导航结果为准，不用 curl 判断 OA 死活。

**登录凭据**（用户提供，2026-11-08）：门户/OA 账号 `19980005`（万志平，
教务处）。登录页出现时从本机 `data/config.json`（user 字段）读取账号密码
自动登录；凭据只存本机 config.json，不写入其它文件（草稿/审计/计划/
外发内容）。

## 已确认信息（2026-11-08 实测）

| 项目 | 值 |
|---|---|
| OA 基址 | `https://xt.zjipc.cn`（Chrome 内可达，直接导航无跳转即已登录） |
| 主框架 | `/general/`，内含唯一业务 iframe：`iframe[name="tabs_portal_5_iframe"]` → `/portal/personal/`（同源，可直接 `contentDocument` 访问） |
| 收件箱 | `/general/email/inbox/?BOX_ID=0&boxname=inbox0&boxid=0` |
| 收件箱计数 | 226 封（11-08）；桌面面板"内部邮件"tab 徽标显示未读数 |
| 读信 | `/general/email/inbox/read_email/read_email.php?PAGE_START=&EMAIL_ID=<id>&BOX_ID=0&CURSOR_ID=<n>&BODY_ID=<id>&BTN_CLOSE=2` |
| 写邮件 | `/general/email/new/`（3 分钟自动存草稿，填表有草稿副作用） |
| 发件箱 | `/general/email/sentbox/?BOX_ID=0` |
| 草稿箱 | `/general/email/outbox/?BOX_ID=0` |
| 邮件列表结构 | 完整模块：按日期分组（"星期五/11-6"），每封 `h3` 发件人（description=部门）、主题文本、状态图标 |
| 未读图标 | `/static/images/email/2013/unread.png`；已读 `readed.png`；星标 `whitestar.png` |
| 我的工作详情 | `/general/approve_center/list/input_form/?RUN_ID=<id>&FLOW_ID=..&PRCS_ID=..&FLOW_PRCS=..` |
| 公告详情 | `/general/notify/show/read_notify.php?NOTIFY_ID=<id>` |

## 桌面面板（/portal/personal/）读取链路 —— 2026-11-08 实测修正

**重要：进入桌面面板时页面只有图标桌面，没有列表。列表弹窗在点击对应图标
后才动态创建并 AJAX 加载。不点图标就没有任何数据——这就是此前"提取为空"
的根因。** 旧版文档的"进入即有 li[data-url] tab + dialogContent 表格"描述
与实况不符，已废弃。

实测流程（每一步均在浏览器中验证通过）：

1. 导航 `https://xt.zjipc.cn/general/`，确认标题为
   "浙江工业职业技术学院_网络智能办公系统"（出现登录页则请用户登录，
   账号见上）
2. 桌面 iframe：`document.querySelector('iframe[name="tabs_portal_5_iframe"]')`
   的 `contentDocument`（同源可直接访问；`evaluate_script` 在此上下文中
   执行脚本即可读到 iframe 内 DOM）
3. 图标桌面结构：`div#container > ul.ui-sortable > li.block[data-url]`，
   每块含 `div.count#count_<id>`（未读徽标）与文本。三个面板块：

   | 面板 | 块选择器（data-url） | 弹窗 tab id |
   |---|---|---|
   | 内部邮件 | `li.block[data-url="email"]` | `#dialog_title_1` |
   | 公告通知查阅 | `li.block[data-url="notify/show/index.php"]` | `#dialog_title_4` |
   | 我的工作 | `li.block[data-url="approve_center/list"]` | `#dialog_title_301` |

4. 点击块 → 弹窗 `div#dialogPanel`（含 `div.dialogNav` 三个 tab + 每 tab
   徽标未读数 + `div.dialogContent`）；点击 tab 切换面板内容。
   **坑1**：点击块后弹窗和表格是异步出现的，必须轮询等待。
   **坑2**：tab 切换按需加载，已加载过的 tab 有缓存；读取前必须用
   **表头单元格文本校验**确认当前表格是目标面板，防读到上一个 tab 的
   陈旧表格（表头第一列：内部邮件="发件人"、公告="发布人"、
   我的工作="状态"）。
5. 表格位于 `#panel_content table.TableList`：
   表头 `tr.TableHeader td`，数据行 `tr.TableLine1/tr.TableLine2`
   （隔行配色两 class）。行内主题/标题为 `a`，完整标题在 `a[title]`，
   详情 URL 在 `a[onclick]`（含 EMAIL_ID / NOTIFY_ID / RUN_ID）。
6. 各面板列结构（2026-11-08 实测）：
   - 内部邮件：发件人 / 邮件主题 / 附件 / 发送时间 / 大小
     （发件人列 td 的 `title` 属性 = "部门：..."）
   - 公告通知：发布人 / 类型 / 公告标题 / 发布范围（"部门：.."或
     "角色：.."） / 生效日期
   - 我的工作：状态图标（email_open.gif=已接收 / email_close.gif=未接收）
     / 流水号 / 工作名称·文号 / 步骤名称 / 流程类别
7. **无已读副作用**：桌面面板列表本身不标已读（读信/点详情才产生副作用）。

### 提取脚本模板（实测通过，复制后按需裁剪）

```js
() => {
  const f = document.querySelector('iframe[name="tabs_portal_5_iframe"]');
  if (!f) return {err: 'no portal iframe'};
  const doc = f.contentDocument || f.contentWindow.document;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const waitFor = async (fn, ms) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { const v = fn(); if (v) return v; await sleep(250); }
    return null;
  };
  const readPanel = async (url, tabId, expectHeader) => {
    let dlg = doc.getElementById('dialogPanel');
    if (!dlg) {
      const block = doc.querySelector('li.block[data-url="' + url + '"]');
      if (!block) return {err: 'no block ' + url};
      block.click();
      dlg = await waitFor(() => doc.getElementById('dialogPanel'), 8000);
      if (!dlg) return {err: 'dialog not opened ' + url};
    }
    const tab = doc.getElementById(tabId);
    if (!tab) return {err: 'no tab ' + tabId};
    if (!tab.classList.contains('active')) { tab.click(); await sleep(400); }
    // 严格等待：表头第一列必须匹配，防止读到上一个 tab 的陈旧表格
    const ok = await waitFor(() => {
      const t = dlg.querySelector('#panel_content table.TableList');
      const first = t ? (t.querySelector('tr.TableHeader td') || {}).innerText : '';
      return first && first.trim() === expectHeader ? t : null;
    }, 10000);
    if (!ok) {
      tab.click(); await sleep(500); // 重试一次
      const t = dlg.querySelector('#panel_content table.TableList');
      const first = t ? (t.querySelector('tr.TableHeader td') || {}).innerText : '';
      if (!first || first.trim() !== expectHeader)
        return {err: 'header mismatch for ' + url + ': got [' + (first || '').trim() + ']'};
    }
    const t = dlg.querySelector('#panel_content table.TableList');
    const hdr = Array.from(t.querySelectorAll('tr.TableHeader td')).map(x => (x.innerText || '').trim());
    const rows = Array.from(t.querySelectorAll('tr.TableLine1,tr.TableLine2')).map(tr => {
      const cells = Array.from(tr.querySelectorAll('td')).map(x => (x.innerText || '').trim().replace(/\s+/g, ' '));
      const a = tr.querySelector('a');
      return {cells, aTitle: a ? (a.getAttribute('title') || '') : '', aOnclick: a ? (a.getAttribute('onclick') || '') : ''};
    });
    const badge = tab.querySelector('.dialog-nav-num');
    return {header: hdr, rows, badge: badge ? badge.innerText.trim() : ''};
  };
  return (async () => ({
    email:   await readPanel('email', 'dialog_title_1', '发件人'),
    notify:  await readPanel('notify/show/index.php', 'dialog_title_4', '发布人'),
    approve: await readPanel('approve_center/list', 'dialog_title_301', '状态'),
  }))();
}
```

返回 JSON：三面板各自的 header/rows/badge。rows 中：
- 邮件 EMAIL_ID 从 `aOnclick` 正则 `/EMAIL_ID=(\d+)/` 取；
  发件人部门从第一列 td 的 title 属性取（脚本未含，需要时在 cells 循环里加
  `td.getAttribute('title')`）
- 公告 NOTIFY_ID 从 `/NOTIFY_ID=(\d+)/` 取；发布范围看 cells[3] 前缀
  "部门："或"角色："
- 我的工作流水号 = cells[1]；状态看第一列 img 的 alt（"已接收"/"未接收"）

### 面板过滤规则（沿用）

- 邮件：只收最近 2 天发送的（按"发送时间"列）；需要行动/回复的才生成建议项
- 公告：只收最近 2 天生效、发布范围含"教务处"或含本人姓名的
- 我的工作：全部列出，重点标"未接收"；只入计划不代审批

## 读取收件箱（完整模块，需要正文/附件清单时）

1. `navigate_page https://xt.zjipc.cn/general/email/`，收件箱在 iframe 内，
   列表按日期分组，未读图标 `unread.png`
2. 只打开最近 2 天未读/需办理邮件，上限 10 封（`oa_mail_max`）；每封提取
   主题、发件人、时间、正文纯文本前 500 字、附件名列表
3. **已读副作用**：打开邮件即标记已读。限量打开，并在计划中注明
   "读取时已读 N 封"，绝不批量全部打开
4. 分类：需办理 / 需回复 / 仅知会 / 参考；只有"需办理且能明确行动"的邮件
   生成建议计划项

## 我的工作（OA 待办）

- 桌面"我的工作"面板列出待办流程：状态、流水号、工作名称/文号、步骤名称、
  流程类别；行链接 onclick 含详情 URL（RUN_ID/FLOW_ID/PRCS_ID）
- 状态"未接收"（email_close.gif）表示尚未处理；"已接收"表示已打开过
- 打开详情页有接收副作用，同样限量；列表中已含关键信息时不必逐条打开
- 需办理的待办可生成建议计划项（来源 `oa-approve`，来源ID 用流水号）

## 公告通知（OA 公告）

- 桌面"公告通知查阅"面板：发布人、类型、公告标题、发布范围、生效日期
- 只提取最近 2 天生效且发布范围含本人所在部门/角色的公告
- 公告标题点击进入正文（`/general/notify/show/read_notify.php?NOTIFY_ID=<id>`），
  点开有已读副作用，限量

## 提取失败判定与降级标注（重要）

三面板中任一返回 `{err: ...}`、表头不匹配、或 rows 为空数组且 badge 缺失
时，**不得当作"（无）"处理**——"（无）"表示"读取成功且确实没有新内容"，
两者必须区分：

- 全部面板失败 → OA 状态写 `未读取（提取失败：<err 摘要>）`，日文件 OA 块
  写"OA 未读取（提取失败：<原因>），恢复后请运行'刷新OA'"，**禁止写入
  "（无）"或留空**，并 `set-status --oa 未读取（提取失败）`
- 部分面板失败 → 成功面板照常写入，失败面板标注"未读取（原因）"
- 页面可达但结构变化（找不到 `li.block[data-url]` 等）→ 停止脚本、重新快照、
  回填本文件校准表，**不要盲改选择器**

## 写邮件并发送 → 由 oa-email 技能负责

**本技能不撰写、不发送任何 OA 邮件**。写邮件页表单细节（收件人选择器、
主题/正文定位、默认勾选项、发送核实流程）见 oa-email 技能的
`references/oa-send.md`。本文件仅保留读取侧适配。

下方"已确认信息"表中的写邮件/发件箱条目仅供参考（oa-email 复用同一浏览器
登录态与入口）。

## 收件人确认规则

收件人确认由 **oa-email 技能**负责（发送时在写邮件页收件人选择器搜索确认，
并更新共享 contacts.json）。本技能只在读取侧把发件人 h3 的 description 属性
（"部门：..."）作为联系人部门信息来源的线索，写入 contacts.json 前仍需用户
确认。

## 校准记录

- 2026-11-08（第 2 次，重要修正）：实测发现旧版"桌面面板进入即有 tab 列表"
  描述与实况不符——实际是图标桌面（`li.block[data-url]`），点击图标才动态
  创建弹窗并 AJAX 加载列表。**这就是当次 OA 邮件/公告/我的工作提取为空、
  OA 块误写"（无）"的根因**。重新实测并回填：图标桌面结构、弹窗
  dialogPanel/dialogNav/dialogContent、`#panel_content table.TableList`
  行结构、表头校验防陈旧表格、徽标未读数、三面板完整提取脚本（已实测
  通过）。补充登录凭据说明与"提取失败降级标注"规则。
  当日实际数据：内部邮件面板 2 封（未读 2）、公告 2 条（未读 2）、
  我的工作 4 项（含 3 项未接收）。
- 2026-11-08（第 1 次）：通过融合门户"OA办公"SSO 进入 OA 成功。实测并回填：
  邮件模块页面（收件箱列表结构、未读图标、写邮件表单、收件人选择器弹窗、
  默认勾选项）、读信与待办详情 URL 模式。修正入口：弃用 192.168.0.8，
  改用 xt.zjipc.cn。（桌面面板部分描述有误，已被同日第 2 次校准取代）
- 尚未实测：邮件详情正文容器、附件下载（读取侧）。实际发送流程与成功提示
  归 oa-email 技能，由其在 `references/oa-send.md` 回填。
