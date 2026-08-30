# Windows Print Agent — WebSocket Print Queue Spec

This document describes the agent-side changes required to consume the unified
print job queue introduced in the Hotel Bell Elite backend.

## Connection

On startup (after register/heartbeat), open a persistent WebSocket:

```
wss://belleliteaccounts.com/ws/print-agent?agentId=<uuid>
Authorization: Bearer <hpa_* token from register>
```

Keep the connection alive with optional `{"type":"ping"}` → `{"type":"pong"}`.

HTTP heartbeat (`POST /api/print-agent/heartbeat`) remains for printer map sync
and as a fallback delivery trigger for queued jobs.

## Inbound message: print_job

```json
{
  "type": "print_job",
  "jobId": "kot-restaurant-42-1",
  "printerRole": "kitchen1",
  "printerId": "Epson TM-T82",
  "documentType": "kot",
  "contentType": "escpos",
  "contentEncoding": "base64",
  "content": "...",
  "copies": 1
}
```

Feed this payload into the **existing local print handler** used by
`POST http://127.0.0.1:4567/print` — no change to Windows spooler integration.

## Outbound message: job_ack

Report lifecycle transitions:

```json
{
  "type": "job_ack",
  "jobId": "kot-restaurant-42-1",
  "status": "PRINTING"
}
```

Allowed statuses: `SENT_TO_AGENT`, `PRINTING`, `PRINTED`, `FAILED`

HTTP fallback (if WS unavailable):

```
POST /api/print-jobs/<jobId>/ack
Authorization: Bearer <agent token>
{"agentId":"<uuid>","status":"PRINTED"}
```

## Idempotency

Maintain a local store (SQLite or in-memory) of processed `jobId` values for
24–48 hours. If the same `jobId` arrives again:

1. ACK `PRINTED` (or last known status)
2. Do **not** send the job to the printer again

## Reconnect behaviour

When the WebSocket reconnects:

1. Server automatically pushes pending jobs for this `agentId`
2. Agent may also call `GET /api/print-jobs/pending?agentId=<uuid>` as backup

## Localhost bridge (migration)

During rollout, keep `POST :4567/print` enabled so browsers on the same PC can
fall back if the queue path fails. Once all clients use the queue, localhost
direct print may be deprecated.

## Status flow

```
CREATED → QUEUED → SENT_TO_AGENT → PRINTING → PRINTED
                                      ↓
                                    FAILED
```

Agent should ACK at least: `PRINTING` → `PRINTED` or `FAILED`.
