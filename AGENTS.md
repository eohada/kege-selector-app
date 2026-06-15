# BooStudy Project Rules

## Production Deploys

- Always deploy production changes with the blue-green flow, not by restarting `web_prod` directly.
- Use the server entrypoint:

```bash
cd /opt/boostudy
scripts/deploy_blue_green.sh deploy
```

- The deploy must switch traffic only after the inactive web service returns HTTP `200` from `/ready`.
- `/ready` must check PostgreSQL, Redis, migrations, and Socket.IO readiness.
- Database migrations used before traffic switch must be backward-compatible / expand-only.
- Keep the previous web service running after the switch unless the user explicitly asks for cleanup. This keeps rollback fast and gives old Socket.IO connections time to reconnect safely.
- Rollback path:

```bash
cd /opt/boostudy
scripts/deploy_blue_green.sh rollback
```

- Do not prune old images/containers immediately after a release. Leave at least a 10-15 minute safety window; for risky releases, leave the previous color running until manual verification is complete.
- Workspace/user state must live outside the web process. PostgreSQL is the source of truth; Redis is only a fast live snapshot/cache.
