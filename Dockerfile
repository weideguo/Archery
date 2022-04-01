FROM archery-base:1.3

WORKDIR /opt/archery

ADD ./ /opt/archery/

#archery
RUN cd /opt \
    && source /opt/venv4archery/bin/activate \
    && cp /opt/archery/src/docker/nginx.conf /etc/nginx/ \
    && cp /opt/archery/src/docker/supervisord.conf /etc/ 

#port
EXPOSE 9123

#start service
ENTRYPOINT bash /opt/archery/src/docker/startup.sh && bash
