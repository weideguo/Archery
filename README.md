archery的修改版本

这是2021.06-2022.03在某公司的分支版本，相对与主版本，多了pma登陆，企业微信通知时多了操作人信息，对查询可以设置限制的主机。


发布
------------
构建基础镜像
``` shell
# 构建基础镜像 因为这两个很少改变，所以可以预先构建，如果python中引入新模块，则重新构建
## 启动容器 手动安装依赖项 
docker run -it archery-base:1.3 /bin/bash

## 复制文件到容器
docker cp requirements.txt <container-id>:/etc

## 进入容器运行
source /opt/venv4archery/bin/activate
yum -y install nginx 
pip3 install -r /etc/requirements.txt 

## 提交容器成基础镜像
docker commit <container-id> archery-base:1.3
```

发布
``` shell
## 手动构建新镜像 一般不需要手动构建镜像
#docker build -t archery_new:a.b.c -f Dockerfile .

## 使用docker-compose.yml构建镜像并启动容器 重新构建需要修改 compose文件： 服务名 对外映射端口号 .env文件
# docker-compose -f docker-compose.yml build    # 使用自定义配置文件构建镜像
# docker-compose -f docker-compose.yml up -d    # 使用自定义配置文件运行容器，果如没有镜像则先构建
docker-compose up -d
```



调试启动
---------------
``` shell
# 启动容器
docker run -it -v $PWD:/opt/archery -p 9124:9123 --env NGINX_PORT=9123 --network docker-compose_default archery-base:1.3 /bin/bash

# 进入容器然后运行
cd /opt/archery
 
cp /opt/archery/src/docker/nginx.conf /etc/nginx/ \
&& cp /opt/archery/src/docker/supervisord.conf /etc/ 

/usr/sbin/nginx

source /opt/venv4archery/bin/activate

python3 manage.py collectstatic -v0 --noinput

# 启动django_q 可能不需要单独启动，如果共用redis，则django_q多个竞争执行，启动多个也没有影响
supervisord -c /etc/supervisord.conf

nohup python3 manage.py runserver 127.0.0.1:8888 &

```