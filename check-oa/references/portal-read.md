# 融合门户读取适配（check-oa 任务检测视角）

融合门户 = dsc.zjipc.cn（layui SPA）。**DOM 结构、校准参数、登录链路、
来源 ID 规则全部沿用 `references/portal-dsc.md` 的实测结果
（2026-11-08/11-09 校准，原 normal-work 技能，2026-11-13 并入本 skill），
本文件只扩展 check-oa 需要的：N 天窗口过滤、行动词判定、任务化
（发布人/要求/截止提取）与降级标注。**

门户登录：check-oa 从本 skill `data/config.json` 读工号+密码自动填入 CAS
（`ua.zjipc.cn/cas/login`），与 OA 步骤一致，不重复登录。

## 窗口参数

- 运行参数 `-x天`（如 `-20天`）决定本次检测窗口 N；缺省取 config
  `limits.scan_days`（10）。
- 门户三个数据源与 OA 用**同一个 N**：校内通知过滤近 N 天发布，
  会议公告/本周会议报表按"今天起未来"过滤（会议是将来事件，不看过去 N 天）。

## 数据源一：校内通知（首页默认 tab）

1. `navigate_page` 首页 → `wait_for` "校内通知"（15s）；顶部"欢迎您,<姓名>"
   即已登录
2. `evaluate_script` 提取 `li.news-type-item` 列表
   `{title, date: p.news-date, href}`（空则回退 `take_snapshot`）
3. 过滤：发布时间在**近 N 天**内；条数上限 config `limits.notice_max`
   （30）。列表页面不翻页（首页 tab 只提供近期列表，超出窗口的公告
   完整列表在 OA 侧已覆盖）
4. **行动词判定**：标题含行动词（与 oa-read.md 行动词表一致，另加
   会议/培训/检查）的条目为候选
5. 候选条目打开详情（imy.zjipc.cn 新闻站新标签页，`a.news-content[target=_blank]`
   的 href）：**每次运行最多 5 条**（config `limits.notice_detail_max`，
   按时间倒序取最近），提取：
   - 发布人：imy 详情页中的发布部门（结构未校准时用首页列表无部门字段，
     标"融合门户-校内通知"）
   - 要求：正文摘要 ≤80 字
   - 截止：正文中文日期转 `YYYY-MM-DD [HH:MM]`（规则同 oa-read.md
     "打开正文"节）；无法确定则不加截止
6. 正文确有明确办理要求（交材料/填表/参会等）→ 生成任务项；
   纯知会/转发学习 → 不入单，摘要一句带过

## 数据源二：会议公告（首页"会议系统"tab）

1. `evaluate_script` 点 `ul.layui-tab-title li`（textContent="会议系统"）
   → SPA 到 `#/portal/newsPage/typeId=..` → 提取 `li.news-detail-item`
   （标题 `p.news-content`/来源部门 `p.news-department`/时间 `p.news-time`/
   `data-id`/href）
2. 过滤：**今天至未来 3 天**的会议；参会对象含"教务处"或用户姓名的条目
   重点标注（列表拿不到参会对象时开详情确认）
3. 候选（本部门/本人相关，或标题含行动词）打开详情：**最多 3 条**
   （config `limits.meeting_detail_max`）
4. 入单：需本人/本部门参会的会议 → 任务项（发布人=来源部门或召集部门，
   要求=会议时间地点摘要，截止=会议开始时间 `YYYY-MM-DD HH:MM`）；
   无关会议不入单

## 数据源三：本周会议报表（FineReport）

1. 计算本周一日期（周五-周日同时拉本周与下周；周日规则同 portal-dsc.md）
2. `navigate_page` 到周会议报表 URL（config `urls.portal_report` 替换
   `<周一日期>`）；302 到 CAS 先登录
3. `wait_for` "会议名称"；`evaluate_script` 读 `table.x-table`：
   遍历 `tr[tridx]` 取 td 文本转二维数组（跳过 display:none 的 B/D 隐藏列），
   去空行
4. 筛选：**今天至未来 3 天**且参加人员（J 列）或备注含"教务处"/用户姓名
   的行；**周五-周日拉下周报表时放宽为下周整周**
5. 入单：每行一条任务项（发布人=召集部门（I 列）+主持人（H 列），
   要求=会议名称+地点，截止=会议日期+时间（B 列完整日期+F 列时间））；
   其余本部门无关会议不入单，摘要一句带过
6. 与 OA 侧已入单的会议任务靠来源 ID 去重（同一会议两处都出现时只留一条）

## 来源 ID 与去重（沿用 portal-dsc.md 规则）

- 校内通知：`notice-<imy 页面 cXXXXaNNNNN 号>`；会议公告：
  `meeting-<li.news-detail-item 的 data-id>`；周会议条目：`report-<D 列隐藏 ID>`
- 无页面 ID 时：`portal-` + md5（来源类型 + 规范化标题）前 12 位
- `task_manager.py add` 自动跳过任务文件与归档文件中已存在的同来源 ID
  （门户与 OA 同查）

## 提取失败判定与降级标注

- 任一数据源 `{err}`/结构变化/列表提取为空且未确认"无内容" →
  **不得当作"无任务"**；聊天摘要注明"门户<数据源>未读取（提取失败：<原因>）"，
  OA 部分照常
- 门户整体不可用（导航失败/无 MCP）→ 摘要注明"门户不可用（原因）"，
  任务文件不动，**不阻塞 OA 扫描**；恢复后重跑即可
- 页面可达但结构变化 → 停止脚本、重新快照定位、回填
  `references/portal-dsc.md` 校准参数表与本文件，**不要盲改选择器**

## 校准记录

- 2026-11-11（第 1 次）：创建。DOM/URL/来源 ID 规则沿用 portal-dsc.md
  2026-11-08/11-09 实测；N 天窗口、行动词判定、任务化提取
  （发布人/要求/截止）与降级标注为本技能新增。
- 尚未实测：imy 通知详情页正文容器与发布部门位置（首次开详情时回填）。
- 2026-11-13：默认窗口由 30 天改为 10 天（与 oa-read.md 一致）。
- 2026-11-18（第 2 次）：imy 详情页实测——无独立正文容器，`document.body.innerText`
  即为"发布者+发布时间+正文+附件名"；部分通知正文仅为附件（docx），列表标题即
  全部可用信息。周会议报表隐藏 D 列 ID 可用 `getComputedStyle(td).display==='none'`
  识别隐藏列后取文本（每行第 5 个 td 为 D 列 ID，行头行除外）。
