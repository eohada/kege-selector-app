# Production access and deployment

Production deploy должен выполняться отдельным SSH-ключом deploy-пользователя.
Пароль `root` не используется в CI и не хранится в репозитории.

## One-time server setup

Выполнить один раз через консоль провайдера или текущую root-сессию:

```bash
useradd --create-home --shell /bin/bash boostudy-deploy
install -d -m 700 -o boostudy-deploy -g boostudy-deploy /home/boostudy-deploy/.ssh
cat >> /home/boostudy-deploy/.ssh/authorized_keys
chmod 600 /home/boostudy-deploy/.ssh/authorized_keys
chown boostudy-deploy:boostudy-deploy /home/boostudy-deploy/.ssh/authorized_keys
usermod -aG docker boostudy-deploy
```

The public key is pasted only into `authorized_keys`. Generate its pair locally:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/boostudy_deploy -C boostudy-production-deploy
```

The workflow runs the helper through `sudo -n`, because it updates the
root-owned checkout, Docker resources and Nginx upstream. Grant only the
required deploy commands through `/etc/sudoers.d/boostudy-deploy`:

```text
boostudy-deploy ALL=(root) NOPASSWD: /opt/boostudy/scripts/deploy_blue_green.sh deploy
boostudy-deploy ALL=(root) NOPASSWD: /opt/boostudy/scripts/deploy_blue_green.sh rollback
boostudy-deploy ALL=(root) NOPASSWD: /opt/boostudy/scripts/deploy_blue_green.sh status
```

Do not grant a general `NOPASSWD: ALL` rule.

## GitHub Actions secrets

Configure these repository secrets:

- `HOST`: `72.56.239.25`;
- `USERNAME`: `boostudy-deploy`;
- `SSH_PRIVATE_KEY`: the private key matching `authorized_keys`;
- `SSH_KNOWN_HOSTS`: pinned output of `ssh-keyscan -H -p 22 72.56.239.25`;
- `SSH_PORT`: `22` (optional; the workflow defaults to `22`).

The workflow is manual and serialized. It calls
`scripts/deploy_blue_green.sh deploy`, which fetches `main`, builds the inactive
color, applies migrations, waits for local `/ready`, switches Nginx, and leaves
the previous color available for rollback.

## Release procedure

1. Commit and push the reviewed release to `main`.
2. Run **Deploy to VPS (MANUAL PROD)** from GitHub Actions.
3. Confirm the workflow's `/ready` and `/health` checks.
4. Keep the previous color and image for at least 10–15 minutes.
5. Roll back from the server if required:

```bash
sudo -n /opt/boostudy/scripts/deploy_blue_green.sh rollback
```

Do not run `docker compose down`, direct `web_prod` restarts, force pushes, or
automatic image pruning during the safety window.
