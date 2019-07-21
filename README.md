# pea3nut-hub

Pea3nut's server config.

To start:

1\. Copy the file to `./blog/wordpress` and `./blog/mysql-data`

2\. Run the script below:

```bash
docker-compose up -d
docker exec pea3nut-blog /set-url "http://127.0.0.1:8081" # set the url of blog
```

3\. Install the nginx like `apt install nginx` 

4\. Apply the config file `vhost.conf` in nginx like:

```bash
ln -s "$(pwd)/vhost.conf" /etc/nginx/conf.d/vhost.conf
```
