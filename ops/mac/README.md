# ops/mac: the Mac's side of the routine host

Two launchd agents, installed by the user from the Mac's checkout once the droplet runs the
routines (`docs/OPS.md`, cut-over). The `pickandroll@hts-digital-ocean` login's key must
work without a prompt (no passphrase, or `UseKeychain yes` in `~/.ssh/config`): launchd has
no agent to ask.

**The tunnel**: localhost:8000 on the Mac becomes the droplet's API, so the dashboard
(`npm run dev` in `web/`, unchanged) and the extension keep their address. Stop the Mac's own
API first (the port).

```bash
cp ops/mac/com.pickandroll.tunnel.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.pickandroll.tunnel.plist && sleep 2 && curl -s http://127.0.0.1:8000/seasons | head -c 200
```

**The nightly copy** (03:30, droplet to Mac, the rollback copy; it adds and updates, never
deletes, so the Mac's own folders stay): write the settings, then load the agent. Nothing is
copied until `rsync.env` exists.

```bash
mkdir -p ~/.config/pickandroll && printf 'DROPLET=pickandroll@hts-digital-ocean\nREMOTE_DATA=pickandroll/data\nLOCAL_DATA=%s/code/pickandroll/data\n' "$HOME" > ~/.config/pickandroll/rsync.env && sed "s|__HOME__|$HOME|g" ops/mac/com.pickandroll.rsync.plist > ~/Library/LaunchAgents/com.pickandroll.rsync.plist && launchctl load ~/Library/LaunchAgents/com.pickandroll.rsync.plist
```

A copy by hand, any time: `bash ops/mac/rsync-from-droplet.sh` (the log is
`~/.config/pickandroll/rsync.log`).

**The re-sign-in** (`docs/OPS.md` §3): once, `mkdir -p ~/.config/pickandroll && echo
pickandroll@hts-digital-ocean > ~/.config/pickandroll/droplet`; then, whenever the 04:50
`signin` check fails, `bash ops/mac/signin.sh` runs the droplet's sign-in browser in a tmux
session, opens its two DevTools windows in Chrome and prints the routine's result.

**Remove** (rollback): `launchctl unload ~/Library/LaunchAgents/com.pickandroll.tunnel.plist`
frees the port for the Mac's API; the same for the rsync agent, and delete `rsync.env` so a
stray run copies nothing.
