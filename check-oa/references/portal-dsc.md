# 融合门户适配（dsc.zjipc.cn）

门户是 layui SPA：静态空壳 HTML + `pcportalng` 业务 API（需 CAS token）。
**所有读取走浏览器自动化**（chrome-devtools MCP），不逆向 token、不直接调 API。

> **状态：2026-11-08 已现场校准，全部参数实测。校准记录见文末。**

## 已确认信息

| 项目 | 值 |
|---|---|
| 首页 | `https://dsc.zjipc.cn/pcportal/start/index.html#/portal/home`（实际访问常带 `?t=<时间戳>` 缓存参数，可忽略） |
| 登录 | `https://ua.zjipc.cn/casClient/login/pcportal`（CAS 统一认证） |
| 登录态标志 | 顶部"欢迎您,万志平"（含姓名即已登录） |
| 业务 API 基址 | `https://dsc.zjipc.cn/pcportalng`（仅背景知识，不直接调用） |
| 周会议报表（FineReport） | `https://dsc.zjipc.cn/webroot/decision/view/report?viewlet=xxkj%2Fhdqd%2Fhyapb_week.cpt&date=<周一日期>` |
| hosts | `dsc.zjipc.cn → 192.168.180.53`（/etc/hosts 已配置，Chrome 可达） |

## 校准参数表（2026-11-08 实测）

| 参数 | 实测值 |
|---|---|
| 首页"校内通知"组件 | **layui tab**：`ul.layui-tab-title > li`，默认激活 tab 为"校内通知"（`lay-href="portal/newsPage/typeId=2557"`，id=news） |
| 首页"会议公告"组件 | 实为 tab **"会议系统"**（`typeId=d8dc8179233ab9be12dfe6464ed2fc57`）；首页并列 tab 还有：校领导接访(2532)、校领导公出(2531)、值班安排(2561)、报告厅使用(f8d3f5c2997de80bc4a206dec29caa64) |
| 通知列表项选择器 | `li.news-type-item`：`a.news-content.ellipsis[target=_blank][title=标题][href=链接]` + `p.news-date`（日期） |
| 通知详情入口 | 链接直接指向 `https://imy.zjipc.cn/<年>/<月日>/<cxxxxaNNNNN>/page.htm`（校外新闻站，新开标签页） |
| 通知详情正文容器 | imy.zjipc.cn 新闻详情页（新标签页打开后读取；结构待开详情时确认） |
| 会议列表页路由 | 点 tab 后 SPA 路由 `#/portal/newsPage/typeId=<id>` |
| 会议列表项 | `li.news-detail-item[data-id=<页面ID>]`：`a[href=链接] > div.news-head > p.news-content`（标题）+ `p.news-department`（资讯来源）+ `p.news-time`（发布时间）；列头行 `li.title-bar` |
| 会议列表 data-id | 可作为来源 ID（如 `meeting-<data-id>`），优先于 md5 |
| 会议报表表格容器 | `table.x-table`（单表，无 iframe 包裹，直接在报表页中） |
| 报表表头 | 学校领导一周会议预安排表：星期（日期）/会议名称/时间/地点/主持人/召集部门/参加人员 |
| 报表行结构 | `tr[tridx]`；隐藏列 B=完整日期、D=会议 ID（`ff8080...` 可作来源 ID）；显示列 C=星期(日期)、E=会议名称、F=时间、G=地点、H=主持人、I=召集部门、J=参加人员（名单+备注） |
| 报表周导航 | 底部"上一周 / <周一日期> / 下一周" |
| CAS 登录页特征 | 未登录访问报表 302 到 `ua.zjipc.cn/cas/login`；首页则显示"统一身份认证"登录表单 |

## 提取步骤

### 校内通知 / 会议公告

1. `navigate_page` 首页，`wait_for` "校内通知"（超时 15 秒）；顶部含
   "欢迎您,<姓名>"即已登录
2. 优先 `evaluate_script` 提取：默认 tab 列表为
   `[...document.querySelectorAll('li.news-type-item')]` →
   `{title: a.news-content.textContent, date: p.news-date.textContent,
   href: a.href}` 紧凑 JSON；为空则回退 `take_snapshot` 解析
3. 会议列表：`evaluate_script` 点击 `ul.layui-tab-title li`（textContent 为
   "会议系统"）→ SPA 跳转 `#/portal/newsPage/typeId=..` → 提取
   `li.news-detail-item` 行（标题/来源/时间/data-id/href）
4. 过滤：发布时间最近 2 天（config `limits.notice_days_back`）；总数上限
   15 条（`notice_max`）
5. 标题含行动词（申报/报送/提交/汇总/统计/检查/会议/培训）的条目，最多打开
   5 条详情（`notice_detail_max`，imy 新闻站新标签页），提取正文短摘要、
   截止日期、原始链接
6. 会议公告过滤今天及未来 3 天（`meeting_days_ahead`）；参会对象含"教务处"
   或用户姓名的条目重点标注；最多打开 3 条详情

### 本周会议安排（FineReport）

1. 计算本周一日期（周五-周日同时拉取本周与下周）
2. `navigate_page` 到周会议报表 URL（`date=<周一>`）；若 302 到 CAS 先登录
3. `wait_for` "会议名称"出现；`evaluate_script` 读 `table.x-table`：
   遍历 `tr`，取 td 文本（跳过 `display:none` 的 B/D 列），转二维数组去空行
4. 写入范围：今天至未来 3 天；**周五-周日拉下周报表时放宽为下周整周**，
   只写与本部门相关（参加人员含"教务处"/用户姓名，或备注提及教务处）的行；
   其余入一行文字摘要
5. 参会人含用户姓名的行加粗/重点标注；文件末尾附"查看完整周会议报表"链接
   （带当前报表 date 参数）

## 来源 ID 规则（去重用）

- 页面提供 ID 时直接使用：会议公告 `meeting-<li.news-detail-item 的 data-id>`；
  周会议条目 `report-<D 列隐藏 ID>`；通知详情 `notice-<imy 页面 cXXXXaNNNNN 号>`
- 否则：`portal-` + md5（来源类型 + 规范化标题）前 12 位
- 同日重跑按来源 ID 去重，不重复添加建议项

## 异常处理

- 登录跳转/会话失效 → 按 browser-session.md 处理
- 组件结构变化 → 重新快照定位，回填本校准参数表；**失败即停并报告**，不盲点
- 门户整体不可用 → 门户块写"未读取：<原因>"，计划照常生成其余部分

## 校准记录

- 2026-11-08：实测回填全部参数。首页 layui tab 结构、通知/会议列表 DOM、
  会议 tab typeId、FineReport 报表表格（含隐藏日期/ID 列）、周导航。会议
  公告组件名从"会议公告"更正为"会议系统"；1.3 小节标题保留"本周会议安排"。
- 尚未实测：imy 通知详情页正文容器（首次开详情时回填）。
- 2026-11-09：实测回填 CAS 重登流程与 OA 入口。未登录访问门户 302 到
  `ua.zjipc.cn/cas/login`；登录表单字段 username（工号）/password +
  "我已阅读并同意"隐私勾选（默认已勾）+ 登录按钮，登录成功后自动跳回
  门户首页。首页"我的系统"区"OA办公"卡片（serve-id=
  860340B10FB5C60304D6C20699208C85，fwdz=`https://ua.zjipc.cn/casClient/login/oa`）
  点击后**新标签页** SSO 直达 OA。
