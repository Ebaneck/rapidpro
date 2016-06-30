FROM mdillon/postgis:9.4
MAINTAINER James Oloo Onyango <jamesony@thoughtworks.com>

## install and configure supervisor, postgres wget, curl, build essential, pip and ssh
# RUN export DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y openssh-server tar supervisor wget build-essential python python-dev curl postgresql postgresql-contrib libpq-dev python-pip git
RUN mkdir -p /var/lock/apache2 /var/run/apache2 /var/run/sshd /var/log/supervisor
COPY supervisor/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN echo "root:password" | chpasswd  # need a password for ssh
RUN sed -i 's/PermitRootLogin without-password/PermitRootLogin yes/' /etc/ssh/sshd_config

# SSH login fix. Otherwise user is kicked off after login
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd

# Install redis
RUN wget http://download.redis.io/redis-stable.tar.gz
RUN tar xvzf redis-stable.tar.gz
RUN cd redis-stable && make

# Install nodejs and npm
ENV NODE_VERSION 0.12.2
ENV NPM_VERSION 1.3.11

RUN curl -SLO "http://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.gz" \
    && tar -xzf "node-v$NODE_VERSION-linux-x64.tar.gz" -C /usr/local --strip-components=1 \
    && npm install -g npm \
    && npm install -g grunt-cli \
    && npm cache clear

RUN npm install -g less
RUN npm install -g coffee-script

# Create postgres users
RUN /usr/bin/pg_createcluster 9.4 main --start

USER postgres
RUN service postgresql start && psql --command "create database temba;" \
    && psql temba --command "create extension postgis; create extension postgis_topology; create extension hstore;"

USER root

# Add the code to the docker image and setup dependencies
ADD . /home/app/rapidpro
RUN cd /home/app/rapidpro \
    && cp temba/settings.py.dev temba/settings.py \
    && pip install virtualenv \
    && virtualenv env \
    && apt-get install -y libncurses5-dev \
    && pip install -r pip-freeze.txt

RUN cd /home/app/rapidpro \
    && python manage.py syncdb

# Setup the virtualenv and install the files
EXPOSE 22 8000
CMD ["/usr/bin/supervisord"]
