// web shim for expo-sqlite using sql.js (screenshots only)
import initSqlJs from 'sql.js/dist/sql-wasm.js';
let SQLp;
const flat = (a) => (a.length === 1 && Array.isArray(a[0]) ? a[0] : a).map((v) => (v === undefined ? null : v));
export async function openDatabaseAsync() {
  SQLp = SQLp || initSqlJs({ locateFile: () => '/sql-wasm.wasm' });
  const SQL = await SQLp; const db = new SQL.Database();
  const all = (sql, p) => { const st = db.prepare(sql); st.bind(p); const out = []; while (st.step()) out.push(st.getAsObject()); st.free(); return out; };
  return {
    async execAsync(sql) { db.exec(sql.replace(/PRAGMA journal_mode = WAL;/g, '')); },
    async getAllAsync(sql, ...a) { return all(sql, flat(a)); },
    async getFirstAsync(sql, ...a) { return all(sql, flat(a))[0] || null; },
    async runAsync(sql, ...a) { db.run(sql, flat(a)); const r = all('SELECT last_insert_rowid() AS id, changes() AS c', []); return { lastInsertRowId: r[0].id, changes: r[0].c }; },
    async withTransactionAsync(fn) { await fn(); },
  };
}
