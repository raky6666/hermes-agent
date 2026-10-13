# Isolated Hermes deployment on macOS

This deployment keeps Hermes state in a dedicated Docker volume. It runs as UID
10001, drops all Linux capabilities, blocks privilege elevation, and uses a
read-only root filesystem. Chromium runs inside the same container. No Mac home
directory, documents, browser profile, SSH agent, device, or Docker socket is
mounted. The only host file mounted is a dedicated read-only credentials file.

This is a practical boundary, not absolute isolation. Docker Desktop runs a
Linux VM and still needs host access for its own operation. Containers share
that VM's kernel. A runtime flaw, Docker administrator, or compromised host can
break the boundary. Hermes can read its own credentials and send data through
its internet connection. Do not add your wife's accounts or files. Use a separate
macOS user for this installation. For a stronger boundary, use a separate VM or
device with no personal files and enforced network rules.

## 1. Install Docker Desktop

Open **Apple menu → About This Mac**. Check the Chip or Processor field.
Download the matching [Docker Desktop installer](https://docs.docker.com/desktop/setup/install/mac-install/).
Choose Apple silicon for an M-series chip. Choose Intel for an Intel processor.
Check the supported macOS versions and licence terms on that page before installation.

Install Docker Desktop. Start it. Wait until its engine is running.
Use the normal Linux-container engine. Do not enable a TCP Docker API.
Do not add personal folders to Docker file sharing. Remove broad sharing paths
if other applications do not need them. Some Desktop versions need file-sharing
access to the dedicated secret directory below; grant only that directory.
Do not change settings needed by another user's applications without review.

Give Docker enough memory for the 4 GiB container limit plus VM overhead.
The container has a two-CPU limit and a 256-process limit. You can adjust these
in `compose.yaml` after checking the Mac's available resources.

In Terminal, check:

```sh
docker version
docker compose version
```

The Compose file leaves `platform` unset. Builds use the Mac's native Linux
architecture: `linux/arm64` on Apple silicon, `linux/amd64` on Intel. Python uses
`docker/requirements.isolated.txt` with hashes; npm uses `package-lock.json`.
The fork's `uv.lock` is stale and is not used by this image.
The dedicated workflow builds and smoke
tests both architectures with QEMU. A successful emulated test is not a native
Mac test. If a dependency fails on arm64, inspect the build error first. Do not
switch silently to amd64. An explicit amd64 build can use emulation, but is
slower and needs Docker Desktop support. Do not disable security settings to
make it work.

## 2. Get the source

Use a new directory in the dedicated macOS account. Install Git if required
by the macOS prompt. Clone the fork:

```sh
git clone https://github.com/raky6666/hermes-agent.git
cd hermes-agent
git switch isolated-mac-compose
git rev-parse HEAD
```

Use `main` instead once this change is merged. Record the commit ID with each
backup. The build context is this checkout only; it is copied into the image,
not mounted at runtime. Do not put private files in the checkout. `.dockerignore`
excludes environment files, credentials, backups, and local virtual environments.
The original `Dockerfile` remains available for other use cases. This deployment
uses `docker/Dockerfile.isolated` and installs messaging, cron, PTY, and MCP
dependencies. It does not include every optional integration or local voice model.

Builds are repeatable from a recorded commit and locked app dependencies, not
byte-for-byte reproducible: the Debian tag and apt repositories can change.
Keep a known-good image for exact rollback. Update and rebuild on purpose.

## 3. Create dedicated credentials

Create a new Telegram bot with Telegram's official **@BotFather**. Keep its token
private. Use a separate model API key, with a spending limit where supported.
This deployment initially uses OpenRouter. Other providers need an explicit
change to the secret loader and configuration; do not place keys in YAML.

Obtain your numeric Telegram user ID. You can send a private message to your
new bot, then use the local helper below to read `getUpdates`. Do this before
starting Hermes. It prompts for the token without putting it in shell history:

```sh
python3 - <<'PY'
import getpass, json, urllib.request
token = getpass.getpass('New bot token: ')
try:
    with urllib.request.urlopen('https://api.telegram.org/bot' + token + '/getUpdates', timeout=20) as response:
        updates = json.load(response)
    for update in updates.get('result', []):
        message = update.get('message', {})
        user = message.get('from', {})
        print('User ID:', user.get('id'), 'Chat ID:', message.get('chat', {}).get('id'))
except Exception:
    print('Request failed. Check the token and internet connection. No token was printed.')
PY
```

Match the ID to your own test message. For a private chat, its chat ID is normally
your user ID. Only use IDs you verified. Use private chat first; do not add the
bot to groups during initial setup. A public bot username is not authorization.

Create the secret outside the checkout. This command needs Python 3 on the Mac.
If it is absent, install Python 3 from [python.org](https://www.python.org/downloads/macos/).

```sh
mkdir -p "$HOME/hermes-private"
chmod 700 "$HOME/hermes-private"
export HERMES_SECRETS_FILE="$HOME/hermes-private/hermes-credentials.json"
python3 - <<'PY'
import getpass, json, os
from pathlib import Path
os.umask(0o077)
path = Path(os.environ['HERMES_SECRETS_FILE'])
values = {
    'OPENROUTER_API_KEY': getpass.getpass('Dedicated OpenRouter key: '),
    'TELEGRAM_BOT_TOKEN': getpass.getpass('New bot token: '),
    'TELEGRAM_ALLOWED_USERS': input('Your numeric user ID: ').strip(),
}
values['TELEGRAM_HOME_CHANNEL'] = values['TELEGRAM_ALLOWED_USERS']
with path.open('x') as output:
    json.dump(values, output)
print('Created dedicated credentials file.')
PY
```

The file must contain JSON string values. Multiple authorized user IDs can be
comma-separated without spaces. Set the home channel to one verified chat ID,
not a list. This is the destination for optional scheduled notifications.
The creation command refuses to overwrite an existing file.

Export `HERMES_SECRETS_FILE` again in each new shell. You may store its **path**
in your dedicated shell configuration. Do not store the keys there. Do not use
`env_file`, build arguments, shell command arguments, or GitHub Actions secrets
for live runtime credentials in this deployment.

Compose file-based secrets are file mounts, not an encrypted vault. They are not
encrypted at rest by Compose. Use FileVault and a protected account. File
ownership mapping differs between Desktop versions. If the non-root container
cannot read a mode-600 secret, test the dedicated directory's sharing settings.
Do not make the file world-readable, run Hermes as root, or share your full home
directory. Stop and resolve the file-access problem instead.

The loader validates supported keys and numeric IDs. It loads credentials into
the Hermes process environment, without shell evaluation or printing values.
They are absent from Compose's configured environment and image layers. Child
tools still inherit them. Treat the agent and its tools as trusted with these
keys. Keep `/opt/data/.env` empty or comment-only; startup rejects assignments
because Hermes otherwise reloads them with precedence over process settings.
Do not use `hermes setup` or provider login flows for this deployment.

## 4. Validate and build

```sh
docker compose config --quiet
docker compose build
docker compose run --rm --no-deps -T --entrypoint /opt/hermes/.venv/bin/python hermes /opt/hermes/docker/smoke_isolated.py
docker compose run --rm --no-deps -T --entrypoint /opt/hermes/.venv/bin/python hermes /opt/hermes/docker/smoke_isolated.py --verify-persistence
```

The smoke check uses no model or Telegram API. It checks the UID, capabilities,
privilege flag, read-only app directory, writable data, Chromium launch, and
state across separate containers. It does not prove a secure kernel boundary
or working credentials. `agent-browser` may use Chromium with its browser sandbox
disabled; do not treat Chromium's sandbox as an extra isolation guarantee.

Initialize the data volume and set a model available to your API account:

```sh
docker compose run --rm hermes config set model.default anthropic/claude-sonnet-4.6
```

The initial provider is `openrouter`. The model above is a default, not a promise
of current price or account availability. Change the model ID as needed.
`terminal.backend: local` means local **inside the container**, not on the Mac.
The working directory is `/opt/data/workspace`. Files under `/opt/data` persist.
Files in `/tmp`, `/dev/shm`, or the container layer do not. Browser software stays
in `/opt/chromium`; runtime cache is under the dedicated container home. Browser
sessions are not guaranteed to survive restart. Explicitly saved login state
inside `/opt/data` is sensitive and is included in backups.

## 5. Start and use Telegram

```sh
docker compose up -d
docker compose ps
docker compose logs --tail=100 hermes
```

Send `/help` to your bot from the authorized account. Send a small test request.
Verify the reply and model API access. From a second, unauthorized account, check
that the bot does not run the request. Hermes can offer a pairing code to unknown
DM users. A pairing code alone gives no access. **Do not approve pairing codes**
unless you intend to grant access: saved pairing approvals also authorize users,
even if they are absent from `TELEGRAM_ALLOWED_USERS`. Review and revoke pairing
approvals before reusing an old volume or backup (`hermes pairing --help` lists
the supported commands). A fresh volume starts with no approvals.

Use `docker compose run --rm hermes pairing --help` for this CLI command.
Stop the gateway before changing shared configuration or pairing state.
Do not use the same bot token in two running gateways: long polling will conflict.
The service uses Telegram long polling. It needs no webhook, tunnel, router
port forwarding, or published container port.

| Phone control | Included here |
| --- | --- |
| Send tasks and receive replies in Telegram | Yes, when the gateway is running |
| Start a fresh chat session with `/new` | Yes |
| Use commands listed by the current `/help` | Yes; availability can depend on config |
| Receive configured scheduled messages | Yes; home chat is supplied, no jobs are created automatically |
| See a visual agent tree or Jev routing graph | No; separate dashboard work |
| Browse and switch all agent sessions in an iPhone app | No; separate dashboard work |
| Start Docker, wake the Mac, or recover a failed gateway | No; needs a separate host-control channel |

`/stop` controls agent work; it is not a host shutdown command. This is one Hermes
gateway, not the full Muse agent hierarchy. No Jev routing or dashboard is added.

The Mac must stay powered on, awake, and connected. Docker Desktop must run.
Use its supported start-at-login setting if wanted. `unless-stopped` can restart
the container when the engine returns; it cannot start Docker Desktop or log in
to macOS. Prevent sleep through macOS power settings only if appropriate.

## 6. Network and access boundary

The service uses a dedicated bridge network. No ports, host networking, privileged
mode, host PID namespace, devices, SSH forwarding, or Docker socket are enabled.
Docker's default seccomp profile stays enabled. Resource and log limits reduce
accidental host exhaustion. Local persistent logs under `/opt/data/logs` still
need maintenance; Docker log rotation does not rotate those files.

Outbound internet is allowed for Telegram, OpenRouter, DNS, package/API calls,
and browser sites. A bridge network is **not an egress allowlist**. The container
may reach LAN addresses and Docker Desktop's host gateway, including services
exposed by `host.docker.internal`. No personal files are mounted, but a host file
server or API could still expose data through the network. Shut down such services
or block access with an enforced VM/firewall policy. For strict LAN/host denial,
deploy in a separate VM/network with firewall rules that also cover IPv6 and DNS
rebinding. Do not claim this Compose file implements those rules.

Never connect `/browser connect` to a host browser. Do not configure Browserbase,
Camofox, remote CDP, remote terminals, host tools, or an MCP service with host
access. The startup guard checks local terminal and browser config; it is not a
tamper-proof runtime policy. Authorized tools can change writable configuration
and make network requests. Only log into dedicated agent accounts inside the
container browser. Credentials, sessions, memories, attachments, cookies, and
backups belong to this deployment and remain sensitive.

## 7. Shutdown and rotate keys

```sh
docker compose stop
docker compose start
```

`stop` leaves the container and volume. To remove the container and network while
keeping state:

```sh
docker compose down
```

Do not use `down --volumes` or `docker volume prune` for this deployment. These
can delete data. To rotate keys, stop Hermes, edit the dedicated JSON file in a
local editor, keep mode 600, then recreate the service:

```sh
chmod 600 "$HERMES_SECRETS_FILE"
docker compose up -d --force-recreate
```

Revoke the old keys with Telegram/OpenRouter. A simple restart may retain a
file mount to an old inode after an editor replaces the secret file. Recreate
the container to use the current file. Treat logs as private; tool output may
contain sensitive information even though the loader does not print secrets.

## 8. Backup

Stop the gateway for a consistent backup of SQLite, sessions, and configuration.
Store the archive outside the checkout. The helper mounts no backup directory;
it streams the archive to the host shell.

```sh
docker compose stop
umask 077
mkdir -p "$HOME/hermes-backups"
backup="$HOME/hermes-backups/hermes-$(date +%Y%m%d-%H%M%S).tgz"
docker compose run --rm --no-deps -T --entrypoint tar hermes -C /opt/data -czf - . > "$backup"
tar -tzf "$backup" > /dev/null
git rev-parse HEAD > "$backup.commit.txt"
docker image inspect hermes-isolated:local --format '{{.Id}}' > "$backup.image.txt"
docker compose start
```

Check every command's exit status. If export or archive validation fails, keep
the service stopped until the cause is clear. An archive listing alone does not
prove recovery; do the fresh-volume test below. The credentials file is not part
of the volume archive. Keep it separately in an encrypted password manager or
encrypted backup. The archive can include other API tokens, cookies, and personal
messages generated during use. Encrypt it before cloud storage or transfer.
Keep a copy off the Mac. Never upload it to GitHub.

## 9. Recover and test the backup

Use a fresh named volume. Preserve the old volume until recovery is verified.
Use a trusted archive you created; do not restore an untrusted tar file.
Set `backup` to its absolute path. Restore using the same recorded source/image
version where possible. Stop the current gateway first.

```sh
docker compose down
export HERMES_DATA_VOLUME="hermes-isolated-recovery-$(date +%Y%m%d-%H%M%S)"
docker volume inspect "$HERMES_DATA_VOLUME"
```

The last command must report that this volume does not exist. If it exists,
choose another new name. Then restore:

```sh
docker compose run --rm --no-deps -T --entrypoint tar hermes -C /opt/data -xzf - --no-same-owner < "$backup"
docker compose run --rm --no-deps -T --entrypoint /opt/hermes/.venv/bin/python hermes -c 'import sqlite3; from pathlib import Path; paths=list(Path("/opt/data").rglob("*.db")); [(print(str(p), sqlite3.connect("file:"+str(p)+"?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchall())) for p in paths]'
```

Check restore success. Each database should return `ok`. A backup without a
database needs no database check. Review the restored configuration and pairing
approvals. Check remembered data and session files. Then start and test Telegram:

```sh
docker compose up -d
docker compose logs --tail=100 hermes
```

Keep `HERMES_DATA_VOLUME` set to this recovered volume in future shells. Otherwise
Compose returns to `hermes-isolated-data`. To return to the old state, run
`docker compose down`, unset `HERMES_DATA_VOLUME`, and run `docker compose up -d`.
Do not run both copies with the same Telegram bot token.

## 10. Update and rollback

Back up first. Record the current commit. Preserve the working image:

```sh
docker image tag hermes-isolated:local hermes-isolated:previous
```

Fetch and review the desired source revision. Do not update a working checkout
blindly. Build it, run the smoke checks, then recreate the service. Do not perform
Hermes self-updates inside this read-only image. Rebuild instead.
For code rollback, stop the service and restore the previous image tag:

```sh
docker compose down
docker image tag hermes-isolated:previous hermes-isolated:local
docker compose up -d --no-build
```

If the update changed stored data, restore the matching backup to a fresh volume
as described above. Rolling back only the image may not undo a database migration.

## Validation status

Local validation checks Compose parsing, configuration boundaries, startup
validation, and the repository test suite. The added GitHub workflow can build
and test runtime behavior on amd64 and emulated arm64. Check its actual results
before treating either architecture as verified. No live Telegram/model smoke
test is run without credentials. No installation on your Mac is verified by
these files. Complete sections 4 and 5 on the target Mac to verify that setup.

Checks completed when this change was prepared: Compose v2.39.4 parsed the
configuration, rendered configuration checks passed, and all 16 focused tests
passed. The hashed dependency file passed a uv sync dry run. No Docker engine
was available in that environment, so local image builds and runtime smoke
checks were not executed. The full repository test run reported failures and
was stopped by automatic approval review after an unexpected request to
`api.anthropic.com`; the review could not establish the payload or credential
use. It is not recorded as passing. Runtime workflow results are separate.

Sources: [Docker macOS setup](https://docs.docker.com/desktop/setup/install/mac-install/),
[Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/),
and this fork's `gateway/run.py`, `hermes_cli/commands.py`, `tools/browser_tool.py`,
`docker/entrypoint.sh`, and lockfiles.
