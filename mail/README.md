# 域名邮件转发：Forward Email 免费托管

目标：将 `*@pea3nut.org` 的全部来信转发到 **`qq626954412@gmail.com`**，包括 `me@pea3nut.org` 和任意其他前缀。使用 [Forward Email](https://forwardemail.net/) 的免费托管转发服务，GoDaddy 继续管理域名和权威 DNS，无需迁移 NS。

本仓库只保留可审查的 DNS 参考 [`forward-email.dns`](./forward-email.dns)，不再运行本地邮件容器或邮件专用 Nginx 配置。免费方案用于收件转发，不提供个人发信账号；在 Gmail 回复时默认仍使用 Gmail 地址。

**合并 PR 只是迁移的开始。生产机若仍运行 `pea3nut-mail`，不要先 `git pull`：它绑定了仓库的 `mail/config`，新版本会删除这些配置文件。先按下文迁移邮件，再更新生产代码。**

## DNS 记录

以下为 GoDaddy 中 `pea3nut.org` 根域的配置；参考文件的 TTL 为 1800 秒，可在迁移前提前调低，并等待原 TTL 失效。

| 类型 | 名称 | 优先级 | 值 |
| --- | --- | --- | --- |
| MX | `@` | `0` | `mx1.forwardemail.net` |
| MX | `@` | `0` | `mx2.forwardemail.net` |
| TXT | `@` | — | `forward-email=qq626954412@gmail.com`，部署时优先替换为加密后的等价值 |
| TXT | `@` | — | `v=spf1 a include:spf.forwardemail.net -all`，仅为无既有 SPF 时的示例 |

两条 MX 的优先级都为 **0**。切换时用它们替换旧根域 MX，不能把旧的 `mail.pea3nut.org` 混作备用。网站 A / AAAA / CNAME、其他 TXT 和 GoDaddy NS 均保留。

**同一名称只允许一条 SPF。** 如果根域已有 `v=spf1`，将 `include:spf.forwardemail.net` 合并进原记录，保留仍在使用的发送来源及合适的最终策略，不要另加第二条或直接覆盖。旧 `srs` 子域的 SPF 与根域是不同记录，先按退信过渡需要保留。

### 优先使用免费加密 TXT

在实际部署阶段打开 [官方加密工具](https://forwardemail.net/en/encrypt)，输入 `forward-email=qq626954412@gmail.com`，将返回的完整 `forward-email=<密文>` 写入根域 TXT，替换表中的明文规则。它不需要创建账户、付费或绑定域名。

参考文件保留明文等价规则，便于确认目标地址。实际 DNS 不要同时发布明文和密文，否则目标邮箱仍然公开。加密只隐藏 TXT 中的转发规则，不加密邮件正文；以后修改目标地址时重新生成。

可以在切换 MX 前准备并检查规则 TXT 与 SPF；免费 DNS 转发不需要付费方案的 `forward-email-site-verification` 记录。完整收件验证应在 MX 切换后进行。

## 迁移现有生产部署

以下命令在 Ubuntu 宿主机以 root 执行。除非另有说明，工作目录为 `/root/_pea3nut/pea3nut-hub`。迁移期间保留旧容器、配置、状态目录和证书。

### 1. 保存现状并检查队列

先从 GoDaddy 导出当前 DNS，记下旧 MX、TXT、`mail` / `srs` 相关记录及各自原 TTL。在旧配置仍完整时执行：

```bash
cd /root/_pea3nut/pea3nut-hub
migration_backup="/root/_pea3nut/pea3nut-hub-backup/mail-migration-$(date +%Y%m%d-%H%M%S)"
install -d -m 700 "$migration_backup"
cp -a mail/config "$migration_backup/config-before"
git status --short > "$migration_backup/git-status.txt"
git log -5 --oneline > "$migration_backup/git-history.txt"
docker inspect pea3nut-mail > "$migration_backup/container-before.json"
docker exec pea3nut-mail postqueue -p
```

记录备份目录；后续命令继续在同一 shell 使用 `migration_backup`。初始备份保存配置和部署信息，最终队列的一致性备份要等容器停止后进行。

若队列包含真实未投递邮件，**暂停旧服务清理**，确认邮件已成功投递，或导出、妥善转送并记录处理结果。更改 MX 不会搬走本机已排队的邮件。不要清空队列或删除 `mail/state`；仅明确识别为可丢弃的测试邮件才可按实际安排处理。

### 2. 准备 TXT / SPF，最后切换 MX

在 GoDaddy 准备上述加密转发 TXT 和合并后的 SPF，先核对拼写、目标邮箱和 DNS 实际返回值。保留旧根域 MX，直到新规则准备就绪。

随后将根域 MX 一次替换为表中的两条 Forward Email MX。保留旧容器和绑定目录，处理仍使用缓存旧 MX 的来信；不要立即更新生产代码或删除旧 SRS 记录。

```bash
dig +short MX pea3nut.org @1.1.1.1
dig +short MX pea3nut.org @8.8.8.8
dig +short TXT pea3nut.org @1.1.1.1
dig +short TXT pea3nut.org @8.8.8.8
```

两家解析器都应返回两条优先级 0 的新 MX；TXT 应包含正确的转发规则和唯一的 SPF。密文 TXT 可核对完整值与加密工具输出是否一致。

### 3. 验证 Gmail 收件与过渡窗口

从不同的外部发件域发送带唯一主题的测试邮件，分别投递到 `me@pea3nut.org` 和一个随机前缀地址，确认都进入 `qq626954412@gmail.com` 的收件箱或垃圾箱，并检查 Gmail“显示原始邮件”中的转发路径及认证结果。

至少使用一个不同于目标 Gmail 的发件账户；不要仅从目标邮箱向自己测试。DNS 校验通过、SMTP 收件人被接受，都不能代替实际收到邮件。

确认新链路工作后，等待切换前相关记录的**最大旧 TTL** 经过，并检查旧容器日志与队列，确认缓存旧 MX 的邮件已妥善处理。

**旧 SRS 退信可能比 DNS 缓存更晚到达。** 如果旧服务器实际成功转发过邮件，应根据最后发送时间和退信情况保留 `srs.pea3nut.org` 的 MX、`mail` 的 A、旧 SMTP 服务及 SRS 密钥，直至退信过渡结束。旧配置的 `maximal_queue_lifetime`、`bounce_queue_lifetime` 都是 `5d`，这是本机队列寿命，不是所有外部退信的统一截止时间；仅等待 TTL、仅看到空队列或机械等待五天，都不能直接证明可以清理。

若日志证明旧服务器从未成功外发，记录这一事实；没有生成实际外发邮件的 SRS 返回路径时，无需等待不存在的退信。

### 4. 停止并归档旧邮件服务

只有新链路验证通过、真实队列邮件处理完毕且旧 SRS 过渡结束后，才继续：

```bash
docker exec pea3nut-mail postqueue -p
docker stop pea3nut-mail
tar --numeric-owner -czpf "$migration_backup/mail-before-removal.tar.gz" mail
```

确认归档成功，且停止前后没有新增的真实待处理邮件，再执行 `docker rm pea3nut-mail`。若发现仍有邮件待处理，保留归档并暂停后续清理，先安排恢复处理。

`docker rm` 不加 `-v`，也不删除宿主机的 `mail/state`、日志或备份。归档包含邮件内容、真实邮箱和 SRS 密钥，只允许可信管理员访问。

### 5. 安全更新生产代码

生产机可能有本地提交或未提交修改，先审查状态并保存必要改动。**不要 `reset --hard` 或强制覆盖生产修改。** 新版本已移除邮件服务，合并不会自动处理上述迁移步骤。

```bash
git fetch origin
git status --short
git log --oneline --left-right HEAD...origin/master
git merge origin/master
```

如出现冲突或 Git 阻止合并，停在这里，保留现场并解决差异后再继续。确认新代码已安全合入后：

```bash
nginx -t && systemctl reload nginx
```

本次无需执行全站 `refresh-all`、`docker-compose down` 或 `docker-compose up`。新邮件链路由外部托管，Nginx 只需重载移除旧邮件 ACME 路径的配置，网站容器继续运行。

### 6. 清理遗留证书及无用 DNS

旧 SMTP 已停止且过渡结束后，运行 `certbot certificates` 核对实际证书名称，并确认 Nginx 和其他服务均不再引用该证书。若确认仅用于旧邮件服务，再执行：

```bash
certbot delete --cert-name mail.pea3nut.org
```

如实际 cert-name 不同，应使用核实后的名称。不要直接 `rm` 证书目录，否则可能留下失效的续期任务；移除旧 HTTP 验证路径后也不应继续保留无人使用的 webroot 续期配置。清理旧 `mail` A、`srs` MX / SPF 前，同样确认没有其他用途或在途退信依赖。

## 回退与日常维护

阿里云默认限制出站 TCP 25，当前标准解封条款也不适合自建 MTA 直投收件方 MX。因此恢复旧 Compose / Postfix 配置本身，不能解决旧链路无法向 Gmail 投递的问题。

托管转发异常时，先检查 Forward Email 状态、DNS 和目标 Gmail。需要回退时优先将 MX 与对应规则恢复到**已经验证可用的邮件服务**；不要把被出站封锁的旧服务器当作自动可用的备用 MX。任何回退都要继续保留并处理旧队列。

以后修改目标邮箱，只更新转发 TXT（优先重新加密）；无需部署容器、申请邮件服务器 PTR 或维护邮件专用证书。修改 DNS 后仍应做随机地址和真实收件验证。

## 官方参考

- [Forward Email：免费 DNS 接入、catch-all 和 SPF](https://forwardemail.net/en/faq#how-do-i-get-started-and-set-up-email-forwarding)
- [Forward Email：免费 TXT 加密](https://forwardemail.net/en/encrypt)及[无需认证的加密接口](https://forwardemail.net/en/blog/docs/mcp#authentication)
- [阿里云：出站 TCP 25 限制与解封条件](https://help.aliyun.com/zh/document_detail/56130.html)
- [Certbot：使用 delete 管理证书](https://eff-certbot.readthedocs.io/en/stable/using.html#deleting-certificates)
