// D1 de mentira sobre node:sqlite, con la misma interfaz que usan las Functions
// (prepare → bind → first / all / run, y batch en una transacción).
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
    return this.db.prepare(this.sql);
  }

  async first(col) {
    const row = this._stmt().get(...this.args);
    if (row === undefined) return null;
    const plain = { ...row };
    return col ? plain[col] : plain;
  }

  async all() {
    return { results: this._stmt().all(...this.args).map((r) => ({ ...r })), success: true };
  }

  async run() {
    const r = this._stmt().run(...this.args);
    return { success: true, meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } };
  }
}

export class FakeD1 {
  constructor() {
    this.db = new DatabaseSync(':memory:');
  }

  prepare(sql) {
    return new Statement(this.db, sql);
  }

  async batch(stmts) {
    this.db.exec('BEGIN');
    try {
      const out = [];
      for (const s of stmts) out.push(await s.run());
      this.db.exec('COMMIT');
      return out;
    } catch (e) {
      this.db.exec('ROLLBACK');
      throw e;
    }
  }
}
