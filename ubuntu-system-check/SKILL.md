---
name: ubuntu-system-check
description: 检查与维护本地 Ubuntu 系统。当用户要求"检查/体检/维护系统"、"看下系统有没有问题"、"清理/优化 Ubuntu"、"清理垃圾文件"时使用。覆盖系统基础、服务与日志、更新与软件包、硬件与磁盘健康、网络与安全五个方面，并可基于 shell 历史定位清理垃圾文件；先只读检查给出报告，维护动作需用户确认后再执行。
---

# Ubuntu 系统检查与维护

**核心原则：先只读检查，再谨慎维护。** 检查阶段只执行不改变系统状态的命令；任何维护动作（apt upgrade、autoremove、清理日志/内核、重启/禁用服务、改防火墙）必须先列出清单并征得用户确认，禁止擅自执行破坏性或不可逆操作。

## 使用流程

0. **sudo 预授权（开始检查前一次完成）**：直接提示用户输入 sudo 密码。用户输入密码 → 先执行 `echo '<密码>' | sudo -S -v` 缓存凭据（约 15 分钟），之后所有需要 sudo 的命令直接执行，不再逐条询问；用户不输入（跳过/拒绝）→ 跳过全部需要 sudo 的命令，报告中标注"⚠️ 未检查（无 sudo 权限）"。
1. 按下面五类逐项执行**只读**检查命令（不需要 sudo 的优先，需要 sudo 的用第 0 步的凭据执行）。
2. 汇总为报告：每类一个小节，用 `✅`（正常）/ `⚠️`（异常/需关注）/ `❌`（问题）标记，给出关键数值和合理阈值。
3. 报告末尾列出"建议动作"，区分**无需确认的只读建议**与**需用户确认的维护动作**，等用户拍板再执行维护。

## 一、系统基础

```bash
lsb_release -a 2>/dev/null || cat /etc/os-release      # 发行版版本
uname -r                                              # 内核版本
uptime                                                # 运行时长 + 1/5/15 分钟负载
nproc && grep -c ^processor /proc/cpuinfo             # CPU 核数
free -h                                               # 内存/SWAP（关注 available 过低、swap 占用高）
df -hT                                                # 磁盘（关注 / 与 /home 使用率 > 85% ⚠️、> 95% ❌）
```

阈值参考：负载 < 核数×0.7 正常；内存 available < 总量 10% ⚠️；SWAP 持续占用高 ⚠️；根分区 > 85% ⚠️。

## 二、服务与日志

```bash
systemctl --failed                                    # 失败的服务/单元（重点！）
systemctl list-units --type=service --state=running   # 运行中的服务（数量骤减说明有问题）
journalctl -p err -b --no-pager | tail -30            # 本次启动的错误日志
journalctl -p warning -b --no-pager | tail -20        # 本次启动的警告日志
systemd-analyze                                       # 启动总耗时
systemd-analyze blame | head -10                      # 启动最慢的单元
systemctl list-unit-files --state=enabled | head -40  # 开机自启项（检查是否有可疑项）
```

重点排查：`systemctl --failed` 非空、journal 里反复出现的同一错误、自启项里有不认识的服务。

## 三、更新与软件包

```bash
sudo apt-get update -qq 2>/dev/null && apt list --upgradable 2>/dev/null   # 可升级包（先 update 再列，update 需 sudo）
apt list --upgradable 2>/dev/null | grep -i security || true          # 其中安全更新
dpkg --audit                                           # 损坏的软件包状态
sudo apt-get check                                      # 依赖一致性（需 dpkg 锁，需 sudo）
dpkg -l 'linux-image-*' | grep ^ii | awk '{print $2}'  # 已安装内核（与 uname -r 对比，旧内核可清理）
apt-get -s autoremove | head -20                       # 模拟 autoremove（-s 只预览，不执行！）
```

注意：`apt-get upgrade` / `autoremove` / 删除旧内核属于**维护动作**，先报告再等确认。长期不更新（可升级包很多且含安全更新）应提示。

## 四、硬件与磁盘健康

```bash
df -hT                                                # 空间（同系统基础）
sudo smartctl -H /dev/sda 2>/dev/null                  # SMART 健康（需 smartmontools，按实际盘符 sda/sdb/nvme0）
sudo smartctl -a /dev/sda 2>/dev/null | grep -E 'Reallocated|Pending|Temperature'  # 关键属性
sensors 2>/dev/null || echo "未安装 lm-sensors"         # CPU/主板温度
upower -i /org/freedesktop/UPower/devices/battery_BAT0 2>/dev/null | grep -E 'state|percentage|time to'  # 电池
sudo dmesg | grep -iE 'error|fail|thermal|i/o' | tail -20   # 硬件相关内核错误
```

阈值参考：SMART 出现 Reallocated/Pending 扇区 ❌；温度长期 > 85°C ⚠️；电池 health < 80% ⚠️。

## 五、网络与安全

```bash
ss -tulpn | grep LISTEN                               # 监听端口（核对每项是否认识）
sudo ufw status verbose 2>/dev/null || systemctl is-active ufw   # 防火墙状态
systemctl status ufw fail2ban ssh --no-pager 2>/dev/null | grep -E 'Active|●'  # 安全相关服务
who && last -n 5                                       # 当前登录与近期登录
sudo lastb -n 10 2>/dev/null || echo "无失败登录记录(或需权限)"   # 失败登录（暴力破解迹象）
sudo sshd -T 2>/dev/null | grep -E 'PermitRootLogin|PasswordAuthentication|Port'  # SSH 配置
find /etc/ssl/certs -name '*.pem' -mtime +365 -print 2>/dev/null | head   # 过期证书线索
```

重点排查：不认识的高端口监听 ❌；ufw inactive 且直接暴露公网 ⚠️；lastb 大量失败记录 ⚠️（考虑 fail2ban）；PermitRootLogin yes ⚠️。

## 六、垃圾文件清理（基于 shell 历史）

**原理**：用户的 `~/.bash_history` / `~/.zsh_history` 记录了下载、解压、编译、误装依赖等操作留下的痕迹。从中提取文件路径，核对磁盘上是否仍残留，定位真正的垃圾文件。

**流程**：

1. **提取线索**：读取历史文件（bash/zsh/fish，先确认存在），用 grep 提取以下模式：
   - 下载：`wget`、`curl -o` / `curl -O`
   - 解压：`tar x*`、`unzip`、`7z x`、`xz -d`
   - 编译/构建：`make`、`cmake`、`ninja`、`go build`、`npm run build`
   - 依赖/环境：`npm install`、`pnpm install`、`pip install`、`git clone`、Homebrew 安装脚本
   - 备份/临时：`cp xxx.bak`、`*.tmp`、`*.pre-update`、`~` 结尾的 vim 备份
2. **存在性校验**：对提取的路径逐一 `test -e`，过滤掉已不存在的路径（历史里的路径多数已删）。
3. **安全过滤**（任一不满足即排除）：
   - 只处理**当前用户主目录**下的路径（含 `/home/linuxbrew` 等历史安装残留），**绝不碰** /usr /etc /var /opt /boot 及其他用户目录
   - 排除 **7 天内修改过**的文件（可能仍在用）
   - 排除当前会话工作目录、正在开发的项目目录（git 仓库根）
   - 排除被进程占用的文件（`lsof` 检查）
   - `node_modules` / `venv` / `.venv` / `.git` / conda / 编译产物目录标记为**高风险项**，必须逐项单独确认
4. **分类输出清单**：路径 + 大小 + 分类（下载残留/解压残留/构建产物/依赖误装/备份文件）+ 清理理由，**列出后等用户确认**，绝不直接删除。
5. **确认后执行**：
   - 默认 `mv` 到 `~/.local/share/ubuntu-maintenance-trash/`（回收站式，可恢复），**不直接 `rm`**
   - 若清理项涉及 PATH 等配置文件（如删除 Homebrew 需同步移除 `.bashrc` 里的 `brew shellenv` 行），给出修改方案，确认后一并处理
   - 完成后提示回收站位置，由用户自行决定是否清空

**命令模板**：

```bash
HIST=~/.bash_history; [ -f ~/.zsh_history ] && HIST="$HIST ~/.zsh_history"
# 提取线索
grep -hE 'wget |curl .*(-o|-O)|tar .*x|unzip |7z x|make |cmake |ninja |go build|npm install|pnpm install|pip.*install|git clone|\.pre-update|\.bak|\.tmp' $HIST 2>/dev/null | tail -60
# 校验存在性（示例）
for p in ~/v2rayN* ~/node_modules ~/package.json /home/linuxbrew; do [ -e "$p" ] && echo "存在: $p ($(du -sh "$p" 2>/dev/null | cut -f1))"; done
# 检查占用
lsof "$path" 2>/dev/null
```

## 维护动作清单（需用户逐项确认后执行）

| 动作 | 命令 | 风险 |
|------|------|------|
| 更新软件 | `sudo apt-get update && sudo apt-get upgrade` | 低-中，建议先备份或选非工作时段 |
| 清理无用依赖 | `sudo apt-get autoremove --purge` | 低 |
| 清理旧内核 | `sudo apt-get purge linux-image-旧版本号` | 中，保留当前内核 |
| 清理日志 | `sudo journalctl --vacuum-time=7d` | 低 |
| 修复损坏包 | `sudo dpkg --configure -a` | 低 |
| 启用防火墙 | `sudo ufw enable`（先 `ufw allow` 必要端口） | 中，可能断连，远程操作需谨慎 |
| 禁用失败服务 | `sudo systemctl disable --now <服务>` | 中 |
| 安装缺失工具 | `sudo apt-get install -y smartmontools lm-sensors htop` | 低 |
| 清理历史垃圾文件 | 按第六节流程（历史定位→校验→清单→确认→移入回收站） | 低-中，默认进回收站可恢复 |

## 安全注意事项

- 检查阶段一律只读；`apt-get -s` 等 `-s/--dry-run` 模拟命令可以放心跑，但**严禁**把模拟命令的 `-s` 去掉后顺手执行。
- 需要 sudo 的命令统一使用第 0 步获取的密码执行（建议先 `echo '<密码>' | sudo -S -v` 缓存凭据，后续命令免密）；密码不回显、不写入文件、不展示在报告中。**维护动作（升级/清理/重启或禁用服务/改防火墙）不因已获得密码而自动执行，仍须逐项确认。**
- 涉及重启服务、禁用服务、改防火墙等可能影响当前会话的操作，必须等用户明确同意。
- 检查结果以报告形式给出，不自动"修复"；用户说"你自己看着办/自动处理"时，也要先列出将执行的动作再动手。
- **基于历史推断的文件清理风险更高**：历史命令 ≠ 用户不需要该文件。删除前必须核对文件真实存在、大小、修改时间，向用户说明"为什么判断它是垃圾"，默认移入回收站而非 rm，绝不清理工作文档（pdf/ppt/docx/xlsx 等办公文件需特别标注，默认跳过）。
