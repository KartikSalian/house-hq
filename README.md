# House HQ 🏠

A shared household management app for flatmates — tracks common shopping items and rotating chores, keeps everyone's turn fair, and flags what needs doing with a colour-coded, notification-style system.

Built for a 4-person shared house in Galway.

## Features

**Shopping**
- Common items grouped by section (Kitchen / Bathroom / Bedroom / Hall)
- Flag an item **Running low** or **Empty**; the next person in the rotation is notified
- **"I bought it"** logs the buyer and the cost, then advances the rotation
- **Propose + vote** to add new items — only people who vote *yes* join that item's rotation, so someone who doesn't use an item is never asked to buy it
- Remove is admin-only

**Chores**
- Adjustable reminder interval per chore (default 2 weeks)
- **"Needs doing now"** button for early triggers (e.g. bin full before the timer), which resets the clock on completion
- Fixed pairs for specific chores (e.g. per-bathroom teams)
- Pair fairness: solo = 1 point, pair = 0.5 each, so a pair must do a chore twice to match one solo turn
- Layered chores (e.g. Hall = brush floor / wipe floor / dining table / teapoy) with per-layer credit

**Accounts**
- Each housemate sets their own PIN on first sign-in; it's required afterwards
- PINs are hashed (PBKDF2); actions are authorised by a session token, and the server derives *who* the actor is from that token — so no one can act as someone else, even via the API
- Stay signed in across refreshes until logout

**Fairness scoreboard**
- Per-person spend and chore-effort points

**Colour code**
- 🟢 Green — nothing for you
- 🟡 Yellow — flagged/due, but it's someone else's turn (passive, in-app only)
- 🔴 Red — your turn (this is what becomes a phone push notification)

## Status

Full-stack app running locally: a **Flask + SQLite backend** persists all data (items, chores, purchases, chore logs, proposals and votes) and serves the front-end. The red alerts are still on-screen stand-ins for real push — that and hosting are the next phase.

## Run

**Windows:** double-click `run.bat`, then open http://localhost:5000

**Any OS (manual):**
```bash
pip install -r requirements.txt
python app.py
```
Then open http://localhost:5000

The database file `house.db` is created automatically on first run and seeded with the initial items and chores. Delete it to reset to a fresh state.

## Architecture

- **Backend** — `app.py`: Flask REST API over SQLite. Rotation, voting resolution and chore-point logic live server-side.
- **Frontend** — `index.html`: single-file vanilla HTML/CSS/JS. Fetches state from `/api/state` and posts actions; the signed-in user is kept in `localStorage`.
- **Data** — `house.db` (SQLite): items, buys, chores, chore_log, proposals.

### API
| Method | Route | Purpose |
|---|---|---|
| GET | `/api/state` | Full app state |
| POST | `/api/login` | Set PIN (first time) / sign in; returns session token |
| POST | `/api/logout` | End the session |
| POST | `/api/reset-pin` | Admin-authorised PIN reset for a housemate |
| POST | `/api/items/<id>/flag` | Mark low / empty |
| POST | `/api/items/<id>/buy` | Log purchase + cost, advance rotation |
| DELETE | `/api/items/<id>?who=` | Remove item (admin only) |
| POST | `/api/proposals` | Propose a new item |
| POST | `/api/proposals/<id>/vote` | Vote; yes-voters join the rotation |
| POST | `/api/chores/<id>/flag` | "Needs doing now" |
| POST | `/api/chores/<id>/done` | Mark done (solo / pair), advance rotation |
| POST | `/api/chores/<id>/interval` | Change reminder interval |
| POST | `/api/chores/<id>/layer` | Toggle a sub-task on a layered chore |

## Roadmap

- [x] Backend + database (persist items, chores, logs)
- [x] Per-user PIN authentication + sessions
- [x] Admin-authorised "Forgot PIN" reset flow
- [x] Admin self-recovery via a local recovery-code file
- [ ] Web-push notifications (with WhatsApp fallback for iOS)
- [ ] Hosting / deployment

## Tech

Python · Flask · SQLite · vanilla HTML/CSS/JavaScript.
