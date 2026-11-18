# 域名邮件转发

使用现成镜像 `mailserver/docker-mailserver:17.0.0`，将 `pea3nut.org` 的来信直接转发到自己的 Gmail 或 QQ 邮箱。服务名为 `mail-forwarder`，已加入原 `docker-compose.yml`；只需维护转发地址和配置，不需要自写程序。它不提供独立收件箱或个人发信账号，在 Gmail / QQ 中回复时默认使用该邮箱自己的地址。

以下命令在 Ubuntu 宿主机上以 root 执行，工作目录为 `/root/_pea3nut/pea3nut-hub`。若安装的是 Compose v2，将 `docker-compose` 换成 `docker compose`。

## 部署前提

- 固定公网 IPv4，且云厂商支持将该 IP 的 PTR 设置为 `mail.pea3nut.org`。
- 云安全组与宿主防火墙允许 TCP 25 **入站和出站**；出站 25 被封锁时，需要先向云厂商申请解除，才能直接投递到 Gmail / QQ。
- 宿主机已有 Docker、Compose、Nginx 和 Certbot。TCP 80 可从公网访问，供申请和续期证书使用。

此配置仅使用 IPv4。邮件主机必须指向服务器真实公网 IP，不能指向网站 CDN；不要添加未配置和验证的 AAAA 记录。

## 1. 配置 DNS 地址及 PTR

先在 GoDaddy 为 `pea3nut.org` 添加 `A` 记录：名称 `mail`，值为服务器公网 IPv4，等待解析生效。再由服务器／IP 提供商设置 PTR，使该 IP 反向解析到 `mail.pea3nut.org`。PTR 通常不在 GoDaddy 域名 DNS 页面配置。

```bash
dig +short A mail.pea3nut.org
dig +short -x YOUR_SERVER_IPV4
```

第二条命令中的 `YOUR_SERVER_IPV4` 替换为真实 IP。先保留原有 MX，等证书和服务就绪后再切换。

## 2. 填写真实转发地址

```bash
cd /root/_pea3nut/pea3nut-hub
cp mail/config/postfix-virtual.cf.example mail/config/postfix-virtual.cf
```

编辑 `mail/config/postfix-virtual.cf`，取消需要的规则前面的 `#`，将目标改成自己实际控制的邮箱，例如：

```text
me@pea3nut.org YOUR_REAL_ADDRESS@gmail.com
hello@pea3nut.org YOUR_REAL_ADDRESS@qq.com
```

若希望整个域名的任意地址都转给同一个邮箱，可改用 catch-all：

```text
@pea3nut.org YOUR_REAL_ADDRESS@gmail.com
```

务必替换示例地址；目标不要再转回 `pea3nut.org`，以免产生循环。catch-all 也会收下拼错的地址和更多垃圾邮件。通用 Postfix 设置已放在 `mail/config/postfix-main.cf`，通常不需要修改。

## 3. 申请邮件证书并启动

Nginx 仅提供 `mail.pea3nut.org` 的 HTTP 证书验证路径，配置已加入 `vhost.conf`。SMTP 直接进入容器的 TCP 25，不经过 Nginx；也无需为邮件增加 HTTPS 反向代理。

```bash
mkdir -p /var/www/letsencrypt
nginx -t && systemctl reload nginx
certbot certonly --webroot -w /var/www/letsencrypt -d mail.pea3nut.org --cert-name mail.pea3nut.org
docker-compose pull mail-forwarder
docker-compose up -d mail-forwarder
docker-compose ps mail-forwarder
docker-compose logs --tail=100 mail-forwarder
```

证书保存在 `/etc/letsencrypt/live/mail.pea3nut.org/`，Compose 将整个 `/etc/letsencrypt` 只读挂载给容器，以保留证书符号链接。镜像使用 `SSL_TYPE=letsencrypt`，原生监测证书更新；宿主机继续负责 Certbot 自动续期，无需另装自写 hook。可用 `certbot renew --dry-run` 检查续期。

## 4. 切换 MX 并发布 SRS 的 SPF

确认容器正常运行后，在 GoDaddy 设置以下记录。名称均相对于 `pea3nut.org`：

| 类型 | 名称 | 优先级 | 值 |
| --- | --- | --- | --- |
| A | `mail` | — | 服务器公网 IPv4 |
| MX | `@` | `10` | `mail.pea3nut.org` |
| MX | `srs` | `10` | `mail.pea3nut.org` |
| TXT | `srs` | — | `v=spf1 ip4:YOUR_SERVER_IPV4 -all` |

将 SPF 中的 `YOUR_SERVER_IPV4` 替换为真实 IP。只修改 `srs` 子域的 SPF，不覆盖根域已有的 SPF，也不要在同一个名称下发布多条 `v=spf1` 记录。`srs` 的 MX 用于接收转发邮件的退信。

若已有其他邮箱供应商的 MX，先确认旧邮箱和地址的处理安排，再替换根域的旧 MX。不要把不同供应商的 MX 混合当作“双份接收”。DNS 缓存更新期间，旧系统仍可能收到来信，应保留并检查旧服务直至旧记录的 TTL 过期。

用另一个邮箱向 `me@pea3nut.org` 发信，确认目标收件箱或垃圾箱中收到邮件。不要只用目标 Gmail 向自己的转发地址测试，以免重复邮件处理影响判断；在 Gmail“显示原始邮件”中检查认证结果。

## 日常维护

修改 `postfix-virtual.cf` 后，镜像会监测变化并更新规则，等待几秒后用新邮件验证；必要时执行 `docker-compose restart mail-forwarder`。修改 `postfix-main.cf`、Compose 环境变量或镜像版本后，重新创建该服务：

```bash
docker-compose pull mail-forwarder
docker-compose up -d --force-recreate mail-forwarder
```

上述操作只更新邮件服务。原 `./scripts/refresh-all` 仍会停止全部容器，邮件会短暂停机；`mail/state` 中的队列及 SRS 密钥会保留。不要删除这个目录来处理投递失败，应先检查日志和队列：

```bash
docker-compose logs --tail=100 mail-forwarder
docker-compose exec mail-forwarder postqueue -p
```

本配置启用 SMTP-only 和 SRS，保留原邮件的 DKIM 签名，限制连接／发信速率，不做内容垃圾过滤。SRS 让转发服务器通过自身域的 SPF，但不能单独解决原发件人域的 DMARC 对齐。上游 DKIM、服务器 IP 信誉和收件方策略都可能影响投递；本地容器验证不代表真实 Gmail 已接受邮件。

## 备份

`mail/state` 包含待投递邮件和 SRS 密钥，`mail/config` 包含真实转发地址，`mail/logs` 保存日志。先停止服务，再以 root 保留权限归档，完成后启动：

```bash
install -d -m 700 /root/_pea3nut/pea3nut-hub-backup
docker-compose stop mail-forwarder
tar --numeric-owner -czpf /root/_pea3nut/pea3nut-hub-backup/mail-$(date +%Y%m%d-%H%M%S).tar.gz mail/config mail/state mail/logs
docker-compose up -d mail-forwarder
```

归档含邮件内容和密钥，只允许可信管理员访问。宿主机 `/etc/letsencrypt` 需单独保护并备份；现有全仓库备份脚本不会先停止邮件服务，不能代替此流程。恢复时保持服务停止并保留文件所有者与权限；迁往新服务器还需更新 A、PTR 及 SRS 的 SPF。

参考：[Docker Mailserver 配置说明](https://github.com/docker-mailserver/docker-mailserver/blob/v17.0.0/docs/content/config/environment.md)、[证书管理](https://docker-mailserver.github.io/docker-mailserver/latest/config/security/ssl/)、[Google 转发邮件建议](https://support.google.com/mail/answer/175365?hl=en)。
