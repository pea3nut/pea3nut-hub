# pea3nut-hub

花生PeA的全部线上站点！

部分站点编译结果：

- [Pxer 官网](http://pxer.pea3nut.org/)：[<img src="https://api.travis-ci.org/pea3nut/pxer-homepage.svg?branch=master" />](https://github.com/pea3nut/pxer-homepage)
- [Pxer App](https://pxer-app.pea3nut.org/)：[<img src="https://www.travis-ci.org/FoXZilla/Pxer.svg?branch=dev" />](https://github.com/FoXZilla/Pxer)
- [Short Night 官网](http://short-night.pea3nut.org/)：[<img src="https://api.travis-ci.org/FoXZilla/short-night-homepage.svg?branch=master" />](https://github.com/FoXZilla/short-night-homepage)
- [花生PeAの个人资料](http://pea3nut.info/)：[<img src="https://api.travis-ci.org/pea3nut/pea3nut-info.svg?branch=master" />](https://github.com/pea3nut/pea3nut-info)

## 首次部署

确保你在`/root/_pea3nut/pea3nut-hub/`文件夹下

安装所有依赖：

```bash
bash install.bash
```

该脚本会自动安装所有依赖并设置开机启动

补充私密文件夹内容，包括：
- 博客源码：`blog/mysql-data/*`
- 博客源码：`blog/wordpress/*`
- Pxer服务器SSL证书：`pxer/ssl/pxer-app.pea3nut.org.pem`、`pxer/ssl/pxer-app.pea3nut.org.key`

执行`/etc/rc.local`中的最后一行，来启动整个服务

**确保服务都启动好后**，设置博客的根URL：

```bash
docker exec pea3nut-blog /set-url "http://blog.pea3nut.com"
```

修改域名解析，包含：
- pea3nut.blog
- blog.pea3nut.org
- short-night.pea3nut.org
- pxer.pea3nut.org
- pxer-app.pea3nut.org
- pea3nut.info
- aoning.wang

别忘了一一测试哦~
