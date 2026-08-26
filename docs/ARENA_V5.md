# Arena Simplification V5

Arena V5 is an additive flow layered on the existing Arena V3/V4 tables and
admin settlement infrastructure. Legacy matches and statuses remain readable;
new matchmaking creates `flow_version = 5` matches directly in `PLAYING`.

## Runtime flow

1. The MiniApp stores the player's eFootball username and joins the persistent
   matchmaking queue.
2. Pairing runs in one database transaction with row locks. No ticket is spent
   while waiting; one ticket per player is recorded when a match is created.
3. The MiniApp opens the bot with an opaque, participant-bound relay token.
4. The bot resolves the user's active match through internal authenticated
   endpoints and relays private Telegram messages directly to the opponent.
5. A result photo is copied to the configured admin/results channel. Only
   Telegram identifiers are stored; the media is not uploaded to application
   storage.
6. Existing admin review settles the score once. V5 permits a draw, updates
   statistics and points, and sends durable result notifications to both users.

## Environment

- `TELEGRAM_BOT_USERNAME`: bot username used by MiniApp deep links.
- `INTERNAL_API_KEY`: shared secret used by the bot's internal API calls.
- `ARENA_ADMIN_CHANNEL_ID`: admin/results channel used by backend metadata and
  the bot (the bot also accepts its existing results-channel fallback).
- `ARENA_V5_SEASON_NAME`: optional displayed season name.
- `ARENA_V5_SEASON_END_AT`: optional ISO-8601 season end; otherwise the end of
  the current UTC week is displayed.

## Deployment order

1. Back up the database and apply Alembic revision `20260826_arena_v5`.
2. Deploy the backend and verify the public and internal V5 health paths.
3. Deploy the bot with matching internal key/channel configuration.
4. Deploy the MiniApp and smoke-test with two real Telegram accounts.

The migration is additive and idempotent so it can coexist with the project's
runtime schema compatibility hook. Do not remove legacy Arena columns or enum
values until production legacy matches have been drained and separately
migrated.
