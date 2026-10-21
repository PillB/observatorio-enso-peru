// D1 de mentira sobre node:sqlite, con la misma interfaz que usan las Functions
// (prepare → bind → first / all / run, y batch en una transacción). `trips` cuenta los viajes a la base, que en
// Cloudflare son idas y vueltas por la red.
import { DatabaseSync } from 'node:sqlite';

class Statement {
  constructor(db, sql, args = []) {
    this.db = db;
    this.sql = sql;
    this.args = args;
  }

  bind(...args) {
    return new Statement(this.db, this.sql, args);
  }

  _stmt() {
    return this.db.sqlite.prepare(this.sql);
  }

  async first(col) {
    this.db.trips += 1;
    const row = this._stmt().get(...this.args);
    if (row === undefined) return null;
    const plain = { ...row };
    return col ? plain[col] : plain;
  }

  async all() {
    this.db.trips += 1;
    return { results: this._stmt().all(...this.args).map((r) => ({ ...r })), success: true };
  }

  async run() {
    this.db.trips += 1;
    return this._run();
  }

  _run() {
    const r = this._stmt().run(...this.args);
    return { success: true, meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } };
  }
}

export class FakeD1 {
  constructor() {
    this.sqlite = new DatabaseSync(':memory:');
    this.trips = 0;
  }

  prepare(sql) {
    return new Statement(this, sql);
  }

  async batch(stmts) {
    this.trips += 1;
    this.sqlite.exec('BEGIN');
    try {
      const out = stmts.map((s) => s._run());
      this.sqlite.exec('COMMIT');
      return out;
    } catch (e) {
      this.sqlite.exec('ROLLBACK');
      throw e;
    }
  }
}
