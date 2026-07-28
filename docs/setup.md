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

## Disclaimer

This is a simplified installation guide.
It is fine for most regular users and smaller deployments, if you rely on this install in your production environments you should probably take a look at the official documentations.

## Install TheHive, Cortex, and MISP

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

Initialize TheHive and Cortex .env files. Since we're deploying a reverse proxy on the host later, we disable the included nginx and expose the Services to the host.

```bash
cd cortex
bash ./scripts/init.sh
sed -i '/^  nginx:$/a\    profiles: ["disabled"]' docker-compose.yml
sed -i 's/# ports:/ports:/' docker-compose.yml
sed -i -E "s|^(\s*)(#\s)?(\s*)-\s*['\"][^'\"]*9001:9001['\"]\s*$|\1\3- '127.0.0.1:9001:9001'|" docker-compose.yml
docker compose config >/dev/null
cd ..

cd thehive
bash ./scripts/init.sh
sed -i '/^  nginx:$/a\    profiles: ["disabled"]' docker-compose.yml
sed -i 's/# ports:/ports:/' docker-compose.yml
sed -i -E "s|^(\s*)(#\s)?(\s*)-\s*['\"][^'\"]*9000:9000['\"]\s*$|\1\3- '127.0.0.1:9000:9000'|" docker-compose.yml
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
sed -i -E 's|^[[:space:]#]*BASE_URL=.*$|BASE_URL=https://misp.thephish.example.com|' .env
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

## Configure Nginx Reverse Proxy

In this section we will install and configure nginx as a TLS terminating reverse proxy. If you do not want to use nginx, i strongly recommend to use a different reverse proxy, as ThePhish-NG does not offer built in TLS.

I will assume you already got the following setup. You may have to adjust the paths and hostnames:

* Server with an IP-Address reachable by users needing to access the stack
* DNS for `thephish.example.com` and `*.thephish.example.com` pointing to that IP-Address
* You got a valid TLS certificate for both `thephish.example.com` and `*.thephish.example.com`
* The certificate chain is at `/etc/letsencrypt/live/thephish.example.com/fullchain.pem` and the key at `/etc/letsencrypt/live/thephish.example.com/privkey.pem`
* Services bound to these ports: ThePhish-NG: 127.0.0.1:8080, TheHive: 127.0.0.1:9000, Cortex: 127.0.0.1:9000, MISP: 127.0.0.1:9443

### Install Nginx using nginx.org repo

Look at the official install documentation: https://nginx.org/en/linux_packages.html#Debian

Once you finished installing and verified nginx is running with a default configuration, continue with the configuration.

### Global Nginx config

If this is a fresh nginx install and you are only using it for this application you can safely apply the configuration below, otherwise, you might want to edit it manually and adjust it further.

Backup existing nginx.conf and replace it with hardened config:

```bash
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak

sudo cat > /etc/nginx/nginx.conf <<'EOF'
# For more information on configuration, see:
#   * Official English Documentation: http://nginx.org/en/docs/
#   * Official Russian Documentation: http://nginx.org/ru/docs/

user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /run/nginx.pid;

# Load dynamic modules. See /usr/share/doc/nginx/README.dynamic.
include /usr/share/nginx/modules/*.conf;

events {
    worker_connections 1024;
}

http {
    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';

    access_log  /var/log/nginx/access.log  main;

    sendfile            on;
    tcp_nopush          on;
    keepalive_timeout   65;
    types_hash_max_size 4096;

    include             /etc/nginx/mime.types;
    default_type        application/octet-stream;

    # Load modular configuration files from the /etc/nginx/conf.d directory.
    # See http://nginx.org/en/docs/ngx_core_module.html#include
    # for more information.
    include /etc/nginx/conf.d/*.conf;
    
    # https://configurator.tlsref.org/#server=nginx&version=1.27.3&config=intermediate&openssl=4.0.1&hsts&guideline=6.0
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;

    # see also ssl_session_ticket_key alternative to stateful session cache
    ssl_session_timeout 1d;
    ssl_session_cache shared:MozSSL:10m;  # about 40000 sessions
    
    # Safe gzip defaults
    gzip on;
    gzip_vary on;
    gzip_comp_level 4;
    gzip_min_length 1024;
    gzip_http_version 1.1;

    gzip_proxied expired no-cache no-store private auth;

    gzip_types text/plain text/css text/xml application/json application/javascript application/xml application/rss+xml image/svg+xml;
}

EOF
```

After you edited the config, you should run `sudo nginx -t` to verify there are no syntax errors in the configuration.

### Create Nginx hosts for TheHive, Cortex, and MISP

If you already have one or more of these behind a reverse proxy, you can skip their hosts here.

Make sure to replace the host in server_name and the certificate paths in all of these configs.

TheHive:

```bash
sudo cat > /etc/nginx/conf.d/thehive.conf <<'EOF'
server {
	listen 443 ssl;
	listen [::]:443 ssl;
	server_name thehive.thephish.example.com;
	http2 on;

	ssl_certificate /etc/letsencrypt/live/thephish.example.com/fullchain.pem;  
	ssl_certificate_key /etc/letsencrypt/live/thephish.example.com/privkey.pem;
	
    proxy_connect_timeout   600;
    proxy_send_timeout      600;
    proxy_read_timeout      600;
    send_timeout            600;
    client_max_body_size    2G;
    proxy_buffering off;
    proxy_request_buffering off;
    client_header_buffer_size 8k;

    location / {
    	proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host  $host;
        
        add_header              Strict-Transport-Security "max-age=31536000; includeSubDomains";
        proxy_pass              http://127.0.0.1:9000/;
        proxy_http_version      1.1;
    }
}

EOF
```

Cortex:

```bash
sudo cat > /etc/nginx/conf.d/cortex.conf <<'EOF'
server {
	listen 443 ssl;
	listen [::]:443 ssl;
	server_name cortex.thephish.example.com;
	http2 on;

	ssl_certificate /etc/letsencrypt/live/thephish.example.com/fullchain.pem;  
	ssl_certificate_key /etc/letsencrypt/live/thephish.example.com/privkey.pem;
	
    proxy_connect_timeout   600;
    proxy_send_timeout      600;
    proxy_read_timeout      600;
    send_timeout            600;
    client_max_body_size    2G;
    proxy_buffering off;
    proxy_request_buffering off;
    client_header_buffer_size 8k;

    location / {
    	proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host  $host;
        
        add_header              Strict-Transport-Security "max-age=31536000; includeSubDomains";
        proxy_pass              http://127.0.0.1:9001/;
        proxy_http_version      1.1;
    }
}
EOF
```

MISP:

```bash
sudo cat > /etc/nginx/conf.d/misp.conf <<'EOF'
server {
	listen 443 ssl;
	listen [::]:443 ssl;
	server_name misp.thephish.example.com;
	http2 on;

	ssl_certificate /etc/letsencrypt/live/thephish.example.com/fullchain.pem;  
	ssl_certificate_key /etc/letsencrypt/live/thephish.example.com/privkey.pem;
	
    proxy_connect_timeout   600;
    proxy_send_timeout      600;
    proxy_read_timeout      600;
    send_timeout            600;
    client_max_body_size    150M;
    proxy_buffering off;
    proxy_request_buffering off;
    client_header_buffer_size 8k;

    location / {
    	proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host  $host;
        
        add_header              Strict-Transport-Security "max-age=31536000; includeSubDomains";
        proxy_pass              https://127.0.0.1:9443/;
        proxy_ssl_verify off;
        proxy_http_version      1.1;
    }
}
EOF
```

### Nginx host for ThePhish-NG

Replace the host in server_name and the certificate paths.

```bash
sudo cat > /etc/nginx/conf.d/thephish-ng.conf <<'EOF'
server {
	listen 443 ssl;
	listen [::]:443 ssl;
	server_name thephish.example.com;
	http2 on;

	ssl_certificate /etc/letsencrypt/live/thephish.example.com/fullchain.pem;  
	ssl_certificate_key /etc/letsencrypt/live/thephish.example.com/privkey.pem;
	
    proxy_connect_timeout   600;
    proxy_send_timeout      600;
    proxy_read_timeout      600;
    send_timeout            600;
    client_max_body_size    150M;
    proxy_buffering off;
    proxy_request_buffering off;
    client_header_buffer_size 8k;

    location / {
    	proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host  $host;
        
        add_header              Strict-Transport-Security "max-age=31536000; includeSubDomains";
        proxy_pass              http://127.0.0.1:8080/;
        proxy_http_version      1.1;
    }
}
EOF
```

### Verify config and restart Nginx

```bash
sudo nginx -t
sudo systemctl restart nginx
```

## Configure Services for ThePhish-NG

This section assumes that the TheHive, Cortex and MISP webapps are reachable via their domains and that you created a default admin user with a secure password.

### Configure TheHive

#### Request Community License

Since TheHive version 5.3 you need to have a valid license. You get a 14-day Platinum trial license, and afterward you can request a free community license. I recommend you request the free license right away as the request will be reviewed by the StrangeBee team before you can use it.

You can find a detailed tutorial on how to request and activate such a license on the StrangeBee website:

* Request a Community License: https://docs.strangebee.com/thehive/installation/licenses/request-a-community-license/
* Activate or Update a License: https://docs.strangebee.com/thehive/installation/licenses/license/

#### Configure Cortex and MISP connection

TODO

### Configure Cortex

TODO

### Configure MISP

TODO

## Deploy ThePhish-NG

### Deploy using docker compose

TODO

### Deploy natively

TODO
