import json
from pathlib import Path
import shutil
import subprocess
import unittest

from streamlit.testing.v1 import AppTest


ASSETS = Path(__file__).resolve().parents[1] / "tea_ledger_component"


class LedgerTests(unittest.TestCase):
    def test_component_mounts_with_only_order_draft_fields(self):
        app = AppTest.from_string(
            "import streamlit as st\nfrom tea_ledger import render_ledger\n"
            "st.session_state['tea.last_order'] = {'brand':'示例', 'name':'茉莉', 'price':12.5, 'other':'private'}\n"
            "render_ledger()"
        ).run()
        self.assertFalse(app.exception)
        component = app.get("bidi_component")[0].proto
        self.assertEqual(json.loads(component.json), {"brand": "示例", "name": "茉莉", "price": "12.5"})
        self.assertIn("备份", component.html_content)

    def test_manual_entry_without_simulated_purchase(self):
        app = AppTest.from_string("from tea_ledger import render_ledger\nrender_ledger()").run()
        self.assertFalse(app.exception)
        self.assertEqual(json.loads(app.get("bidi_component")[0].proto.json), {})

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to run JavaScript logic tests")
    def test_cents_calendar_totals_and_atomic_backup_validation(self):
        checks = """
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source = readFileSync(process.argv[2], 'utf8');
const {parseCents, parseBackup, summarize, money, mergeEntries} = await import(
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
for (const [value, cents] of [['1',100], ['12.3',1230], ['0.01',1], ['99999999.99',9999999999]]) {
  assert.equal(parseCents(value), cents);
}
for (const bad of ['', '0', '-1', '3.141', '1e3', 'NaN', '100000000']) assert.throws(() => parseCents(bad));
const row = {id:'28e1fcab-f8be-4501-b28d-70bac7da633b',kind:'expense',date:'2024-02-29',cents:1990,note:'test'};
const wrap = entries => JSON.stringify({format:'shijian-tea-ledger',version:1,entries});
assert.deepEqual(parseBackup(wrap([row,row])), [row]);
for (const change of [{date:'2025-02-29'}, {date:'2024-02-30'}, {note:'x'.repeat(161)}, {kind:'unknown'},
  {cents:1.5}, {cents:-20}, {cents:0}, {id:'bad-id'}, {cents:'5'}]) {
  assert.throws(() => parseBackup(wrap([row,{...row,...change}])));
}
assert.throws(() => parseBackup(wrap([row,{...row,note:'conflicting version'}])));
assert.throws(() => parseBackup('{"version":2,"entries":[]}'));
const next = {...row,kind:'income',date:'2024-03-01',cents:2500};
const totals = summarize([row,next], '2024-02');
assert.equal(totals.balance, 510n);
assert.equal(totals.expense, 1990n);
assert.equal(totals.income, 0n);
assert.deepEqual(totals.selected, [row]);
assert.equal(money(totals.balance), '¥5.10');
assert.equal(money(-1), '−¥0.01');

// A calendar week starts on Monday and may be clipped at either end of the month.
const weeks = summarize([
  {...row, date:'2024-09-01', cents:101}, {...row, date:'2024-09-02', cents:202},
  {...row, date:'2024-09-08', cents:3}, {...row, date:'2024-09-09', cents:1},
  {...row, date:'2024-09-30', cents:9}, {...row, date:'2024-10-01', cents:999},
  {...row, date:'2024-09-08', kind:'income', cents:700},
], '2024-09').weeks;
assert.deepEqual(weeks.map(w => [w.start, w.end, w.expense]), [
  [1,1,101n], [2,8,205n], [9,15,1n], [16,22,0n], [23,29,0n], [30,30,9n],
]);
assert.deepEqual(totals.weeks.at(-1), {start:26,end:29,expense:1990n});
assert.equal(summarize([], '2021-02').weeks.length, 4);
assert.deepEqual(summarize([row], '').weeks, []);

// Model the IndexedDB event contract, exposing writes only on commit.
let saved = new Map();
const db = { transaction(table, mode) {
  assert.equal(table, 'entries');
  assert.equal(mode, 'readwrite');
  const pending = new Map(saved);
  let aborted = false;
  const tx = {
    objectStore() { return {
      get(id) {
        const request = {};
        queueMicrotask(() => { if (!aborted) { request.result = pending.get(id); request.onsuccess(); } });
        return request;
      },
      add(row) { assert(!pending.has(row.id)); pending.set(row.id,row); }
    }; },
    abort() { aborted = true; tx.onabort(); }
  };
  setImmediate(() => { if (!aborted) { saved = pending; tx.oncomplete(); } });
  return tx;
} };
assert.equal(await mergeEntries(db, [row]), 1);
assert.equal(await mergeEntries(db, [row]), 0);
const another = {...row, id:'10000000-0000-4000-a000-000000000000'};
await assert.rejects(mergeEntries(db, [another,{...row,cents:200}]), /整批导入已取消/);
assert.deepEqual([...saved.values()], [row]);
assert.equal(await mergeEntries(db,[another,row]), 1);
assert.equal(saved.size, 2);
"""
        subprocess.run(
            [shutil.which("node"), "--input-type=module", "-", str(ASSETS / "ledger.js")],
            input=checks, text=True, encoding="utf-8", check=True,
        )
