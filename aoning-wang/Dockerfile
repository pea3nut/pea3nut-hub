FROM nginx
MAINTAINER pea3nut "626954412@qq.com"

COPY ./index.html /usr/share/nginx/html/index.html
COPY ./static /usr/share/nginx/html/static

EXPOSE 80

ENTRYPOINT ["nginx","-g","daemon off;"]
