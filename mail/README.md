# 自托管域名邮件转发

本服务在自己的服务器上接收 `me@pea3nut.org` 等地址的邮件，通过 Postfix 和 PostSRSd 直接投递到指定的 Gmail、QQ 等邮箱，不经过第三方转发商。它只提供收件转发，没有独立收件箱、IMAP、Webmail 或供个人客户端使用的发信账号；在 Gmail 或 QQ 中回复时，默认仍使用该邮箱自身的地址。

邮件使用独立的 `docker-compose.mail.yml` 和 Compose 项目名 `pea3nut-mail`，请始终通过 `./scripts/mail` 管理。原来的 `./scripts/refresh-all` 不会停止这个项目。下面的服务器命令以 Ubuntu 的 root 用户、仓库根目录 `/root/_pea3nut/pea3nut-hub` 为例。

## 1. 先检查服务器条件

- 使用固定公网 IPv4，云厂商允许设置 PTR 反向解析。
- 云防火墙、安全组、宿主防火墙均允许外部连接服务器 TCP 25，且服务器能向外部邮件服务器的 TCP 25 建立连接。只开放入站端口不够；部分云厂商默认封锁出站 25，需要申请解除。
- 安装 Docker 及 Docker Compose，宿主机已有可用的 Nginx、Certbot Nginx 插件。仓库 `scripts/install` 安装的 Certbot snap 包含该插件，可用 `certbot plugins` 检查。
- TCP 80 可从公网访问，以便下文申请和续期证书。

邮件记录应指向服务器的实际公网 IPv4，不是网站 CDN 的 IP。此实现仅使用 IPv4；未配置和验证 IPv6 时，不要为邮件主机添加 AAAA 记录。

## 2. 先配置主机地址、PTR 和证书

在 GoDaddy 的 `pea3nut.org` DNS 管理中，先添加下表的 A 记录，暂时保留原有 MX：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| A | `mail` | 服务器公网 IPv4 |

向服务器／IP 提供商设置该公网 IPv4 的 PTR 为 `mail.pea3nut.org`。PTR 通常不能在 GoDaddy 域名 DNS 页面设置。确认正向和反向解析一致：

```bash
dig +short A mail.pea3nut.org
dig +short -x <服务器公网IPv4>
```

等 A 记录生效、确认 Nginx 配置有效后，在宿主机签发证书：

```bash
nginx -t
certbot certonly --nginx -d mail.pea3nut.org --cert-name mail.pea3nut.org
```

`certonly` 只申请证书，不需要提前向 `vhost.conf` 添加引用新证书的 HTTPS 块。证书保存在 `/etc/letsencrypt/live/mail.pea3nut.org/`。容器将整个 `/etc/letsencrypt` 只读挂载，以保留 `live` 到 `archive` 的符号链接关系。

## 3. 配置收件规则并启动

```bash
cd /root/_pea3nut/pea3nut-hub
install -d -m 700 mail/config
cp mail/mail.env.example mail/mail.env
cp mail/forwards.example mail/config/forwards
chmod 600 mail/mail.env mail/config/forwards
```

编辑 `mail/mail.env`，本域名的配置示例为：

```dotenv
MAIL_HOSTNAME=mail.pea3nut.org
MAIL_DOMAINS=pea3nut.org
MAIL_SRS_DOMAIN=srs.pea3nut.org
MAIL_TLS_CERT_FILE=/etc/letsencrypt/live/mail.pea3nut.org/fullchain.pem
MAIL_TLS_KEY_FILE=/etc/letsencrypt/live/mail.pea3nut.org/privkey.pem
```

编辑 `mail/config/forwards`，每行左侧为域名收件地址，右侧为实际目标邮箱，使用空白分隔：

```text
me@pea3nut.org your-real-address@gmail.com
hello@pea3nut.org your-real-address@qq.com
both@pea3nut.org your-real-address@gmail.com,your-real-address@qq.com
```

请将示例目标替换成自己实际控制的邮箱。若要接收整个域名的任意地址，可添加一条 catch-all 规则：

```text
@pea3nut.org your-real-address@gmail.com
```

catch-all 也会收下拼错的地址及更多垃圾邮件；只需要 `me@` 时就只配置该地址。目标不要再转回本域名，以免产生转发循环。

当前服务有连接和邮件速率限制，但没有内容型反垃圾邮件引擎，不会自动过滤所有垃圾邮件。转发垃圾邮件也可能影响服务器在目标邮箱服务中的信誉。

准备好证书和配置后运行：

```bash
./scripts/mail build
./scripts/mail check
./scripts/mail up
./scripts/mail status
./scripts/mail logs
```

`check` 使用一次性容器检查配置，不能证明公网端口、DNS 或 Gmail 实际投递已经成功。启动后先从外部机器确认 TCP 25 可连接及 STARTTLS 能提供正确证书，例如：

```bash
openssl s_client -starttls smtp -connect mail.pea3nut.org:25 -servername mail.pea3nut.org
```

## 4. 最后切换 MX 和发布 SPF

确认服务运行后，在 GoDaddy 添加或修改以下记录；名称是相对于 `pea3nut.org` 的主机名：

| 类型 | 名称 | 优先级 | 值 |
| --- | --- | --- | --- |
| MX | `@` | `10` | `mail.pea3nut.org` |
| MX | `srs` | `10` | `mail.pea3nut.org` |
| TXT | `srs` | — | `v=spf1 ip4:<服务器公网IPv4> -all` |

SPF 里的 IPv4 必须替换为真实公网 IP。这里仅为 SRS 子域发布 SPF，避免覆盖根域已有的 SPF；同一个名称也不要发布多条 `v=spf1` 记录。`srs` 的 MX 用于接收重写后的退信地址。

如果已有 GoDaddy、Microsoft 365 或其他邮箱供应商的 MX，先确认旧邮箱需要保留的邮件和地址，再用本服务的根域 MX 替换旧 MX。不要把不同供应商的 MX 混合当作“双份接收”：发送方会按 MX 优先级选择服务器，无法保证都收到。DNS 缓存更新期间，旧系统仍可能收到邮件，应保留并检查旧服务，直至旧记录的 TTL 过期。

用另一个邮箱给 `me@pea3nut.org` 发送一封测试邮件，确认目标邮箱收到原始发件人的邮件，同时检查服务器日志和队列。不要只从目标 Gmail 向自己转发地址测试，以免 Gmail 对重复邮件的处理影响判断。

```bash
./scripts/mail logs
./scripts/mail queue
```

在 Gmail 的“显示原始邮件”中检查 SPF、DKIM 和 DMARC 的结果。SRS 重写 SMTP 信封发件人，使转发服务器可以通过自身域的 SPF；它不改变用户看到的原始 `From`，也不能单独解决原发件人域的 DMARC 对齐。服务应保留原邮件及原 DKIM 签名；上游没有有效 DKIM、服务器 IP 信誉不足或收件方策略都可能造成拒收或进入垃圾箱。实际公网投递需要在部署服务器上验证，本地测试不代表 Gmail 已接受邮件。

## 日常操作与证书续期

| 命令 | 用途 |
| --- | --- |
| `./scripts/mail build` | 构建邮件镜像 |
| `./scripts/mail check` | 在一次性容器中检查配置 |
| `./scripts/mail up` | 构建镜像、检查配置，然后启动或更新邮件服务 |
| `./scripts/mail reload` | 检查并重载运行中服务的规则和证书 |
| `./scripts/mail stop` | 停止邮件服务，保留队列和状态 |
| `./scripts/mail status` | 查看容器状态 |
| `./scripts/mail logs` | 查看邮件日志 |
| `./scripts/mail queue` | 查看等待投递的邮件 |
| `./scripts/mail retry` | 请求重新尝试投递队列中的邮件 |
| `./scripts/mail install-renew-hook` | 以 root 安装 Certbot 续期后重载的 hook |

修改 `mail/config/forwards` 后执行 `./scripts/mail reload`；修改 `mail/mail.env` 后执行 `./scripts/mail up` 重新创建容器。不要删除 `mail/queue` 或 `mail/state` 来“修复”投递失败，应先看日志中的 SMTP 错误和队列状态。

宿主机负责 Certbot 自动续期。服务启动后，以 root 安装续期成功后重载的 hook，并检查续期流程：

```bash
./scripts/mail install-renew-hook
certbot renew --dry-run
```

安装命令生成 `/etc/letsencrypt/renewal-hooks/deploy/pea3nut-mail`，通过项目的绝对路径调用 `./scripts/mail renew`。证书成功续期后，邮件服务运行时会重载证书，已停止则跳过；其他域名证书续期也可能触发一次重载。若移动项目目录，应重新安装 hook。未安装 hook 时，证书实际更新后须手动运行 `./scripts/mail reload`。

## 备份和迁移

`mail/queue` 保存尚未完成投递的邮件，`mail/state` 保存 SRS 密钥等状态；二者都必须持久化。`mail/mail.env`、`mail/config/forwards` 及运行状态不会提交到 Git。

备份应先停止邮件服务，再以 root 保留权限归档，完成后重新启动。短暂停机期间，外部发信服务器通常会稍后重试，但不应将其作为无限期停机的保证。

```bash
install -d -m 700 /root/_pea3nut/pea3nut-hub-backup
./scripts/mail stop
tar --numeric-owner -czpf /root/_pea3nut/pea3nut-hub-backup/mail-$(date +%Y%m%d-%H%M%S).tar.gz mail/queue mail/state mail/config mail/mail.env
./scripts/mail up
```

归档包含邮件内容、真实目标邮箱及 SRS 密钥，只允许可信管理员访问。宿主机 `/etc/letsencrypt` 不在此归档中，需单独保护并备份，或在新服务器重新签发邮件证书。现有 `scripts/backup` 会归档仓库中的这些目录，但没有先停止邮件服务，因此不替代上面的停机备份流程。

迁移时在新服务器停止状态下恢复这些目录并保留文件所有者和权限，尤其要保留 SRS 密钥以处理迁移前生成的退信地址。先确认新 IP 的入站／出站 TCP 25、PTR、证书和服务，再更新 `mail` 的 A 记录及 `srs` 的 SPF，并检查 MX。切换期间不要让新旧服务器同时写同一份队列；旧服务器已有的待投递邮件也需要先完成投递或停机迁移。

## 本地验证

在仓库根目录运行单元测试和容器集成测试：

单元测试需要 Python 3 和 OpenSSL；集成测试还需要 Docker。

```bash
python3 -m unittest discover -s mail/tests -p 'test_*.py'
python3 mail/tests/integration.py
```

容器测试需要可用的 Docker；它验证服务在隔离环境中的行为，不会代替公网 DNS、云端口策略和真实 Gmail 收件检查。

## 官方参考

- [Google：向 Gmail 转发邮件的最佳实践](https://support.google.com/mail/answer/175365?hl=en)
- [Google：Gmail 发信者要求，包括 PTR、TLS 和邮件认证](https://support.google.com/mail/answer/81126?hl=en)
- [Certbot：Nginx 插件、证书目录和续期 hooks](https://eff-certbot.readthedocs.io/en/stable/using.html)
