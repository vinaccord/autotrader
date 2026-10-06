"""SQLite-Ledger: Slots (virtuelle Wallets), Positionen, Trades, Freigaben."""
import json
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    strategy TEXT NOT NULL,
    address TEXT NOT NULL,
    cash REAL NOT NULL,
    start_value REAL NOT NULL,
    parent_id INTEGER,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    address TEXT NOT NULL,
    qty REAL NOT NULL,
    cost_usd REAL NOT NULL,
    entry_price REAL NOT NULL,
    last_price REAL NOT NULL,
    tp_done INTEGER NOT NULL DEFAULT 0,
    opened_at REAL NOT NULL,
    UNIQUE(slot_id, address)
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    slot_id INTEGER NOT NULL,
    side TEXT NOT NULL,
    symbol TEXT NOT NULL,
    address TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL,
    usd REAL NOT NULL,
    fee REAL NOT NULL,
    pnl REAL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    slot_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (ts REAL NOT NULL, level TEXT NOT NULL, msg TEXT NOT NULL);
"""


class Ledger:
    def __init__(self, path=":memory:"):
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self._depth = 0

    # --- Transaktionen -------------------------------------------------
    @contextmanager
    def atomic(self):
        self._depth += 1
        try:
            yield
        except Exception:
            self._depth -= 1
            if self._depth == 0:
                self.con.rollback()
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                self.con.commit()

    def _commit(self):
        if self._depth == 0:
            self.con.commit()

    # --- Key/Value -----------------------------------------------------
    def kv_get(self, key, default=None):
        row = self.con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key, value):
        self.con.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self._commit()

    # --- Slots ---------------------------------------------------------
    def create_slot(self, name, strategy, cash, address, parent_id=None, ts=None):
        cur = self.con.execute(
            "INSERT INTO slots(name,strategy,address,cash,start_value,parent_id,created_at) VALUES(?,?,?,?,?,?,?)",
            (name, strategy, address, cash, cash, parent_id, ts or time.time()),
        )
        self._commit()
        return cur.lastrowid

    def slots(self):
        return self.con.execute("SELECT * FROM slots ORDER BY id").fetchall()

    def slot(self, slot_id):
        return self.con.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()

    def add_cash(self, slot_id, delta):
        self.con.execute("UPDATE slots SET cash = cash + ? WHERE id=?", (delta, slot_id))
        self._commit()

    def set_start_value(self, slot_id, value):
        self.con.execute("UPDATE slots SET start_value=? WHERE id=?", (value, slot_id))
        self._commit()

    # --- Positionen ----------------------------------------------------
    def positions(self, slot_id=None):
        if slot_id is None:
            return self.con.execute("SELECT * FROM positions").fetchall()
        return self.con.execute("SELECT * FROM positions WHERE slot_id=?", (slot_id,)).fetchall()

    def add_to_position(self, slot_id, symbol, address, qty, cost_usd, price, ts=None):
        row = self.con.execute(
            "SELECT * FROM positions WHERE slot_id=? AND address=?", (slot_id, address)
        ).fetchone()
        if row:
            new_qty = row["qty"] + qty
            new_cost = row["cost_usd"] + cost_usd
            self.con.execute(
                "UPDATE positions SET qty=?, cost_usd=?, entry_price=?, last_price=? WHERE id=?",
                (new_qty, new_cost, new_cost / new_qty, price, row["id"]),
            )
        else:
            self.con.execute(
                "INSERT INTO positions(slot_id,symbol,address,qty,cost_usd,entry_price,last_price,opened_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (slot_id, symbol, address, qty, cost_usd, cost_usd / qty, price, ts or time.time()),
            )
        self._commit()

    def reduce_position(self, pos_id, fraction):
        row = self.con.execute("SELECT * FROM positions WHERE id=?", (pos_id,)).fetchone()
        if row is None:
            return
        if fraction >= 0.999999:
            self.con.execute("DELETE FROM positions WHERE id=?", (pos_id,))
        else:
            self.con.execute(
                "UPDATE positions SET qty=qty*?, cost_usd=cost_usd*?, tp_done=1 WHERE id=?",
                (1 - fraction, 1 - fraction, pos_id),
            )
        self._commit()

    def set_last_price(self, address, price):
        self.con.execute("UPDATE positions SET last_price=? WHERE address=?", (price, address))
        self._commit()

    def equity(self, slot_id):
        slot = self.slot(slot_id)
        held = sum(p["qty"] * p["last_price"] for p in self.positions(slot_id))
        return slot["cash"] + held

    def total_equity(self):
        return sum(self.equity(s["id"]) for s in self.slots())

    # --- Trades --------------------------------------------------------
    def record_trade(self, slot_id, side, symbol, address, qty, price, usd, fee, pnl=None, note="", ts=None):
        self.con.execute(
            "INSERT INTO trades(ts,slot_id,side,symbol,address,qty,price,usd,fee,pnl,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (ts or time.time(), slot_id, side, symbol, address, qty, price, usd, fee, pnl, note),
        )
        self._commit()

    def buys_usd_since(self, ts):
        row = self.con.execute(
            "SELECT COALESCE(SUM(usd),0) AS s FROM trades WHERE side='buy' AND ts>=?", (ts,)
        ).fetchone()
        return row["s"]

    def recent_trades(self, limit=15):
        return self.con.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # --- Freigaben -----------------------------------------------------
    def add_approval(self, slot_id, payload, ts=None):
        cur = self.con.execute(
            "INSERT INTO approvals(ts,slot_id,payload) VALUES(?,?,?)",
            (ts or time.time(), slot_id, json.dumps(payload)),
        )
        self._commit()
        return cur.lastrowid

    def approval(self, approval_id):
        return self.con.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()

    def pending_approvals(self):
        return self.con.execute("SELECT * FROM approvals WHERE status='pending' ORDER BY id").fetchall()

    def set_approval_status(self, approval_id, status):
        self.con.execute("UPDATE approvals SET status=? WHERE id=?", (status, approval_id))
        self._commit()

    # --- Log -----------------------------------------------------------
    def log(self, level, msg, ts=None):
        self.con.execute("INSERT INTO events(ts,level,msg) VALUES(?,?,?)", (ts or time.time(), level, msg))
        self._commit()

    def recent_events(self, limit=15):
        return self.con.execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
