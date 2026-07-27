# Setup Guide

**Note**: Throughout this guide I will use values enclosed in angle brackets such as `<hostname>`, as placeholders.
Replace them with your own values and remove the angle brackets.

In this guide I place all application files in the /opt/thephish-stack directory.
If you choose a different location, you have to adjust the paths accordingly.

## Table of Contents

## Hardware Requirements

Cortex and TheHive are very resource intensive.
Depending on your workload you may have to adjust the system resources.

My Recommendation for starters:
* 8 vCPU
* 32GB RAM

## Prerequisites

* Fresh linux install (Preferably Debian 13)
* User with sudo permissions (Working as root is also possible, but it can cause problems with Elasticsearch)
* Docker & Docker compose installed and running (https://docs.docker.com/engine/install/debian/)
* git installed

## Install TheHive, Cortex, and MISP

### Disclaimer

This is a simplified installation guide.
It is fine for most regular users and smaller deployments, if you rely on this install in your production environments you should probably take a look at the official documentations and config options.

### Install Natively

This guide only covers the installation using Docker.

If you want to install natively you have to follow the official documentation:
* [TheHive Install](https://docs.strangebee.com/thehive/installation/installation-guide-linux-standalone-server)
* [Cortex Install](https://docs.strangebee.com/cortex/installation-and-configuration/)
* [MISP download](https://www.misp-project.org/download/)

Once you finished the installation and verified the services are working, you can proceed to the [configuration section](#configure-services-for-thephish) of this guide.

### Install using Docker (Recommended)

First make directory for the applications

```bash
sudo mkdir -p /opt/thephish-stack/cortex /opt/thephish-stack/thehive /opt/thephish-stack/misp
sudo chown $USER:$(id -gn) /opt/thephish-stack -R
cd /opt/thephish-stack
```

Now clone the official git repos and place the files in the directories

```bash
git clone https://github.com/MISP/misp-docker.git misp

git clone https://github.com/StrangeBeeCorp/docker.git strangebee-docker
mv ./strangebee-docker/prod1-cortex ./cortex
mv ./strangebee-docker/prod1-thehive ./thehive
mv ./strangebee-docker/versions.env ./versions.env
```

Initialize TheHive and Cortex .env files. Since we're deploying a reverse proxy on the host later, we disable the included nginx and expose Cortex to the host.

```bash
cd cortex
bash ./scripts/init.sh
sed -i '/^  nginx:$/a\    profiles: ["disabled"]' docker-compose.yml
sed -i 's/# ports:/ports:/' docker-compose.yml
sed -i "s/#   - '0.0.0.0:9001:9001'/  - '127.0.0.1:9001:9001'/" docker-compose.yml
docker compose config >/dev/null
cd ..

cd thehive
bash ./scripts/init.sh
sed -i '/^  nginx:$/a\    profiles: ["disabled"]' docker-compose.yml
sed -i 's/# ports:/ports:/' docker-compose.yml
sed -i "s/#   - '0.0.0.0:9000:9000'/  - '127.0.0.1:9000:9000'/" docker-compose.yml
docker compose config >/dev/null
cd ..
```

Now you can delete the strangebee-docker GitHub repository and the version.env file, as theese are only needed for initialization

```bash
rm -rf strangebee-docker versions.env
```

MISP .env configuration

```bash
cd misp
cp template.env .env
chmod 600 .env

# set defaults and generate random secrets
sed -i -E "s|^[[:space:]#]*GPG_PASSPHRASE=.*$|GPG_PASSPHRASE=$(openssl rand -hex 32)|" .env
sed -i -E "s|^[[:space:]#]*ENCRYPTION_KEY=.*$|ENCRYPTION_KEY=$(openssl rand -hex 32)|" .env
sed -i -E "s|^[[:space:]#]*MYSQL_PASSWORD=.*$|MYSQL_PASSWORD=$(openssl rand -hex 32)|" .env
sed -i -E "s|^[[:space:]#]*MYSQL_ROOT_PASSWORD=.*$|MYSQL_ROOT_PASSWORD=$(openssl rand -hex 32)|" .env
sed -i -E "s|^[[:space:]#]*REDIS_PASSWORD=.*$|REDIS_PASSWORD=$(openssl rand -hex 32)|" .env
sed -i -E 's|^[[:space:]#]*DISABLE_PRINTING_PLAINTEXT_CREDENTIALS=.*$|DISABLE_PRINTING_PLAINTEXT_CREDENTIALS=true|' .env
sed -i -E 's|^[[:space:]#]*ENABLE_REDIS_EMPTY_PASSWORD=.*$|ENABLE_REDIS_EMPTY_PASSWORD=false|' .env
sed -i -E 's|^[[:space:]#]*DEBUG=.*$|DEBUG=0|' .env
sed -i -E 's|^[[:space:]#]*MYSQL_USER=.*$|MYSQL_USER=misp|' .env
sed -i -E 's|^[[:space:]#]*MYSQL_DATABASE=.*$|MYSQL_DATABASE=misp|' .env
sed -i -E 's|^[[:space:]#]*ENABLE_DB_SETTINGS=.*$|ENABLE_DB_SETTINGS=true|' .env
sed -i -E 's|^[[:space:]#]*ENABLE_BACKGROUND_UPDATES=.*$|ENABLE_BACKGROUND_UPDATES=false|' .env
sed -i -E 's|^[[:space:]#]*PHP_SESSION_COOKIE_SECURE=.*$|PHP_SESSION_COOKIE_SECURE=true|' .env
sed -i -E 's|^[[:space:]#]*PHP_SESSION_COOKIE_SAMESITE=.*$|PHP_SESSION_COOKIE_SAMESITE=Lax|' .env
sed -i -E 's|^[[:space:]#]*X_FRAME_OPTIONS=.*$|X_FRAME_OPTIONS=SAMEORIGIN|' .env

sed -i -E 's|^[[:space:]#]*NGINX_X_FORWARDED_FOR=.*$|NGINX_X_FORWARDED_FOR=true|' .env
sed -i -E 's|^[[:space:]#]*NGINX_SET_REAL_IP_FROM=.*$|NGINX_SET_REAL_IP_FROM=127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16|' .env
sed -i -E 's|^[[:space:]#]*CORE_HTTP_PORT=.*$|CORE_HTTP_PORT=127.0.0.1:9080|' .env
sed -i -E 's|^[[:space:]#]*CORE_HTTPS_PORT=.*$|CORE_HTTPS_PORT=127.0.0.1:9443|' .env

# adjust these values
sed -i -E "s|^[[:space:]#]*ADMIN_PASSWORD=.*$|ADMIN_PASSWORD=<SecureAdminPassword>|" .env
sed -i -E 's|^[[:space:]#]*ADMIN_EMAIL=.*$|ADMIN_EMAIL=admin@misp.local|' .env
sed -i -E 's|^[[:space:]#]*ADMIN_ORG=.*$|ADMIN_ORG=ADMIN|' .env
sed -i -E 's|^[[:space:]#]*BASE_URL=.*$|BASE_URL=https://misp.example.com|' .env
sed -i -E 's|^[[:space:]#]*TZ=.*$|TZ=Europe/Vienna|' .env

cd ..
```

After we set our config in the .env files we can start the docker compose.

```bash
cd thehive
docker compose up -d

cd ../cortex
docker compose up -d

cd ../misp
docker compose up -d

cd ..
```

### Configure Nginx Reverse Proxy

## Configure Services for ThePhish

### Configure TheHive

#### Request Community License

### Configure Cortex

### Configure MISP

