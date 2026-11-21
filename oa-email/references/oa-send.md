# OA 邮件发送与核实（xt.zjipc.cn）

通达 OA = "浙江工业职业技术学院_网络智能办公系统"。基址、入口、登录凭据与
网络注意复用 `references/oa-tongda.md`（写邮件页结构与收件人
选择器已在那里实测校准）。本文件专注 oa-email 的发送流程细节与校准记录。

## 进入 OA 的路径（2026-11-09 用户指定，优先使用）

1. 门户首页 `https://dsc.zjipc.cn/pcportal/start/index.html#/portal/home`
   （实际访问常带 `?t=<时间戳>` 缓存参数，可忽略）
2. 首页 → "我的系统" → **"OA办公"卡片** → SSO 直达
   `https://xt.zjipc.cn/general/`
3. **OA 会话失效（页面显示"用户未登录"）时优先走此 SSO 路径刷新会话**；
   门户 SSO 异常时才直接导航 xt.zjipc.cn 登录页登录

## 发送流程（2026-11-08 首次真实发送实测通过）

1. 按上节路径进入 OA（登录态复用；出现登录页则从本机 `data/config.json`
   的 user 字段读账号密码自动登录，凭据只存本机）后，`navigate_page` 到
   `https://xt.zjipc.cn/general/email/new/`
2. 收件人：点收件人区**标签式"添加"链接**（`#inbox-container` 内
   `a.td-contact-add.orgAdd`）→ 弹层选择器**懒加载**，需 `take_snapshot`
   确认出现。结构：已选/部门/角色/分组/在线 tab + 搜索框 + 组织树 +
   右侧用户列表 + 全部添加/全部删除 + 确定。
   - 用户列表项：`div.block-right-item`，属性 `item_id`/`user_id`（OA 工号）、
     `item_name`（姓名）、`title`（如"中层干部[校领导/教务处]"）
   - 点条目 → class 变 `active` 即选中；点"确定" → 写邮件页隐藏字段
     `TO_ID`/`TO_NAME` 填充（值形如 `19980005,`，尾逗号）
   - 本人（万志平）条目 item_id=19980005，在组织树"校领导/教务处"分组下
   - **不要用**旧 SelectAddr 入口（`onclick="SelectAddr('EMAIL','TO_WEBMAIL')"`
     的"添加"）打开的 frameset 选择器（`/module/addr_select/`）：其通讯簿
     分组全空、"OA用户查询"对任何条件（姓名/工号/部门）都返回
     "无符合条件的记录"，不可用
3. 主题：`input[name="SUBJECT"]`；正文：编辑器是 **UEditor**（可见
   iframe `#ueditor_0` + 真正提交的隐藏
   `textarea[name="TD_HTML_EDITOR_CONTENT"]`）。**必须用编辑器 API 写入**：
   `UE.getEditor('TD_HTML_EDITOR_CONTENT').setContent('<p>段1</p><p>段2</p>')`
   （每段一个 `<p>`，空行 `<p><br></p>`；setContent 会同步隐藏 textarea
   与 iframe 显示）。**禁止直接写 iframe innerHTML**：只改显示、不同步
   真正提交的 textarea → 收件人收到 0 字（2026-11-09 实测确认此坑）；
   抄送"添加抄送"按需，密送默认不用
4. **默认勾选"发送事务提醒消息"**（`tranRemind=true`）：按预览决定保留或
   取消；"请求阅读收条"默认不勾
5. 发送前用 `evaluate_script` 读取表单实际 TO_ID/TO_NAME/SUBJECT 与
   **`textarea[name="TD_HTML_EDITOR_CONTENT"]` 的 value**（真正提交的
   正文字段，不是 iframe 显示内容——只读 iframe 会假通过），与预览
   **一致性核对**；不一致立即停止并报告
6. 点"立即发送"（`#btn_submit`，SubmitForm()）→ POST 到
   `general/email/new/submit.php` → 页面显示"提示 内部邮件发送成功"
   （本次无确认对话框；若出现 `handle_dialog accept` 只处理一次）
7. 核实：`navigate_page` 发件箱
   `https://xt.zjipc.cn/general/email/sentbox/?BOX_ID=0`，按主题+收件人+
   时间查最新记录（实测显示"今日 X秒前 <收件人> <主题>"）
8. 核实结果：
   - 找到 → 成功：草稿状态 `已发送 HH:MM`，`log-send --result sent` 写审计
   - 找不到但无失败提示 → `待核实`：提示用户检查发件箱，**不自动重发**
   - 明确失败 → `失败：<原因>`，草稿保留等待重试指令

## 附件上传（可选）

用户给出本地文件绝对路径时：

1. 发送前先核对文件存在且文件名与预览一致
2. 在写邮件页用 mcp 的 `upload_file` 上传到附件控件
3. 上传后读表单核对附件名；首次实测后回填下方校准表

## 收件人确认规则

- 收件人必须由用户明确给出，不自动从通知/邮件正文推断
- 查本 skill `data/contacts.json`（check-oa 只读共享）：
  姓名+部门精确匹配且 `verified=true` 直接使用；唯一姓名列出确认；多条候选
  全部列出让用户选
- 未命中 → 在写邮件页收件人选择器搜索，记录候选让用户确认；确认后更新
  contacts.json（verified=true）
- 发件人 h3 的 description 属性含"部门：..."，可作为联系人部门信息来源
  （仍需用户确认后才写入 contacts.json）
- 外部邮箱默认不支持，必须显式确认后才勾"向此人发送外部邮件"

## 校准记录

- 2026-11-09（第 3 次）：**定位"发送无内容"根因并修复**。实测昨日
  E-20261108-02 在发件箱读信页显示"（共 0 字）"——上一版流程直接写编辑器
  iframe innerHTML，UEditor 不会同步隐藏 textarea `TD_HTML_EDITOR_CONTENT`，
  发前核对又只读了 iframe 显示（有字）导致假通过，正文以空值提交。正确
  方法已回填第 3/5 步：写入用
  `UE.getEditor('TD_HTML_EDITOR_CONTENT').setContent(...)`，核对读 textarea
  的 value（已实测 setContent 三处同步：getContent/textarea/iframe）。
  另实测回填：门户进入 OA 路径（首页 → "我的系统" → "OA办公"卡片
  serve-id=860340B10FB5C60304D6C20699208C85、fwdz
  `https://ua.zjipc.cn/casClient/login/oa`，点击后**新标签页** SSO 直达
  OA）；CAS 登录表单字段（username 工号/password/隐私协议勾选/登录按钮，
  登录成功后自动跳回门户）。
- 2026-11-09（第 4 次）：修复后首封真实发送 E-20261109-01 实测通过：
  发件箱读信页显示"（共 44 字）"且正文完整（对比昨日 0 字，修复有效）。
  补充实测：点"立即发送"出现 **beforeunload 确认对话框**（accept 一次后
  正常提交）；发件箱列表结构 `DL.email-list > DD.active > P.mail-list-title`
  （选中行 detailFrame 自动加载读信页，EMAIL_ID 从 iframe src 取）；
  事务提醒勾选字段名实测为 `SMS_REMIND`。

- 2026-11-08（第 2 次，首次真实发送实测）：发送 E-20261108-02 测试邮件
  （收件人：万志平本人）全流程成功。实测并回填：标签式选择器
  （orgAdd）完整结构与被选条目属性、旧 SelectAddr frameset 选择器不可用
  （通讯簿全空、任何查询"无符合条件"）、SUBJECT 字段名、正文 iframe
  innerHTML 写法、提交跳转 submit.php 成功提示（无确认对话框）、发件箱
  "今日 X秒前"核实格式。**尚未实测：附件上传（upload_file）、抄送、批量发送。**
- 2026-11-08（第 1 次）：创建。发送流程基于 oa-tongda.md 已实测的写邮件页
  表单与收件人选择器结构编写（原 normal-work 校准，2026-11-13 并入本 skill）。
