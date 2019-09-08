docker-compose down
docker-compose build --pull
docker-compose up -d
systemctl restart nginx
