"""
House HQ - backend
Flask + SQLite. Single file. Run:  python app.py
Then open http://localhost:5000
"""
import json, os, time, random, sqlite3, hashlib, secrets
from flask import Flask, jsonify, request, send_from_directory, g

BASE = os.path.dirname(os.path.abspath(__file__))
# DB_PATH lets a host point the database at a persistent disk; defaults to local file
DB = os.environ.get("DB_PATH", os.path.join(BASE, "house.db"))

PEOPLE = ["Kartik", "Kalyan", "Parva", "Gautami"]
ADMIN = "Kartik"
DAY = 86400000  # ms, to match the frontend

app = Flask(__name__)


def now():
    return int(time.time() * 1000)


def days_ago(d):
    return now() - d * DAY


def rid():
    return "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(7))


def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100000).hex()


# ---------- DB ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    d = g.pop("db", None)
    if d is not None:
        d.close()


def init_db():
    con = sqlite3.connect(DB)
    c = con.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS settings(
      key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS users(
      name TEXT PRIMARY KEY, salt TEXT, pin_hash TEXT);
    CREATE TABLE IF NOT EXISTS sessions(
      token TEXT PRIMARY KEY, name TEXT, created INTEGER);
    CREATE TABLE IF NOT EXISTS items(
      id TEXT PRIMARY KEY, name TEXT, section TEXT, state TEXT,
      turn_idx INTEGER, participants TEXT);
    CREATE TABLE IF NOT EXISTS buys(
      id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, who TEXT, cost REAL, ts INTEGER);
    CREATE TABLE IF NOT EXISTS chores(
      id TEXT PRIMARY KEY, name TEXT, interval INTEGER, mode TEXT,
      turn_idx INTEGER, last_done INTEGER, urgent INTEGER, pair TEXT, layers TEXT);
    CREATE TABLE IF NOT EXISTS chore_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT, chore_id TEXT, who TEXT, pts REAL, ts INTEGER);
    CREATE TABLE IF NOT EXISTS proposals(
      id TEXT PRIMARY KEY, name TEXT, section TEXT, by_who TEXT, votes TEXT);
    """)
    con.commit()

    for p in PEOPLE:
        c.execute("INSERT OR IGNORE INTO users(name,salt,pin_hash) VALUES(?,NULL,NULL)", (p,))
    con.commit()

    # admin recovery code (generated once, written to a local file only)
    has = c.execute("SELECT value FROM settings WHERE key='admin_recovery_hash'").fetchone()
    if not has:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous chars
        code = "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
        salt = secrets.token_hex(8)
        c.execute("INSERT INTO settings(key,value) VALUES('admin_recovery_salt',?)", (salt,))
        c.execute("INSERT INTO settings(key,value) VALUES('admin_recovery_hash',?)",
                  (hash_pin(code, salt),))
        con.commit()
        with open(os.path.join(os.path.dirname(DB) or BASE, "admin_recovery.txt"), "w") as f:
            f.write("HOUSE HQ - ADMIN RECOVERY CODE\n")
            f.write("=" * 40 + "\n\n")
            f.write("Keep this safe. It lets the admin (%s) reset their own PIN\n" % ADMIN)
            f.write("if forgotten, on the sign-in screen via 'Forgot PIN?'.\n\n")
            f.write("   RECOVERY CODE:  %s\n\n" % code)
            f.write("This file is git-ignored and stays only on this computer.\n")
        print("Admin recovery code written to admin_recovery.txt")

    if c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
        seed_items = [
            ("Onion", "Kitchen", PEOPLE), ("Tomatoes", "Kitchen", PEOPLE),
            ("Milk", "Kitchen", PEOPLE), ("Chicken", "Kitchen", ["Kartik", "Kalyan", "Gautami"]),
            ("Ginger", "Kitchen", PEOPLE), ("Garlic", "Kitchen", PEOPLE),
            ("Ginger paste", "Kitchen", PEOPLE), ("Garlic paste", "Kitchen", PEOPLE),
            ("Kitchen tissue", "Kitchen", PEOPLE), ("Toilet paper", "Bathroom", PEOPLE),
            ("Bin bags - compostable", "Kitchen", PEOPLE), ("Bin bags - normal", "Kitchen", PEOPLE),
            ("Toilet cleaner", "Bathroom", PEOPLE), ("Bathroom spray", "Bathroom", PEOPLE),
            ("Floor cleaner", "Bathroom", PEOPLE),
        ]
        for name, sec, parts in seed_items:
            c.execute("INSERT INTO items VALUES(?,?,?,?,?,?)",
                      (rid(), name, sec, "ok", random.randint(0, 3), json.dumps(parts)))

        def add_chore(name, interval, mode, pair=None, layers=None):
            c.execute("INSERT INTO chores VALUES(?,?,?,?,?,?,?,?,?)",
                      (rid(), name, interval, mode, random.randint(0, 3),
                       days_ago(random.randint(0, interval)), 0,
                       json.dumps(pair) if pair else None,
                       json.dumps(layers) if layers else None))

        add_chore("Compost bin", 3, "solo")
        add_chore("General waste bin", 7, "solo")
        add_chore("Recycling bin", 7, "solo")
        add_chore("Clean kitchen", 14, "any")
        add_chore("Clean bedroom", 14, "any")
        add_chore("Clean bathroom 1", 14, "fixedpair", pair=["Parva", "Kalyan"])
        add_chore("Clean bathroom 2", 14, "fixedpair", pair=["Gautami", "Kartik"])
        add_chore("Hall", 14, "any",
                  layers=[{"name": n, "done": False, "by": None}
                          for n in ["Brush floor", "Wipe floor", "Dining table", "Teapoy"]])
        con.commit()
    con.close()


# ---------- auth ----------
def actor_from_token():
    tok = request.headers.get("X-Token", "")
    if not tok:
        return None
    row = db().execute("SELECT name FROM sessions WHERE token=?", (tok,)).fetchone()
    return row["name"] if row else None


@app.before_request
def guard():
    # only guard mutating API calls; reads and login are open
    p = request.path
    if not p.startswith("/api/") or p in ("/api/state", "/api/login",
                                          "/api/reset-pin", "/api/admin-recover"):
        return
    if request.method in ("POST", "DELETE"):
        actor = actor_from_token()
        if not actor:
            return jsonify({"error": "not logged in"}), 401
        g.actor = actor


# ---------- state ----------
def get_state():
    c = db().cursor()
    users = {r["name"]: (r["pin_hash"] is not None)
             for r in c.execute("SELECT name,pin_hash FROM users").fetchall()}
    items = []
    for r in c.execute("SELECT * FROM items").fetchall():
        buys = [{"who": b["who"], "cost": b["cost"], "when": b["ts"]}
                for b in c.execute("SELECT * FROM buys WHERE item_id=? ORDER BY ts", (r["id"],))]
        items.append({"id": r["id"], "name": r["name"], "section": r["section"],
                      "state": r["state"], "turnIdx": r["turn_idx"],
                      "participants": json.loads(r["participants"]), "buys": buys})
    chores = []
    for r in c.execute("SELECT * FROM chores").fetchall():
        log = [{"who": json.loads(l["who"]), "pts": l["pts"], "when": l["ts"]}
               for l in c.execute("SELECT * FROM chore_log WHERE chore_id=? ORDER BY ts", (r["id"],))]
        chores.append({"id": r["id"], "name": r["name"], "interval": r["interval"],
                       "mode": r["mode"], "turnIdx": r["turn_idx"], "lastDone": r["last_done"],
                       "urgent": bool(r["urgent"]),
                       "pair": json.loads(r["pair"]) if r["pair"] else None,
                       "layers": json.loads(r["layers"]) if r["layers"] else None,
                       "log": log})
    proposals = [{"id": r["id"], "name": r["name"], "section": r["section"],
                  "by": r["by_who"], "votes": json.loads(r["votes"])}
                 for r in c.execute("SELECT * FROM proposals").fetchall()]
    return {"people": PEOPLE, "admin": ADMIN, "hasPin": users,
            "items": items, "chores": chores, "proposals": proposals}


def turn_person(o):
    if o["mode"] == "fixedpair":
        return o["pair"][o["turn_idx"] % len(o["pair"])]
    parts = o.get("participants") or PEOPLE
    return parts[o["turn_idx"] % len(parts)]


# ---------- routes ----------
@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.route("/api/state")
def api_state():
    return jsonify(get_state())


# ----- auth endpoints -----
@app.post("/api/login")
def login():
    b = request.json or {}
    who = b.get("who")
    pin = str(b.get("pin", ""))
    if who not in PEOPLE:
        return jsonify({"error": "unknown user"}), 400
    if len(pin) < 4:
        return jsonify({"error": "PIN must be at least 4 digits"}), 400
    row = db().execute("SELECT * FROM users WHERE name=?", (who,)).fetchone()
    if row["pin_hash"] is None:
        # first time: set the PIN now
        salt = secrets.token_hex(8)
        db().execute("UPDATE users SET salt=?, pin_hash=? WHERE name=?",
                     (salt, hash_pin(pin, salt), who))
    else:
        if hash_pin(pin, row["salt"]) != row["pin_hash"]:
            return jsonify({"error": "wrong PIN"}), 401
    token = secrets.token_hex(16)
    db().execute("INSERT INTO sessions(token,name,created) VALUES(?,?,?)", (token, who, now()))
    db().commit()
    return jsonify({"token": token, "who": who})


@app.post("/api/reset-pin")
def reset_pin():
    b = request.json or {}
    who = b.get("who")
    admin_pin = str(b.get("adminPin", ""))
    new_pin = str(b.get("newPin", ""))
    if who not in PEOPLE:
        return jsonify({"error": "unknown user"}), 400
    if len(new_pin) < 4:
        return jsonify({"error": "new PIN must be at least 4 digits"}), 400
    # verify the admin's own PIN
    a = db().execute("SELECT * FROM users WHERE name=?", (ADMIN,)).fetchone()
    if a["pin_hash"] is None:
        return jsonify({"error": "admin has not set a PIN yet"}), 400
    if hash_pin(admin_pin, a["salt"]) != a["pin_hash"]:
        return jsonify({"error": "wrong admin PIN"}), 401
    # set the new PIN for the target user and end their sessions
    salt = secrets.token_hex(8)
    db().execute("UPDATE users SET salt=?, pin_hash=? WHERE name=?",
                 (salt, hash_pin(new_pin, salt), who))
    db().execute("DELETE FROM sessions WHERE name=?", (who,))
    db().commit()
    return jsonify({"ok": True})


@app.post("/api/admin-recover")
def admin_recover():
    b = request.json or {}
    code = str(b.get("code", "")).strip().upper()
    new_pin = str(b.get("newPin", ""))
    if len(new_pin) < 4:
        return jsonify({"error": "new PIN must be at least 4 digits"}), 400
    salt_row = db().execute("SELECT value FROM settings WHERE key='admin_recovery_salt'").fetchone()
    hash_row = db().execute("SELECT value FROM settings WHERE key='admin_recovery_hash'").fetchone()
    if not salt_row or not hash_row:
        return jsonify({"error": "no recovery code set"}), 400
    if hash_pin(code, salt_row["value"]) != hash_row["value"]:
        return jsonify({"error": "wrong recovery code"}), 401
    salt = secrets.token_hex(8)
    db().execute("UPDATE users SET salt=?, pin_hash=? WHERE name=?",
                 (salt, hash_pin(new_pin, salt), ADMIN))
    db().execute("DELETE FROM sessions WHERE name=?", (ADMIN,))
    db().commit()
    return jsonify({"ok": True})


@app.post("/api/logout")
def logout():
    tok = request.headers.get("X-Token", "")
    db().execute("DELETE FROM sessions WHERE token=?", (tok,))
    db().commit()
    return jsonify({"ok": True})


# ----- items -----
@app.post("/api/items/<iid>/flag")
def item_flag(iid):
    state = request.json.get("state", "low")
    db().execute("UPDATE items SET state=? WHERE id=?", (state, iid))
    db().commit()
    return jsonify(get_state())


@app.post("/api/items/<iid>/buy")
def item_buy(iid):
    who = g.actor
    cost = float(request.json.get("cost", 0) or 0)
    row = db().execute("SELECT turn_idx FROM items WHERE id=?", (iid,)).fetchone()
    db().execute("INSERT INTO buys(item_id,who,cost,ts) VALUES(?,?,?,?)", (iid, who, cost, now()))
    db().execute("UPDATE items SET state='ok', turn_idx=? WHERE id=?", (row["turn_idx"] + 1, iid))
    db().commit()
    return jsonify(get_state())


@app.delete("/api/items/<iid>")
def item_delete(iid):
    if g.actor != ADMIN:
        return jsonify({"error": "admin only"}), 403
    db().execute("DELETE FROM items WHERE id=?", (iid,))
    db().execute("DELETE FROM buys WHERE item_id=?", (iid,))
    db().commit()
    return jsonify(get_state())


# ----- proposals -----
@app.post("/api/proposals")
def proposal_add():
    b = request.json
    pid = rid()
    db().execute("INSERT INTO proposals VALUES(?,?,?,?,?)",
                 (pid, b["name"], b["section"], g.actor, json.dumps({g.actor: "yes"})))
    db().commit()
    return jsonify(get_state())


@app.post("/api/proposals/<pid>/vote")
def proposal_vote(pid):
    b = request.json
    row = db().execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if not row:
        return jsonify(get_state())
    votes = json.loads(row["votes"])
    votes[g.actor] = b["vote"]
    if all(p in votes for p in PEOPLE):
        yes = [p for p in PEOPLE if votes.get(p) == "yes"]
        if yes:
            db().execute("INSERT INTO items VALUES(?,?,?,?,?,?)",
                         (rid(), row["name"], row["section"], "ok",
                          random.randint(0, len(yes) - 1), json.dumps(yes)))
        db().execute("DELETE FROM proposals WHERE id=?", (pid,))
    else:
        db().execute("UPDATE proposals SET votes=? WHERE id=?", (json.dumps(votes), pid))
    db().commit()
    return jsonify(get_state())


# ----- chores -----
@app.post("/api/chores/<cid>/flag")
def chore_flag(cid):
    db().execute("UPDATE chores SET urgent=1 WHERE id=?", (cid,))
    db().commit()
    return jsonify(get_state())


@app.post("/api/chores/<cid>/interval")
def chore_interval(cid):
    iv = int(request.json["interval"])
    db().execute("UPDATE chores SET interval=? WHERE id=?", (iv, cid))
    db().commit()
    return jsonify(get_state())


@app.post("/api/chores/<cid>/done")
def chore_done(cid):
    b = request.json
    kind = b.get("kind", "solo")
    row = db().execute("SELECT * FROM chores WHERE id=?", (cid,)).fetchone()
    if kind == "pairfixed":
        entries = [(json.loads(row["pair"]), 0.5)]
    elif kind == "pair":
        partners = b.get("partners", [])
        entries = [([g.actor] + partners, 0.5)]
    else:
        entries = [([g.actor], 1.0)]
    for w, pts in entries:
        db().execute("INSERT INTO chore_log(chore_id,who,pts,ts) VALUES(?,?,?,?)",
                     (cid, json.dumps(w), pts, now()))
    layers = json.loads(row["layers"]) if row["layers"] else None
    if layers:
        for l in layers:
            l["done"] = False
            l["by"] = None
    db().execute("UPDATE chores SET last_done=?, urgent=0, turn_idx=?, layers=? WHERE id=?",
                 (now(), row["turn_idx"] + 1,
                  json.dumps(layers) if layers is not None else None, cid))
    db().commit()
    return jsonify(get_state())


@app.post("/api/chores/<cid>/layer")
def chore_layer(cid):
    b = request.json
    i = b["index"]
    who = g.actor
    row = db().execute("SELECT * FROM chores WHERE id=?", (cid,)).fetchone()
    layers = json.loads(row["layers"])
    layers[i]["done"] = not layers[i]["done"]
    layers[i]["by"] = who if layers[i]["done"] else None
    if all(l["done"] for l in layers):
        doers = list({l["by"] for l in layers})
        for d in doers:
            share = round(sum(1 for l in layers if l["by"] == d) / len(layers), 2)
            db().execute("INSERT INTO chore_log(chore_id,who,pts,ts) VALUES(?,?,?,?)",
                         (cid, json.dumps([d]), share, now()))
        for l in layers:
            l["done"] = False
            l["by"] = None
        db().execute("UPDATE chores SET last_done=?, urgent=0, turn_idx=?, layers=? WHERE id=?",
                     (now(), row["turn_idx"] + 1, json.dumps(layers), cid))
    else:
        db().execute("UPDATE chores SET layers=? WHERE id=?", (json.dumps(layers), cid))
    db().commit()
    return jsonify(get_state())


# run once at import so it works under gunicorn (production) too
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print(f"House HQ running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
