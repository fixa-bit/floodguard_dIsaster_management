# FloodGuard production copy

Two copies of the app run side by side:

| | Development | Production |
|---|---|---|
| Folder | `disaster_management` (this repository) | `../floodguard-production` (git worktree on the `production` branch) |
| Open | http://localhost:3000 | http://127.0.0.1:4100 |
| Backend | port 8000, auto-reload | port 8100, no auto-reload |
| Frontend | `npm run dev` (live reload) | a fixed build served by `vite preview` |
| Settings | `.env`, `frontend/.env` | its own `.env`, `frontend/.env` |
| Database, reports | `floodguard.db`, `reports/` | its own copies |
| Python, packages | `.venv`, `frontend/node_modules` | its own copies |

Production never changes while you work. It only moves to a new version when that
version passes the checks below and you confirm you tested it.

## Day to day

Start or stop production (from this repository's folder):

```
powershell -ExecutionPolicy Bypass -File ops\production\start-production.ps1
powershell -ExecutionPolicy Bypass -File ops\production\stop-production.ps1
```

Production keeps running in the background after the start command finishes; logs are in
`floodguard-production\.local-logs`.

One-click: `FloodGuard Production.cmd` on the desktop runs `launch-production.ps1`, which starts
production if it is not already running (or restarts it if only half of it is up) and opens
http://127.0.0.1:4100 in the default browser.

## Promoting a tested version

1. Finish and commit your work in development.
2. Test every feature in `feature-checklist.txt` in development (http://localhost:3000).
3. Run:

```
powershell -ExecutionPolicy Bypass -File ops\production\promote-to-production.ps1
```

The script stops without changing production if the folder has uncommitted changes, the
backend tests fail, the frontend does not type-check or build, or you answer "n" to any
feature. Otherwise it tags the commit `release-YYYY-MM-DD-N`, moves production to it,
updates production's Python or frontend packages if they changed, rebuilds and restarts.

## Going back

```
powershell -ExecutionPolicy Bypass -File ops\production\rollback-production.ps1
powershell -ExecutionPolicy Bypass -File ops\production\rollback-production.ps1 -To release-2026-11-18-1
```

Only the code goes back; production's database, settings and reports are kept.

## Notes

- Releases are git tags (`git tag -l "release-*"`); `floodguard-production\.local-logs\promotions.log`
  records every promotion and rollback.
- Production shares the read-only hydraulic engine binaries in `tools/` through folder links.
- The n8n alarm system (Docker, port 5678) is shared; its workflow settings decide which
  backend receives alarm events.
