const format = "shijian-tea-ledger";
const maxCents = 9999999999;
const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;

export function parseCents(input) {
  const match = /^(\d{1,8})(?:\.(\d{1,2}))?$/.exec(input.trim());
  const cents = match ? Number(match[1]) * 100 + Number((match[2] || "").padEnd(2, "0")) : 0;
  if (cents < 1 || cents > maxCents) {
    throw new Error("请填写 0.01 至 99999999.99 元的金额，最多两位小数。");
  }
  return cents;
}

function validDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
  const date = new Date(value + "T00:00:00.000Z");
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function entry(raw) {
  if (!raw || typeof raw.id !== "string" || !uuid.test(raw.id) ||
      !["expense", "income"].includes(raw.kind) || !validDate(raw.date) ||
      !Number.isSafeInteger(raw.cents) || raw.cents < 1 || raw.cents > maxCents ||
      typeof raw.note !== "string" || raw.note.length > 160) {
    throw new Error("账本记录格式无效，请检查日期、类型、金额及备注。");
  }
  return {id: raw.id.toLowerCase(), kind: raw.kind, date: raw.date, cents: raw.cents, note: raw.note};
}

function sameRecord(a, b) {
  return a.kind === b.kind && a.date === b.date && a.cents === b.cents && a.note === b.note;
}

export function parseBackup(json) {
  let backup;
  try { backup = JSON.parse(json); }
  catch { throw new Error("无法读取 JSON，请选择账本导出的备份。"); }
  if (backup?.format !== format || backup.version !== 1 || !Array.isArray(backup.entries)) {
    throw new Error("备份格式或版本不受支持。");
  }
  const unique = new Map();
  for (const raw of backup.entries) {
    const row = entry(raw);
    if (unique.has(row.id) && !sameRecord(unique.get(row.id), row)) {
      throw new Error("备份中同一编号有不同内容。导入已取消。");
    }
    unique.set(row.id, row);
  }
  return [...unique.values()];
}

export function money(amount) {
  const cents = BigInt(amount);
  const absolute = cents < 0n ? -cents : cents;
  return (cents < 0n ? "−" : "") + "¥" + (absolute / 100n).toLocaleString("zh-CN") +
    "." + (absolute % 100n).toString().padStart(2, "0");
}

export function summarize(rows, month) {
  let balance = 0n, expense = 0n, income = 0n;
  const selected = [];
  const weeks = [];
  let weekdayOffset = 0;
  if (validDate(month + "-01")) {
    const date = new Date(month + "-01T00:00:00Z");
    weekdayOffset = (date.getUTCDay() + 6) % 7;
    date.setUTCMonth(date.getUTCMonth() + 1, 0);
    const lastDay = date.getUTCDate();
    for (let start = 1; start <= lastDay;) {
      const end = Math.min(lastDay, start === 1 ? 7 - weekdayOffset : start + 6);
      weeks.push({start, end, expense: 0n});
      start = end + 1;
    }
  }
  for (const row of rows) {
    const cents = BigInt(row.cents);
    balance += row.kind === "income" ? cents : -cents;
    if (row.date.slice(0, 7) !== month) continue;
    selected.push(row);
    if (row.kind === "income") income += cents;
    else {
      expense += cents;
      const index = Math.floor((Number(row.date.slice(8)) - 1 + weekdayOffset) / 7);
      weeks[index].expense += cents;
    }
  }
  selected.sort((a, b) => b.date.localeCompare(a.date));
  return {balance, expense, income, selected, weeks};
}

function drawWeeklyChart(list, weeks, month) {
  const max = weeks.reduce((peak, week) => week.expense > peak ? week.expense : peak, 0n);
  const monthNumber = Number(month.slice(5));
  list.replaceChildren();
  for (const week of weeks) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.className = "week-date";
    label.textContent = monthNumber + "月" + week.start +
      (week.start === week.end ? "" : "–" + week.end) + "日";
    const track = document.createElement("span");
    track.className = "week-track";
    track.setAttribute("aria-hidden", "true");
    const bar = document.createElement("span");
    bar.style.width = (max ? Number(week.expense * 10000n / max) / 100 : 0) + "%";
    track.append(bar);
    const value = document.createElement("b");
    value.textContent = money(week.expense);
    item.append(label, track, value);
    list.append(item);
  }
}

function openLedger(name) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(name, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("entries", {keyPath: "id"});
    request.onerror = () => reject(new Error("无法打开本机账本，请允许网站存储并刷新。"));
    request.onsuccess = () => resolve(request.result);
  });
}

function readAll(db) {
  return new Promise((resolve, reject) => {
    const request = db.transaction("entries").objectStore("entries").getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("读取账本失败，请刷新重试。"));
  });
}

// All reads for a merge and their writes share a transaction, including across tabs.
export function mergeEntries(db, rows) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction("entries", "readwrite");
    const store = tx.objectStore("entries");
    let added = 0;
    let issue;
    tx.oncomplete = () => resolve(added);
    tx.onabort = () => reject(new Error(issue || "写入失败，请检查浏览器存储空间后重试。"));
    for (const row of rows) {
      const request = store.get(row.id);
      request.onsuccess = () => {
        if (issue) return;
        if (!request.result) {
          store.add(row);
          added++;
        } else if (!sameRecord(request.result, row)) {
          issue = "同一编号的记录内容不同，整批导入已取消，原账本已保留。";
          tx.abort();
        }
      };
    }
  });
}

function deleteEntry(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction("entries", "readwrite");
    tx.objectStore("entries").delete(id);
    tx.oncomplete = resolve;
    tx.onabort = () => reject(new Error("删除失败，请重试。"));
  });
}

function newId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}

function download(rows, date) {
  const backup = JSON.stringify({format, version: 1, entries: rows}, null, 2);
  const url = URL.createObjectURL(new Blob([backup], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "茶饮账本-" + date + ".json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function render({parentElement, data}) {
  const q = selector => parentElement.querySelector(selector);
  const report = message => { q("#status").textContent = message; };
  const today = new Date();
  const localDate = [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0")].join("-");
  const name = format + ".v1:" + location.pathname.replace(/\/+$/, "");
  let db, channel, rows = [], limit = 20, busy = false, closed = false;
  const setKindLabel = () => {
    q("#amount-label").textContent = q("#kind").value === "expense" ? "实付金额（元）" : "收入金额（元）";
  };
  q("#date").value ||= localDate;
  q("#month").value ||= localDate.slice(0, 7);
  setKindLabel();
  q("#kind").onchange = setKindLabel;
  q("#draft").hidden = !(data?.brand || data?.name || data?.price);
  q("#draft").onclick = () => {
    q("#kind").value = "expense";
    setKindLabel();
    q("#note").value = [data.brand, data.name].filter(Boolean).join(" · ").slice(0, 160);
    try { parseCents(data.price || ""); q("#amount").value = data.price; }
    catch { q("#amount").value = ""; }
    q("#amount").focus();
    report("已带入点单信息，请核对优惠后的实际支付金额。");
  };

  function paint() {
    const month = q("#month").value;
    const {balance, expense, income, selected, weeks} = summarize(rows, month);
    for (const [id, value] of Object.entries({balance, expense, income})) q("#" + id).textContent = money(value);
    drawWeeklyChart(q("#weeks"), weeks, month);
    q("#month-summary").textContent = selected.length
      ? selected.length + " 笔收支 · 当月结余 " + money(income - expense) : "这个月还没有收支记录。";
    const list = q("#entries");
    list.replaceChildren();
    for (const row of selected.slice(0, limit)) {
      const li = document.createElement("li");
      const info = document.createElement("div");
      info.className = "entry-info";
      const day = document.createElement("span");
      day.className = "entry-date";
      day.textContent = row.date + " · " + (row.kind === "expense" ? "支出" : "收入");
      info.append(day, document.createTextNode(row.note));
      const value = document.createElement("b");
      value.textContent = (row.kind === "expense" ? "−" : "+") + money(row.cents);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove";
      remove.textContent = "删除";
      remove.setAttribute("aria-label", "删除 " + row.date + " 的 " + value.textContent + " 记录");
      remove.onclick = () => {
        if (window.confirm("删除 " + row.date + " 的 " + value.textContent + " 记录？")) {
          perform(async () => { await deleteEntry(db, row.id); return "已删除这笔记录。"; });
        }
      };
      li.append(info, value, remove);
      list.append(li);
    }
    q("#more").hidden = selected.length <= limit;
  }
  async function refresh() {
    const latest = await readAll(db);
    if (closed) return;
    rows = latest;
    paint();
  }
  function showError(error) { if (!closed) report(error.message || "操作失败，请重试。"); }
  function setEnabled(ready) {
    q("fieldset").disabled = !ready;
    q("#export").disabled = !ready;
    q("#import").disabled = !ready;
  }
  async function perform(action) {
    if (!db || busy) return;
    busy = true;
    setEnabled(false);
    try {
      const message = await action();
      channel?.postMessage("changed");
      await refresh();
      if (!closed) report(message);
    } catch (error) { showError(error); }
    finally { busy = false; if (!closed) setEnabled(true); }
  }
  q("form").onsubmit = event => {
    event.preventDefault();
    perform(async () => {
      const row = entry({id: newId(), kind: q("#kind").value, cents: parseCents(q("#amount").value),
        date: q("#date").value, note: q("#note").value.trim()});
      await mergeEntries(db, [row]);
      if (!closed) {
        q("#amount").value = "";
        q("#note").value = "";
        q("#month").value = row.date.slice(0, 7);
        limit = 20;
      }
      return "已保存到此浏览器。";
    });
  };
  q("#month").onchange = () => {
    q("#month").value ||= localDate.slice(0, 7);
    limit = 20;
    paint();
  };
  q("#more").onclick = () => { limit += 20; paint(); };
  q("#export").onclick = async () => {
    try { download(await readAll(db), localDate); }
    catch (error) { showError(error); }
  };
  q("#import").onchange = event => {
    const file = event.target.files[0];
    event.target.value = "";
    if (file) perform(async () => {
      const records = parseBackup(await file.text());
      const count = await mergeEntries(db, records);
      return "导入完成，新增 " + count + " 笔。";
    });
  };
  const onFocus = () => { if (db && !closed) refresh().catch(showError); };
  setEnabled(false);
  openLedger(name).then(async connected => {
    if (closed) { connected.close(); return; }
    db = connected;
    if (typeof BroadcastChannel !== "undefined") {
      channel = new BroadcastChannel(name);
      channel.onmessage = onFocus;
    }
    window.addEventListener("focus", onFocus);
    await refresh();
    if (!closed) { setEnabled(true); report(""); }
  }).catch(() => { if (!closed) report("无法读取本机账本，请允许浏览器保存网站数据，然后刷新重试。"); });
  return () => {
    closed = true;
    window.removeEventListener("focus", onFocus);
    channel?.close();
    db?.close();
  };
}
