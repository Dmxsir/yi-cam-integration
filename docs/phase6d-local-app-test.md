# Phase 6D — HA OS Local App test

This procedure validates the packaged YI Home engine on a real Home Assistant OS / Supervisor host before implementing the Integration credential handoff.

## Preconditions

- Phase 6C is complete.
- `PHASE6D_APP_CONTEXT_SMOKE=PASS`.
- `PHASE6D_DOCKER_IMAGE_SMOKE=PASS` on `linux/amd64`.
- The target HA OS machine is `amd64`.
- A Home Assistant Samba or SSH App is available for copying files to `/addons`.

Home Assistant's current Local App development documentation explicitly supports copying an App into a subdirectory of `/addons` on a real HA OS device. For a local build, `config.yaml` must not set `image:`; Supervisor then builds the local Dockerfile.

## 1. Create the transfer bundle

On the development laptop:

```bash
cd ~/Documents/yi-cam-integration-phase3
git pull --ff-only
PYTHON=~/Documents/yi-cam-integration/.venv/bin/python \
  bash tools/phase3_pppp_probe/prepare_phase6d_local_app_bundle.sh
```

Expected final marker:

```text
PHASE6D_LOCAL_APP_BUNDLE=PASS
```

Generated files:

```text
dist/yi_home-local-amd64.tar.gz
dist/yi_home-local-amd64.tar.gz.sha256
```

The archive contains a top-level `yi_home/` directory. Extracting it directly under `/addons` produces:

```text
/addons/yi_home/config.yaml
/addons/yi_home/Dockerfile
/addons/yi_home/run.sh
/addons/yi_home/apparmor.txt
/addons/yi_home/rootfs/...
```

The bundle generator refuses to package known development credentials/state such as `.env.local`, `yi.env`, backend API tokens, runtime policy or capability cache.

## 2. Copy to HA OS

### SSH route

Copy the archive to the HA OS SSH environment, then on HA OS:

```bash
cd /addons
rm -rf yi_home
tar -xzf /path/to/yi_home-local-amd64.tar.gz
ls -l /addons/yi_home/config.yaml
```

### Samba route

Open the Home Assistant `addons` Samba share and copy the **contents of the generated `yi_home` directory** into a folder named `yi_home`.

The final path must be `/addons/yi_home/config.yaml`; avoid an accidental nested `/addons/yi_home/yi_home/config.yaml`.

## 3. Reload Local Apps

In Home Assistant:

1. Open **Settings → Apps**.
2. Open the App repository menu and use the available **Reload / Check for updates** action for Local Apps.
3. Confirm **YI Home** appears as an experimental Local App.
4. Open it and install/build it.

Do not add an `image:` key to `config.yaml`; this test intentionally exercises Supervisor's local Dockerfile build.

## 4. First start — no YI credentials yet

Start YI Home before account credentials exist.

Expected behavior:

- App remains running rather than crashing because `/data/yi.env` is initially empty.
- `/data/backend-api-token` is generated once with mode 0600.
- backend health becomes ready.
- initial YI cloud discovery fails safely and remains pending/retrying.
- no PPPP camera runtime is auto-started.
- managed go2rtc can start without camera producers.
- Supervisor discovery for service `yi_home` is attempted.
- no API token or YI credential is printed in normal logs.

Expected useful log lines include:

```text
Starting YI Home backend...
Published YI Home discovery information to Home Assistant.
YI Home backend is ready.
```

If Supervisor discovery cannot yet be consumed because the custom Integration is not installed, the App may log the safe warning and continue running; that is not an App startup failure.

## 5. Restart persistence proof

Restart the App once before account setup.

Pass conditions:

- App starts again.
- backend health becomes ready again.
- the backend API token file persists rather than being regenerated.
- no camera runtime starts from empty policy.

The token value itself must not be pasted into development notes or chat output. Only report that persistence/permissions passed.

## 6. Failure evidence

If the App fails to build or start, capture:

- Supervisor build log from the first failing Docker step;
- App log from start until failure;
- any AppArmor denial visible in host/audit logs, if available.

Do not disable AppArmor or protected mode preemptively. Adjust permissions only from concrete denial evidence.

Do not paste:

- `/data/backend-api-token` contents;
- `/data/yi.env` contents;
- YI password/tokens;
- UID/DID/InitString/license values.

## Gate

The HA OS bootstrap gate passes when the Local App builds, starts, stays healthy without credentials, and survives one App restart with persistent secret-safe `/data` state.

After this gate, Phase 6D.2 implements authenticated Integration → App YI credential handoff so real account discovery and dual camera streaming can be proven inside HA OS.
