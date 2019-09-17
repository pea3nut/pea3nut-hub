#!/bin/bash


root_path="$(pwd)"


# install

curl https://get.docker.com/ > install-docker.sh
sh install-docker.sh

curl -L "https://github.com/docker/compose/releases/download/1.23.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

apt update
apt-get install -y nginx


# others

ln -s "${root_path}/vhost.conf" /etc/nginx/conf.d/vhost.conf
systemctl restart nginx


# start when power on

if [ ! -f '/etc/systemd/system/rc-local.service' ];then
    ln -s /lib/systemd/system/rc-local.service /etc/systemd/system/rc-local.service
    echo '[Install]' >> /etc/systemd/system/rc-local.service
    echo 'WantedBy=multi-user.target ' >> /etc/systemd/system/rc-local.service
    echo 'Alias=rc-local.service' >> /etc/systemd/system/rc-local.service
fi

if [ ! -f '/etc/rc.local' ];then
    echo '#!/bin/bash' > /etc/rc.local
    chmod +x /etc/rc.local
fi

echo "
$(type -p docker-compose) \
-f ${root_path}/docker-compose.yml \
up \
1>${root_path}/docker.stdout.log \
2>${root_path}/docker.stderr.log \
& \
" >> /etc/rc.local
