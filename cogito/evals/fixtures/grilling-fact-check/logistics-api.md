# ParcelBridge API v3 — Cancellation

Synthetic API reference for conversation evaluation; no live service.

`POST /shipments/{id}/cancel` accepts shipments in `awaiting_pickup` (not yet handed to the carrier). A successful cancellation returns HTTP 200 with `status: cancelled`; cancellation is complete when that response is returned. Requests after carrier handoff return HTTP 409 and leave shipment state unchanged. Other failed requests also leave shipment state unchanged and may be retried manually.
