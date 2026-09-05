# Shop Agent Contract

The agent is a small service on your network (Raspberry Pi or mini-PC) that drives the Bambu
printers. It is **not built yet** — phase 3. This document fixes the API now so that phase 0–2
code doesn't have to change when it lands.

## Security model

**The agent makes all connections outbound.** The cloud app never dials into your house: no port
forwarding, no dynamic DNS, no printer exposed to the internet. The agent authenticates with a
long-lived agent token (`AGENT_TOKEN`, one per agent, revocable from the admin UI).

## Endpoints (cloud side, all under `/api/agent`)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/heartbeat` | Agent reports printer states; response carries any pending commands |
| `POST` | `/jobs/claim` | Atomically claim the next `approved` job for a named printer |
| `GET` | `/jobs/:id/artifact` | Signed URL for the sliced `.3mf` |
| `POST` | `/jobs/:id/progress` | Progress %, layer, temps, ETA |
| `POST` | `/jobs/:id/complete` | Terminal state: `succeeded` / `failed` + reason |
| `POST` | `/jobs/:id/snapshot` | Webcam still, stored against the order |

## Claim payload

```jsonc
{
  "printer": "x1c-01",
  "capabilities": {
    "build_volume_mm": [256, 256, 256],
    "enclosed": true,
    "hardened_nozzle": true,
    "nozzle_mm": 0.4,
    "ams_slots": [
      { "slot": 1, "material": "petg",      "colour": "black", "grams_remaining": 780 },
      { "slot": 2, "material": "pla_tough", "colour": "grey",  "grams_remaining": 210 }
    ]
  }
}
```

The server only hands over a job whose material matches a loaded AMS slot with enough filament.
That check is the thing that stops a job printing in the wrong material — it belongs on the
server, where the order data is, not in the agent.

## Bambu transport notes

- **LAN mode**: MQTT over TLS on `8883`, username `bblp`, password = the printer's access code.
  Report topic `device/<serial>/report`, command topic `device/<serial>/request`.
- File upload over **implicit FTPS on 990** into `/cache/`, then a `project_file` print command
  referencing it.
- Self-signed printer certificate — verification is pinned to the printer cert, not disabled.
- Firmware updates are the main breakage risk; keep the transport isolated in
  `agent/transports/bambu_lan.py` so a protocol change is one file.

## Failure handling

- Printer unreachable → job stays `approved`, agent retries with backoff, operator alerted after
  a threshold. Jobs are never lost to a flaky network.
- Print failure reported → order moves to `reprint_pending` and a replacement job is queued at
  the front, with the customer notified before they have to ask.
- Claim is idempotent: an agent restarting mid-job re-attaches by job id rather than double-printing.
