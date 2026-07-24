# CI/CD & Deployment

The pipeline lives in [ci-cd.yml](workflows/ci-cd.yml). This doc is the one-time
setup to make it work.

## What the pipeline does

```
push / PR ──▶ backend-test (pytest)   ┐
              frontend-test (lint,     │  both must pass
                             vitest,   │
                             build)    ┘
                                       │  (only on push to main)
                                       ▼
                              build-and-push ──▶ GHCR
                              (backend + frontend images,
                               tagged :latest and :<sha>)
                                       │
                                       ▼
                                    deploy
                              (SSH to EC2 → pull images → restart)
```

- **On a pull request:** only the two test jobs run. Nothing is built or deployed.
- **On a push to `main`:** tests run, then images are built on GitHub's runners
  (not on the EC2 box) and pushed to GHCR, then the EC2 pulls and restarts.

Building on the runner instead of the t3.small is the main production win — the
2 GB box no longer competes with Weaviate for RAM during a build, and every
deploy is an immutable, versioned image you can roll back to.

## One-time GitHub setup

### 1. Secrets (Settings → Secrets and variables → Actions → **Secrets**)

| Secret | Value |
|---|---|
| `EC2_HOST` | Public IP of the EC2 box (e.g. `13.63.45.172`) |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | The **full contents** of your `bucketlistt-key.pem` private key |

`GITHUB_TOKEN` is provided automatically — no need to create it. It's what both
the runner and the EC2 use to push/pull the private GHCR images.

### 2. Variable (Settings → Secrets and variables → Actions → **Variables**)

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | `http://13.63.45.172:8000` |

This is baked into the frontend bundle at build time. It's a *variable*, not a
secret, because it's a public URL that ships in the JS anyway.

### 3. (Optional) Approval gate

Settings → Environments → **production** → add yourself as a *Required reviewer*.
The `deploy` job will then pause for a manual click before every prod deploy.

## One-time EC2 setup

The EC2 currently builds from source with `docker-compose.yml`. Switch it to pull
pre-built images from `docker-compose.prod.yml` **once**:

```bash
cd ~/aichatbot
git pull
docker compose down            # stop the build-based stack (keeps the volume)
echo "<GITHUB_PAT>" | docker login ghcr.io -u darsh-del --password-stdin
docker compose -f docker-compose.prod.yml up -d
```

For that first manual login, create a GitHub Personal Access Token (classic) with
`read:packages` scope. After that, CI logs in on every deploy using the ephemeral
`GITHUB_TOKEN`, so you don't need the PAT again.

The Weaviate data volume (`aichatbot_weaviate_data`) is shared between the dev and
prod compose files, so your knowledge base survives the switch. No re-upsert needed.

## Rolling back

Every build is tagged with its commit SHA. To roll back, edit the image tags in
`docker-compose.prod.yml` from `:latest` to the known-good `:<sha>`, then on the box:

```bash
docker compose -f docker-compose.prod.yml up -d
```

Or just revert the bad commit on `main` — the pipeline will build and deploy the
reverted state automatically.

## Making a code change from now on

You no longer SSH in to deploy. Just:

```bash
git add -A && git commit -m "..." && git push
```

Tests run, images build, EC2 updates itself. Watch progress in the repo's
**Actions** tab.
