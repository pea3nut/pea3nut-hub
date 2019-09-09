docker-compose pull $1
docker-compose build $1
docker-compose down pxer-homepage
docker-compose --help
docker-compose stop $1
docker-compose rm $1
docker-compose up -d $1
