# pea3nut-hub

花生Peadar 的全部线上站点！

## 首次部署

确保你在`/root/_pea3nut/pea3nut-hub/`文件夹下，使用 Ubuntu 系统

### 安装依赖

```bash
./scripts/install
```

该脚本会自动安装所有依赖并设置开机启动

### 迁移资源

在旧服务器上使用如下命令打包资源：

```bash
./scripts/package
```

该命令会输出一个 wget 命令和一个地址，在新服务器上执行可下载：

```bash
wget xxx
./script/unpack yyy # yyy 为下载的 tar 包
```

### 启动

直接运行下面命令来下载并拉起所有 Docker 容器：

```bash
./scripts/refresh-all
```

### 导入博客资源

确保 `pea3nut-blog` 容器正在运行，运行如下命令导入博客的 MySQL 数据库

```bash
./scripts/import-blog-data
```

### 修改解析

修改域名解析，域名太多，建议直接

```bash
cat vhost.conf | grep server_name
```

### 增加定期备份脚本

运行

```bash
export VISUAL=vi
crontab -e
```

然后增加

```
0 0 1 * * /root/_pea3nut/pea3nut-hub/scripts/backup
```
