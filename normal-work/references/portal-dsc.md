# 融合门户适配（dsc.zjipc.cn）

门户是 layui SPA：静态空壳 HTML + `pcportalng` 业务 API（需 CAS token）。
**所有读取走浏览器自动化**（chrome-devtools MCP），不逆向 token、不直接调 API。

## 已确认信息

| 项目 | 值 |
|---|---|
| 首页 | `https://dsc.zjipc.cn/pcportal/start/index.html#/portal/home` |
| 登录 | `https://ua.zjipc.cn/casClient/login/pcportal`（CAS 统一认证） |
| 业务 API 基址 | `https://dsc.zjipc.cn/pcportalng` |
| 周会议报表（FineReport） | `https://dsc.zjipc.cn/webroot/decision/view/report?viewlet=xxkj%2Fhdqd%2Fhyapb_week.cpt&date=<周一日期>` |
| hosts | `dsc.zjipc.cn → 192.168.180.53`（内网直连，无需代理） |

## 校准参数表（唯一改动点，首次校准后回填）

| 参数 | 当前值/假设 | 状态 |
|---|---|---|
| 首页"校内通知"组件标题文本 | 校内通知 | 待联调 |
| 首页"会议公告"组件标题文本 | 会议公告 | 待联调 |
| 通知列表"更多"入口 | 待记录 | 待联调 |
| 通知列表项选择器 | 待记录 | 待联调 |
| 通知详情正文容器 | 待记录 | 待联调 |
| 会议公告列表/详情结构 | 待记录 | 待联调 |
| 会议报表表格容器 | 待记录 | 待联调 |
| CAS 登录页特征 | 待记录 | 待联调 |

## 提取步骤

### 校内通知 / 会议公告

1. `navigate_page` 首页，`wait_for` 组件标题文本（超时 15 秒）
2. 优先 `evaluate_script` 把列表转紧凑 JSON（标题、发布部门、时间、链接/ID）；
   为空则回退 `take_snapshot` 解析
3. 过滤：发布时间最近 2 天（config `limits.notice_days_back`）；保留截止日期在
   7 天内的；总数上限 15 条（`notice_max`）
4. 标题含行动词（申报/报送/提交/汇总/统计/检查/会议/培训）的条目，最多打开
   5 条详情（`notice_detail_max`），提取正文短摘要、截止日期、原始链接
5. 会议公告同理：提取会议名称、时间、地点、组织部门、参会对象、材料要求；
   过滤今天及未来 3 天（`meeting_days_ahead`）；参会对象含"教务处"或用户姓名
   的条目重点标注；最多打开 3 条详情

### 本周会议安排（FineReport）

1. 计算本周一日期（周五-周日同时拉取本周与下周）
2. `navigate_page` 到周会议报表 URL（`date=<周一>`）；若 302 到 CAS 先登录
3. `wait_for` 表格出现；`evaluate_script` 把表格转二维数组（表头+行），去空行
4. 只写入今天至未来 3 天与本部门相关的行；完整表用链接指向报表

## 来源 ID 规则（去重用）

- 页面提供 ID 时直接使用（如 `notice-<id>`）
- 否则：`portal-` + md5（来源类型 + 规范化标题）前 12 位
- 同日重跑按来源 ID 去重，不重复添加建议项

## 异常处理

- 登录跳转/会话失效 → 按 browser-session.md 处理
- 组件结构变化 → 重新快照定位，回填校准参数表；**失败即停并报告**，不盲点
- 门户整体不可用 → 门户块写"未读取：<原因>"，计划照常生成其余部分
