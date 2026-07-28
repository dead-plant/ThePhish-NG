# Setup Guide

**Note**: Throughout this guide I will use values enclosed in angle brackets such as `<hostname>`, as placeholders.
Replace them with your own values and remove the angle brackets.

This guide places all application files in `/opt/thephish-stack`.
If you choose a different location, adjust the paths accordingly.

## Table of Contents

## Hardware Requirements

Cortex and TheHive are very resource intensive.
Depending on your workload you may have to adjust the system resources.

Recommended starting point:

* 8 vCPU
* 32 GB RAM

## Prerequisites

* Fresh Linux installation (preferably Debian 13)
* User with sudo privileges
* Docker Engine 25 or newer and Docker Compose plugin 2.20.2 or newer, installed and running
* Current user can run Docker without `sudo`
* `git`, `jq`, and `openssl`

Check the Docker installation before continuing:

```bash
docker version
docker compose version
docker run hello-world
```

See the official [Docker installation guide](https://docs.docker.com/engine/install/debian/) and [Linux post-installation steps](https://docs.docker.com/engine/install/linux-postinstall/).

## Disclaimer

This is a simplified installation guide for most users and smaller deployments.
For production environments, also review the official documentation.

## Install TheHive, Cortex, and MISP

This guide only covers the installation using Docker.

For a native installation, follow the official documentation:

* [TheHive Install](https://docs.strangebee.com/thehive/installation/installation-guide-linux-standalone-server)
* [Cortex Install](https://docs.strangebee.com/cortex/installation-and-configuration/)
* [MISP download](https://www.misp-project.org/download/)

After installing and verifying the services, continue to [Secure the Initial Administrator Accounts](#secure-the-initial-administrator-accounts).

### Install Using Docker (Recommended)

Create the application directory:

```bash
sudo mkdir -p /opt/thephish-stack
sudo chown -R "$USER:$(id -gn)" /opt/thephish-stack
cd /opt/thephish-stack
```

Clone the official repositories and move the files into place:

```bash
git clone https://github.com/MISP/misp-docker.git misp

git clone https://github.com/StrangeBeeCorp/docker.git strangebee-docker
git -C misp rev-parse HEAD
git -C strangebee-docker rev-parse HEAD

mv ./strangebee-docker/prod1-cortex ./cortex
mv ./strangebee-docker/prod1-thehive ./thehive
mv ./strangebee-docker/versions.env ./versions.env
```

Initialize the TheHive and Cortex `.env` files. The commands below disable the
included Nginx services and bind the application ports to localhost for the host
reverse proxy. They also remove fixed container names so Docker Compose can keep
the two Elasticsearch services separate.

```bash
cd cortex
bash ./scripts/init.sh
chmod 600 .env
sed -i '/^[[:space:]]*container_name:[[:space:]]*/d' docker-compose.yml
sed -i '/^  nginx:$/a\    profiles: ["disabled"]' docker-compose.yml
sed -i 's/# ports:/ports:/' docker-compose.yml
sed -i -E "s|^(\s*)(#\s)?(\s*)-\s*['\"][^'\"]*9001:9001['\"]\s*$|\1\3- '127.0.0.1:9001:9001'|" docker-compose.yml
docker compose config >/dev/null
cd ..

cd thehive
bash ./scripts/init.sh
chmod 600 .env
sed -i '/^[[:space:]]*container_name:[[:space:]]*/d' docker-compose.yml
sed -i '/^  nginx:$/a\    profiles: ["disabled"]' docker-compose.yml
sed -i 's/# ports:/ports:/' docker-compose.yml
sed -i -E "s|^(\s*)(#\s)?(\s*)-\s*['\"][^'\"]*9000:9000['\"]\s*$|\1\3- '127.0.0.1:9000:9000'|" docker-compose.yml
docker compose config >/dev/null
cd ..
```

The remaining StrangeBee repository files and `versions.env` are no longer
needed after both initialization scripts finish:

```bash
rm -rf -- strangebee-docker
rm -f -- versions.env
```

### Configure the MISP Environment

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

After configuring the `.env` files, start all three Docker Compose stacks.

```bash
cd thehive
docker compose up -d
docker compose ps

cd ../cortex
docker compose up -d
docker compose ps

cd ../misp
docker compose up -d
docker compose ps

cd ..
```

Confirm that every service is running or healthy. Startup can take a few minutes.
If a service fails, run `docker compose logs` from its directory.

### Secure the Initial Administrator Accounts

Secure TheHive and Cortex before exposing them through the reverse proxy.

From your computer, open an SSH tunnel with forwarding to their localhost-only ports:

```bash
ssh -L 9000:127.0.0.1:9000 -L 9001:127.0.0.1:9001 <user>@<server>
```

Then complete these steps:

* Open `http://127.0.0.1:9000` in your browser, sign in to TheHive as `admin@thehive.local`
  with the initial password `secret`, and immediately set a secure password.
* Open `http://127.0.0.1:9001` in your browser, update the Cortex database, and create the first
  super administrator.
* Keep the secure MISP administrator password configured earlier.

Close the SSH tunnel when the initial setup is complete.

## Configure Nginx Reverse Proxy

This section installs and configures Nginx as a TLS-terminating reverse proxy.
If you prefer another reverse proxy, configure it before exposing the services.
I don't recommend running ThePhish-NG without a reverse proxy.

This section assumes the following setup. Adjust the paths and hostnames as needed:

* Server with an IP address reachable by the stack's users
* DNS for `thephish.example.com` and `*.thephish.example.com` pointing to that IP address
* Valid TLS certificate for both `thephish.example.com` and `*.thephish.example.com`
* The certificate chain is at `/etc/letsencrypt/live/thephish.example.com/fullchain.pem` and the key at `/etc/letsencrypt/live/thephish.example.com/privkey.pem`
* Services bound to these ports: ThePhish-NG: `127.0.0.1:8080`, TheHive: `127.0.0.1:9000`, Cortex: `127.0.0.1:9001`, MISP: `127.0.0.1:9443`

### Install Nginx Using the nginx.org Repository

Follow the [official Nginx installation instructions](https://nginx.org/en/linux_packages.html#Debian).

Continue after Nginx is installed and running with its default configuration.

### Global Nginx Configuration

If this is a fresh Nginx installation used only for this application, apply the configuration below. Otherwise, merge these settings into your existing configuration.

Back up the existing `nginx.conf` and replace it with the hardened configuration:

```bash
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak

sudo tee /etc/nginx/nginx.conf >/dev/null <<'EOF'
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

After writing the configuration, run `sudo nginx -t` to check for syntax errors.

### Create Nginx hosts for TheHive, Cortex, and MISP

If you already have one or more of these behind a reverse proxy, you can skip their hosts here.

Replace each `server_name` and certificate path with your values.

TheHive:

```bash
sudo tee /etc/nginx/conf.d/thehive.conf >/dev/null <<'EOF'
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
        
        add_header              Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
        proxy_pass              http://127.0.0.1:9000/;
        proxy_http_version      1.1;
    }
}

EOF
```

Cortex:

```bash
sudo tee /etc/nginx/conf.d/cortex.conf >/dev/null <<'EOF'
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
        
        add_header              Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
        proxy_pass              http://127.0.0.1:9001/;
        proxy_http_version      1.1;
    }
}
EOF
```

MISP:

```bash
sudo tee /etc/nginx/conf.d/misp.conf >/dev/null <<'EOF'
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
        
        add_header              Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
        proxy_pass              https://127.0.0.1:9443/;
        # MISP forces a HTTP -> HTTPS redirect and uses a self-signed certificate.
        proxy_ssl_verify off;
        proxy_http_version      1.1;
    }
}
EOF
```

### Nginx host for ThePhish-NG

Replace the `server_name` and certificate paths with your values.

```bash
sudo tee /etc/nginx/conf.d/thephish-ng.conf >/dev/null <<'EOF'
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
        
        add_header              Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
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

This section assumes TheHive, Cortex, and MISP are reachable and you created admin accounts with secure passwords.

### Configure TheHive

#### Request Community License

Starting with TheHive 5.3, a valid license is required.

New installations include a 14-day Platinum trial. After that you need to request a free community license.
I recommend you request it early because StrangeBee can take some time to review your registration.

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
