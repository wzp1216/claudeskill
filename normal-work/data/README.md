# normal-work 数据文件说明

本目录存放运行时配置与联系人映射。**`config.json` 与 `contacts.json` 已被 git 忽略**，不会进入 claudeskill 仓库。

## config.json（首次运行生成）

从 `config.example.json` 复制并按需修改。字段：

| 字段 | 说明 |
|---|---|
| `user` | 姓名、工号、部门（用于邮件签名与默认身份） |
| `paths` | 运行时产物绝对路径（计划/草稿/日志/临时目录） |
| `urls` | 门户、FineReport 报表、OA 各页面 URL |
| `limits` | 抓取上限与安全参数（通知条数、邮件封数、收件人数等） |
| `first_run_calibrated` | 首次校准标记，完成门户首次登录与 DOM 记录后改为 true |

## contacts.json（用户维护 + 现场确认）

联系人数组元素字段：

| 字段 | 说明 |
|---|---|
| `name` | 姓名 |
| `dept` | 部门 |
| `oa_user_id` | OA 内部用户 ID（从收件人选择器确认得到） |
| `oa_username` | OA 用户名/工号 |
| `email` | 外部邮箱（通达 OA 内部邮件通常不需要，默认留空） |
| `verified` | 是否经用户人工确认过映射，**true 才可用于自动填充收件人** |
| `last_verified_at` | 最近一次确认日期 |
| `note` | 备注（如职务、常用提醒事项） |

维护方式：
1. Claude 在 OA 收件人选择器按姓名/工号搜索到候选后，展示给用户确认，确认后才写入或更新该条目（verified=true）。
2. 用户也可以手动编辑此文件，但注意保持 JSON 格式合法。
3. 同名同姓多条记录时保留全部候选，靠 `dept` 区分，发送前必须让用户选择。
