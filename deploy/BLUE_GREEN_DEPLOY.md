# Blue-green deployment

The public site must be served only by `web_blue` or `web_green`. Nginx reads
`/etc/nginx/snippets/boostudy-active-upstream.conf`; it must contain one
`proxy_pass` directive targeting port `8001` or `8002`. `web_prod` is a
rollback-only legacy service and must not receive public traffic.

## One-time server bootstrap

After this repository version has been pushed and pulled on the server:

```bash
cd /opt/boostudy && chmod +x scripts/deploy_blue_green.sh && scripts/deploy_blue_green.sh deploy
```

The command builds the inactive colour from the current Git revision, applies
expand-only migrations, checks `/ready` and switches Nginx only after success.

## Regular release

```bash
cd /opt/boostudy && scripts/deploy_blue_green.sh deploy
```

Rollback is equally safe:

```bash
cd /opt/boostudy && scripts/deploy_blue_green.sh rollback
```

Never use `docker compose up -d --build` for the public web service.
