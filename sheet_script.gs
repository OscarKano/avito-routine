/** @OnlyCurrentDoc */
// ^ Google даст скрипту доступ ТОЛЬКО к этой одной таблице (а не ко всем таблицам аккаунта).

/**
 * SneakerFlow -> Google-таблица заказов «КРОССОВКИ: ПРИБЫЛЬ И ОБОРОТ», лист «Расчёт».
 * Вставляется в саму таблицу: Расширения -> Apps Script -> заменить всё этим кодом -> Развернуть как веб-приложение.
 *
 * Работает ТОЛЬКО по запросу бота с секретным ключом (SECRET ниже, такой же в .env у бота).
 *   ping       — проверить, что лист и колонки нашлись (ничего не меняет);
 *   append     — добавить НОВЫЙ заказ в первую пустую строку после последней заполненной;
 *   update     — у СВОЕГО заказа поменять статус / трек / службу / дату прихода денег / суммы;
 *   returns    — строки «Возврат: у поставщика» (чтобы знать, какой возврат потратить);
 *   use_return — строку возврата «Возврат: у поставщика» -> «Возврат: отоварен» (меняет только статус);
 *   frozen     — сколько лежит у каждого поставщика (блок «Поставщики» -> «Лежит у него»);
 *   read       — прочитать строку своего заказа целиком (проверить, что формулы посчитали);
 *   summary    — ТОЛЬКО ЧТЕНИЕ: блоки сверху (как они показаны на листе) и все строки заказов — для кнопки
 *                «💰 Где мои деньги» и «📝 Дела на сегодня» в боте. Ничего не меняет;
 *   organize   — разложить список по месяцам (версия 7, просьба пользователя 26.09.2026): перед каждым месяцем строка-
 *                заголовок «Август 2026 — заказов 40, продано 29, прибыль 19 622 ₽» (формула, в колонке «Модель»;
 *                колонка «Дата» пустая — доля возвратов считается через COUNTA дат), прошлые месяцы сворачиваются «+/−»;
 *                и собрать лист «По месяцам». Сдвигает ТОЛЬКО ячейки таблицы заказов (A–N): блок «Поставщики» справа
 *                не двигается; месяцы в строках рядом с этим блоком не сворачиваются (иначе скрылся бы его ИТОГО).
 *   monthly    — пересобрать лист «По месяцам» (формулы по датам и статусам листа «Расчёт»).
 *   remove_installment — (версия 8, просьба пользователя 26.09.2026: «рассрочка не нужна, убери сам») очистить блок
 *                «РАССРОЧКА (беспроцентная)» справа вверху листа «Расчёт» — ТОЛЬКО если в нём ровно ожидаемые подписи
 *                (свободный лимит, ближайший платёж, дата платежа, дней до платежа, вложено в товар за период); и
 *                убрать строки про рассрочку из «Памятки». На блок не ссылается ни одна другая формула (проверено).
 *   Новый заказ нового месяца (append) сам ставит заголовок месяца, сворачивает прошлый и дополняет «По месяцам».
 *
 * Защита денег:
 *   - пишет ТОЛЬКО в колонки из WRITABLE; перед записью проверяет, что в ячейке НЕТ формулы, иначе отказ;
 *   - значения для выпадающих списков (служба, поставщик, статус) должны быть из списка ячейки, иначе отказ;
 *   - сначала проверяет все ячейки строки, и только если всё в порядке — пишет;
 *   - колонки ищет по заголовкам, а не по буквам — вставка новых колонок ничего не сдвинет;
 *   - свой заказ помечает заметкой «sneakerflow #N» в ячейке с датой: по ней строка находится даже после сортировки,
 *     а повторная отправка того же заказа не создаёт дубль.
 */

const VERSION = '8';  // бот видит его в ответе на ping — так понятно, что Google отдаёт свежий код, а не старую версию
const SECRET = '52788302258631296e668459fe77c2aa999af5f6';
const SHEET_NAME = 'Расчёт';
const MARK = 'sneakerflow #';
const WRITABLE = {
  date: 'Дата заказа', model: 'Модель / пара', service: 'Служба', track: 'Трек-номер', supplier: 'Поставщик',
  paid_card: 'Оплачено рассрочкой', paid_frozen: 'Оплачено из заморозки', money_date: 'Дата прихода денег',
  avito_sum: 'Сумма с Авито', status: 'Статус',
};
const COMPUTED = { cost: 'Себестоимость', profit: 'Прибыль', frozen_out: 'Ушло в заморозку', days: 'Дней ждал' };
const STATUSES = ['В процессе', 'На Авито', 'Выведено', 'Возврат: едет назад', 'Возврат: у поставщика', 'Возврат: отоварен'];
const DATE_FIELDS = ['date', 'money_date'];
const MONTH_NOTE = 'sneakerflow:month ';  // заметка на ячейке «Модель» строки-заголовка месяца: 'sneakerflow:month 202608'
const MONTHS_RU = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь',
                   'Ноябрь', 'Декабрь'];
const MONTHLY_SHEET = 'По месяцам';
const MONEY_FIELDS = ['paid_card', 'paid_frozen', 'avito_sum'];

function doGet() {
  return ContentService.createTextOutput('SneakerFlow: скрипт таблицы на месте, версия ' + VERSION);
}

function doPost(e) {
  let req;
  try { req = JSON.parse(e.postData.contents); } catch (err) { return out_({ ok: false, error: 'bad json' }); }
  if (req.secret !== SECRET) return out_({ ok: false, error: 'forbidden' });
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return out_({ ok: false, error: 'таблица занята, попробуй ещё раз' });
  try {
    const fn = { ping: ping_, append: append_, update: update_, returns: returns_, use_return: useReturn_,
                 frozen: frozen_, read: read_, summary: summary_, organize: organize_, monthly: monthlyAction_,
                 remove_installment: removeInstallment_ }[req.action];
    if (!fn) return out_({ ok: false, error: 'неизвестное действие' });
    return out_(Object.assign({ ok: true }, fn(table_(), req)));
  } catch (err) {
    return out_({ ok: false, error: String((err && err.message) || err) });
  } finally {
    lock.releaseLock();
  }
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function norm_(s) {
  return String(s).toLowerCase().replace(/ё/g, 'е').replace(/[\s▼₽,.\/\-]+/g, '');
}

function soft_(s) {  // для сравнения значений списков: регистр, ё, неразрывные и двойные пробелы не важны
  return String(s).toLowerCase().replace(/ё/g, 'е').replace(/[\s ]+/g, ' ').trim();
}

// ---------- где что лежит ----------

function table_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
  if (!sh) throw new Error('нет листа «' + SHEET_NAME + '»');
  const lastCol = sh.getLastColumn();
  const scan = Math.min(sh.getLastRow(), 150);
  const top = sh.getRange(1, 1, scan, lastCol).getDisplayValues();
  let hr = -1, hc = -1;
  for (let r = 0; r < scan && hr < 0; r++) {
    for (let c = 0; c < lastCol; c++) {
      if (norm_(top[r][c]) === norm_(WRITABLE.date)) { hr = r; hc = c; break; }
    }
  }
  if (hr < 0) throw new Error('не нашёл заголовок «Дата заказа»');
  const all = Object.assign({}, WRITABLE, COMPUTED);
  const cols = {};
  // заголовки таблицы заказов идут подряд вправо от «Дата заказа» до первой пустой ячейки
  for (let c = hc; c < lastCol && String(top[hr][c]).trim() !== ''; c++) {
    const h = norm_(top[hr][c]);
    for (const k in all) {
      if (!(k in cols) && h.indexOf(norm_(all[k])) === 0) cols[k] = c + 1;
    }
  }
  for (const k in WRITABLE) {
    if (!(k in cols)) throw new Error('не нашёл колонку «' + WRITABLE[k] + '»');
  }
  return { sh: sh, headerRow: hr + 1, cols: cols, top: top, lastCol: lastCol };
}

function rows_(t) {
  return Math.max(t.sh.getLastRow() - t.headerRow, 0);
}

function findOwn_(t, id) {
  const n = rows_(t);
  if (!n) return -1;
  const notes = t.sh.getRange(t.headerRow + 1, t.cols.date, n, 1).getNotes();
  for (let i = 0; i < n; i++) {
    if (notes[i][0] === MARK + id) return t.headerRow + 1 + i;
  }
  return -1;
}

function firstEmpty_(t) {
  // первая пустая строка ПОСЛЕ последней заполненной (дыры посреди таблицы не трогаем)
  const n = rows_(t);
  if (!n) return t.headerRow + 1;
  const d = t.sh.getRange(t.headerRow + 1, t.cols.date, n, 1).getValues();
  const m = t.sh.getRange(t.headerRow + 1, t.cols.model, n, 1).getValues();
  let last = -1;
  for (let i = 0; i < n; i++) {
    if (String(d[i][0]).trim() !== '' || String(m[i][0]).trim() !== '') last = i;
  }
  return t.headerRow + 2 + last;
}

function rowValues_(t, row) {
  const vals = t.sh.getRange(row, 1, 1, t.lastCol).getDisplayValues()[0];
  const res = {};
  for (const k in t.cols) res[k] = vals[t.cols[k] - 1];
  return res;
}

// ---------- запись ----------

function value_(k, v) {
  if (v === null || v === undefined || v === '') return '';
  if (DATE_FIELDS.indexOf(k) >= 0) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(v))) throw new Error('дата должна быть в виде ГГГГ-ММ-ДД: ' + v);
    // полночь в часовом поясе ТАБЛИЦЫ (не скрипта): иначе при разных поясах дата съезжает на день (проверено 23.09)
    return Utilities.parseDate(String(v), SpreadsheetApp.getActive().getSpreadsheetTimeZone(), 'yyyy-MM-dd');
  }
  if (MONEY_FIELDS.indexOf(k) >= 0) {
    const x = Number(v);
    if (!isFinite(x) || x < 0 || x > 1000000) throw new Error('странная сумма в «' + WRITABLE[k] + '»: ' + v);
    return x;
  }
  if (k === 'status' && STATUSES.indexOf(v) < 0) throw new Error('нет такого статуса: ' + v);
  return String(v);
}

// значения выпадающего списка ячейки: и набранные вручную (VALUE_IN_LIST), и взятые из диапазона ячеек
// (VALUE_IN_RANGE — так сделан список поставщиков); null — у ячейки нет списка
function allowedList_(cell) {
  const dv = cell.getDataValidation();
  if (!dv) return null;
  const type = dv.getCriteriaType();
  const crit = dv.getCriteriaValues();
  if (type === SpreadsheetApp.DataValidationCriteria.VALUE_IN_LIST) return crit[0].map(String);
  if (type === SpreadsheetApp.DataValidationCriteria.VALUE_IN_RANGE) {
    const out = [];
    crit[0].getDisplayValues().forEach(function (r) { r.forEach(function (x) { if (String(x).trim() !== '') out.push(String(x).trim()); }); });
    return out;
  }
  return null;
}

function writeCells_(t, row, fields) {
  const plan = [];
  for (const k in fields) {
    if (!(k in WRITABLE)) throw new Error('в колонку «' + k + '» писать нельзя');
    const cell = t.sh.getRange(row, t.cols[k]);
    if (cell.getFormula()) throw new Error('в ячейке «' + WRITABLE[k] + '» строки ' + row + ' формула — не трогаю');
    const val = value_(k, fields[k]);
    let v = val;
    let list = allowedList_(cell);
    if (k === 'supplier' && (!list || !list.length)) {
      // выпадающий список поставщиков в таблице ссылается на пустой диапазон («Памятка»!P27:P40, найдено 24.09) —
      // тогда сверяем с именами из блока «Поставщики» (там все поставщики, по ним считается заморозка)
      list = Object.keys(frozen_(t).frozen);
    }
    if (v !== '' && list) {
      // сравниваем без учёта регистра и лишних пробелов, а пишем значение ровно как в списке таблицы
      const hit = list.filter(function (x) { return soft_(x) === soft_(v); })[0];
      if (hit === undefined) {
        throw new Error('«' + v + '» нет в списке колонки «' + WRITABLE[k] + '» (в списке: ' + list.slice(0, 20).join(', ') + ')');
      }
      v = hit;
    }
    plan.push([cell, v]);
  }
  plan.forEach(function (p) { p[0].setValue(p[1]); });  // пишем, только если ВСЕ проверки прошли
}

// ---------- действия ----------

function ping_(t) {
  const names = {};
  for (const k in t.cols) names[k] = t.top[t.headerRow - 1][t.cols[k] - 1];
  const row = firstEmpty_(t);
  const lists = {};  // какие значения колонки принимают (выпадающие списки) — для проверки со стороны бота
  ['service', 'supplier', 'status'].forEach(function (k) {
    const cell = t.sh.getRange(row, t.cols[k]);
    const dv = cell.getDataValidation();
    lists[k] = { type: dv ? String(dv.getCriteriaType()) : 'нет списка',
                 range: dv && dv.getCriteriaType() === SpreadsheetApp.DataValidationCriteria.VALUE_IN_RANGE ?
                        dv.getCriteriaValues()[0].getA1Notation() + ' на листе «' + dv.getCriteriaValues()[0].getSheet().getName() + '»' : '',
                 values: allowedList_(cell) };
  });
  return { version: VERSION, sheet: SHEET_NAME, timezone: SpreadsheetApp.getActive().getSpreadsheetTimeZone(),
           header_row: t.headerRow, columns: names, first_empty: row, lists: lists };
}

function append_(t, req) {
  const id = String(req.id || '');
  if (!/^\d+$/.test(id)) throw new Error('нет номера заказа');
  const f = req.fields || {};
  ['date', 'model', 'supplier', 'status'].forEach(function (k) {
    if (!f[k]) throw new Error('не хватает поля «' + WRITABLE[k] + '»');
  });
  let row = findOwn_(t, id);
  if (row > 0 && String(t.sh.getRange(row, t.cols.model).getValue()).trim() !== '') {
    return { row: row, duplicate: true, values: rowValues_(t, row) };  // этот заказ уже записан — дубль не создаём
  }
  let newMonth = false;
  if (row < 0) {
    row = firstEmpty_(t);
    // первый заказ нового месяца: сначала пишем ЗАКАЗ строкой ниже (если проверки не пройдут — ничего не записано),
    // потом над ним заголовок месяца
    const key = Number(String(f.date).slice(0, 4)) * 100 + Number(String(f.date).slice(5, 7));
    const last = lastNonEmpty_(t);
    if (last && !(last.kind === 'header' && last.key === key) && last.key !== key) {
      writeCells_(t, row + 1, f);
      writeHeader_(t, row, key);
      row += 1;
      newMonth = true;
    }
  }
  if (!newMonth) writeCells_(t, row, f);
  t.sh.getRange(row, t.cols.date).setNote(MARK + id);
  SpreadsheetApp.flush();
  if (newMonth) {
    try { groupPast_(t); buildMonthly_(t); } catch (err) { /* порядок в таблице — не повод терять записанный заказ */ }
  }
  return { row: row, values: rowValues_(t, row), new_month: newMonth };
}

function update_(t, req) {
  const row = findOwn_(t, String(req.id));
  if (row < 0) throw new Error('заказ #' + req.id + ' не нашёлся в таблице (заметку «' + MARK + req.id + '» удалили?)');
  const allowed = ['status', 'track', 'service', 'money_date', 'avito_sum', 'paid_card', 'paid_frozen'];
  const f = req.fields || {};
  for (const k in f) {
    if (allowed.indexOf(k) < 0) throw new Error('менять «' + k + '» у записанного заказа нельзя');
  }
  writeCells_(t, row, f);
  SpreadsheetApp.flush();
  return { row: row, values: rowValues_(t, row) };
}

function returns_(t, req) {
  const n = rows_(t);
  const rows = n ? t.sh.getRange(t.headerRow + 1, 1, n, t.lastCol).getDisplayValues() : [];
  const res = [];
  rows.forEach(function (r, i) {
    if (r[t.cols.status - 1] === 'Возврат: у поставщика' && (!req.supplier || r[t.cols.supplier - 1] === req.supplier)) {
      res.push({ row: t.headerRow + 1 + i, date: r[t.cols.date - 1], model: r[t.cols.model - 1],
                 supplier: r[t.cols.supplier - 1], cost: t.cols.cost ? r[t.cols.cost - 1] : '',
                 frozen_out: t.cols.frozen_out ? r[t.cols.frozen_out - 1] : '' });
    }
  });
  return { returns: res };
}

function useReturn_(t, req) {
  const row = Number(req.row);
  if (!(row > t.headerRow)) throw new Error('нет строки');
  const r = t.sh.getRange(row, 1, 1, t.lastCol).getDisplayValues()[0];
  if (r[t.cols.model - 1] !== req.model || r[t.cols.supplier - 1] !== req.supplier ||
      r[t.cols.status - 1] !== 'Возврат: у поставщика') {
    throw new Error('строка ' + row + ' уже не та (модель/поставщик/статус изменились) — не трогаю');
  }
  writeCells_(t, row, { status: 'Возврат: отоварен' });
  SpreadsheetApp.flush();
  return { row: row, values: rowValues_(t, row) };
}

function frozen_(t) {
  const top = t.top;
  for (let r = 0; r < top.length; r++) {
    for (let c = 0; c < t.lastCol; c++) {
      if (norm_(top[r][c]) !== 'поставщик') continue;
      let lc = -1;
      for (let c2 = c + 1; c2 < t.lastCol; c2++) {
        if (norm_(top[r][c2]).indexOf('лежит') === 0) { lc = c2; break; }
      }
      if (lc < 0) continue;  // это заголовок таблицы заказов, а не блок «Поставщики»
      const res = {};
      for (let r2 = r + 1; r2 < top.length; r2++) {
        const name = String(top[r2][c]).trim();
        if (norm_(name) === 'итого') break;
        if (name) res[name] = top[r2][lc];
      }
      return { frozen: res };
    }
  }
  throw new Error('не нашёл блок «Поставщики» с колонкой «Лежит у него»');
}

function read_(t, req) {
  const row = findOwn_(t, String(req.id));
  if (row < 0) throw new Error('заказ #' + req.id + ' не нашёлся в таблице');
  return { row: row, values: rowValues_(t, row) };
}

function summary_(t) {
  // только чтение: верх листа (блоки «Прибыль», «Где деньги сейчас», «Рассрочка», «Поставщики») как он показан, и все
  // строки заказов (включая вписанные вручную) — бот сам находит нужные цифры по подписям
  const n = rows_(t);
  const vals = n ? t.sh.getRange(t.headerRow + 1, 1, n, t.lastCol).getDisplayValues() : [];
  const notes = n ? t.sh.getRange(t.headerRow + 1, t.cols.model, n, 1).getNotes() : [];
  const keys = Object.keys(t.cols);
  const rows = [];
  vals.forEach(function (r, i) {
    if (!String(r[t.cols.date - 1]).trim() && !String(r[t.cols.model - 1]).trim()) return;
    if (String(notes[i][0]).indexOf(MONTH_NOTE) === 0) return;  // строка-заголовок месяца — не заказ
    const o = { row: t.headerRow + 1 + i };
    keys.forEach(function (k) { o[k] = r[t.cols[k] - 1]; });
    rows.push(o);
  });
  return { top: t.top.slice(0, t.headerRow - 1), rows: rows, today: Utilities.formatDate(new Date(),
           SpreadsheetApp.getActive().getSpreadsheetTimeZone(), 'yyyy-MM-dd') };
}

// ---------- по месяцам (версия 7) ----------

function colLetter_(c) {
  let s = '';
  while (c > 0) { const m = (c - 1) % 26; s = String.fromCharCode(65 + m) + s; c = Math.floor((c - 1) / 26); }
  return s;
}

function tableWidth_(t) {  // последняя колонка таблицы заказов (A–N); правее — блоки, которые не трогаем
  let w = 0;
  for (const k in t.cols) w = Math.max(w, t.cols[k]);
  return w;
}

let SEP_ = null;
function sep_() {
  // разделитель аргументов формул зависит от языка таблицы: у русской — «;» (=СУММ(1;2)), у английской — «,».
  // Проверяем пробной формулой на листе «По месяцам» (26.09: формулы с запятыми в русской таблице дали #ERROR!)
  if (SEP_) return SEP_;
  const c = monthlySheet_().getRange('Z1');
  c.setFormula('=SUM(1,2)');
  SpreadsheetApp.flush();
  SEP_ = String(c.getDisplayValue()) === '3' ? ',' : ';';
  c.clearContent();
  return SEP_;
}

function toSep_(f) {  // формула, собранная с запятыми, -> с разделителем этой таблицы (запятые в кавычках не трогаем)
  if (sep_() === ',') return f;
  let out = '', dq = false, sq = false;
  for (let i = 0; i < f.length; i++) {
    const ch = f[i];
    if (ch === '"' && !sq) dq = !dq;
    else if (ch === "'" && !dq) sq = !sq;
    out += (ch === ',' && !dq && !sq) ? ';' : ch;
  }
  return out;
}

function monthlySheet_() {
  const ss = SpreadsheetApp.getActive();
  return ss.getSheetByName(MONTHLY_SHEET) || ss.insertSheet(MONTHLY_SHEET);
}

function monthKey_(d) { return d.getFullYear() * 100 + d.getMonth() + 1; }
function monthLabel_(k) { return MONTHS_RU[(k % 100) - 1] + ' ' + Math.floor(k / 100); }

function colRange_(t, k, sheetName) {  // «$A$41:$A» (или «'Расчёт'!$A$41:$A») — от первой строки данных до конца листа
  if (!t.cols[k]) return null;
  const c = colLetter_(t.cols[k]);
  return (sheetName ? "'" + sheetName + "'!" : '') + '$' + c + '$' + (t.headerRow + 1) + ':$' + c;
}

function scan_(t) {
  // строки таблицы заказов: header (заголовок месяца), order (есть дата), other (без даты, но что-то есть), empty
  const first = t.headerRow + 1, n = rows_(t);
  if (!n) return [];
  const dates = t.sh.getRange(first, t.cols.date, n, 1).getValues();
  const models = t.sh.getRange(first, t.cols.model, n, 1).getDisplayValues();
  const notes = t.sh.getRange(first, t.cols.model, n, 1).getNotes();
  const out = [];
  let lastKey = null;
  for (let i = 0; i < n; i++) {
    const note = String(notes[i][0] || ''), d = dates[i][0];
    if (note.indexOf(MONTH_NOTE) === 0) {
      lastKey = Number(note.slice(MONTH_NOTE.length));
      out.push({ row: first + i, kind: 'header', key: lastKey });
    } else if (d instanceof Date) {
      lastKey = monthKey_(d);
      out.push({ row: first + i, kind: 'order', key: lastKey });
    } else if (String(d).trim() || String(models[i][0]).trim()) {
      out.push({ row: first + i, kind: 'other', key: lastKey });  // дата текстом («06.09») — месяц соседей
    } else {
      out.push({ row: first + i, kind: 'empty', key: null });
    }
  }
  return out;
}

function lastNonEmpty_(t) {
  const rows = scan_(t).filter(function (r) { return r.kind !== 'empty'; });
  return rows.length ? rows[rows.length - 1] : null;
}

function writeHeader_(t, row, key) {
  const y = Math.floor(key / 100), m = key % 100;
  const S = 'DATE(' + y + ',' + m + ',1)', E = 'DATE(' + y + ',' + (m + 1) + ',1)';
  const A = colRange_(t, 'date'), K = colRange_(t, 'status'), L = colRange_(t, 'profit');
  const when = A + ',">="&' + S + ',' + A + ',"<"&' + E;
  const sold = 'COUNTIFS(' + when + ',' + K + ',"На Авито")+COUNTIFS(' + when + ',' + K + ',"Выведено")';
  const profit = L ? 'SUMIFS(' + L + ',' + when + ')' : '0';
  const f = '="' + monthLabel_(key) + ' — заказов "&COUNTIFS(' + when + ')&", продано "&(' + sold +
            ')&", прибыль "&FIXED(' + profit + ',0)&" ₽"';  // FIXED — разряды по языку таблицы («19 622»)
  const cell = t.sh.getRange(row, t.cols.model);
  cell.setFormula(toSep_(f)).setNote(MONTH_NOTE + key).setFontWeight('bold');
  t.sh.getRange(row, 1, 1, tableWidth_(t)).setBackground('#e8eaed');
}

function insertHeader_(t, row, key) {
  // сдвигаем вниз ТОЛЬКО ячейки таблицы заказов (A–N) — блок «Поставщики» справа остаётся на месте
  t.sh.getRange(row, 1, 1, tableWidth_(t)).insertCells(SpreadsheetApp.Dimension.ROWS);
  writeHeader_(t, row, key);
}

function rightBlockLastRow_(t) {
  // последняя строка (ниже заголовка таблицы), где справа от таблицы заказов что-то есть — её не сворачиваем
  const w = tableWidth_(t), n = rows_(t);
  const lastCol = t.sh.getLastColumn();
  if (!n || lastCol <= w) return 0;
  const r = t.sh.getRange(t.headerRow + 1, w + 1, n, lastCol - w);
  let last = 0;
  r.getValues().forEach(function (row, i) {
    if (row.some(function (x) { return String(x).trim() !== ''; })) last = t.headerRow + 1 + i;
  });
  r.getMergedRanges().forEach(function (m) { last = Math.max(last, m.getLastRow()); });
  return last;
}

function groupPast_(t) {
  // прошлые месяцы — в свёрнутые группы «+/−» (кнопка на строке-заголовке месяца); текущий — развёрнут
  const heads = scan_(t).filter(function (r) { return r.kind === 'header'; });
  const right = rightBlockLastRow_(t);
  t.sh.setRowGroupControlPosition(SpreadsheetApp.GroupControlTogglePosition.BEFORE);  // «+/−» — на строке-заголовке
  const done = [];
  for (let i = 0; i < heads.length - 1; i++) {
    const from = heads[i].row + 1, to = heads[i + 1].row - 1;
    if (to < from || from <= right) continue;
    if (t.sh.getRowGroupDepth(from) > 0) continue;  // уже в группе (пользователь мог развернуть — не трогаем)
    t.sh.getRange(from, 1, to - from + 1, 1).shiftRowGroupDepth(1);
    const g = t.sh.getRowGroup(from, 1);
    if (g) g.collapse();
    done.push(monthLabel_(heads[i].key));
  }
  return done;
}

function buildMonthly_(t) {
  const sh = monthlySheet_();
  const keys = [];
  scan_(t).forEach(function (r) { if (r.kind === 'order' && keys.indexOf(r.key) < 0) keys.push(r.key); });
  keys.sort();
  const A = colRange_(t, 'date', SHEET_NAME), K = colRange_(t, 'status', SHEET_NAME), H = colRange_(t, 'cost', SHEET_NAME),
        J = colRange_(t, 'avito_sum', SHEET_NAME), L = colRange_(t, 'profit', SHEET_NAME);
  const head = ['Месяц', 'Заказов', 'Продано', 'Едет', 'Возвратов', '% возвратов', 'Вложено', 'Получено с Авито', 'Прибыль',
                'Прибыль с пары'];
  const rows = keys.map(function (key, i) {
    const r = i + 2, y = Math.floor(key / 100), m = key % 100;
    const when = A + ',">="&DATE(' + y + ',' + m + ',1),' + A + ',"<"&DATE(' + y + ',' + (m + 1) + ',1)';
    const st = function (fn, rng, s) { return fn + '(' + (rng ? rng + ',' : '') + when + ',' + K + ',"' + s + '")'; };
    return [monthLabel_(key),
            '=COUNTIFS(' + when + ')',
            '=' + st('COUNTIFS', null, 'На Авито') + '+' + st('COUNTIFS', null, 'Выведено'),
            '=' + st('COUNTIFS', null, 'В процессе'),
            '=' + st('COUNTIFS', null, 'Возврат*'),
            '=IFERROR(E' + r + '/B' + r + ',0)',
            H ? '=SUMIFS(' + H + ',' + when + ')' : '',
            J ? '=' + st('SUMIFS', J, 'На Авито') + '+' + st('SUMIFS', J, 'Выведено') : '',
            L ? '=SUMIFS(' + L + ',' + when + ')' : '',
            '=IFERROR(I' + r + '/C' + r + ',0)'];
  });
  const tot = keys.length + 2, last = keys.length + 1;
  const sum = function (c) { return keys.length ? '=SUM(' + c + '2:' + c + last + ')' : '=0'; };
  rows.push(['Итого', sum('B'), sum('C'), sum('D'), sum('E'), '=IFERROR(E' + tot + '/B' + tot + ',0)', sum('G'), sum('H'),
             sum('I'), '=IFERROR(I' + tot + '/C' + tot + ',0)']);
  sep_();  // пробная формула — до очистки листа
  // подписи месяцев — значениями, остальное — формулами (setFormulas, как и пробная формула — одинаковый разбор)
  const labels = rows.map(function (r) { return [r[0]]; });
  const formulas = rows.map(function (r) { return r.slice(1).map(function (v) { return toSep_(v || '=0'); }); });
  sh.clear();
  sh.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold').setBackground('#e8eaed');
  sh.getRange(2, 1, labels.length, 1).setValues(labels);
  sh.getRange(2, 2, formulas.length, head.length - 1).setFormulas(formulas);
  sh.getRange(tot, 1, 1, head.length).setFontWeight('bold').setBackground('#e8eaed');
  sh.getRange(2, 6, rows.length, 1).setNumberFormat('0%');
  sh.getRange(2, 7, rows.length, 4).setNumberFormat('#,##0 "₽"');
  sh.setFrozenRows(1);
  sh.autoResizeColumns(1, head.length);
  sh.getRange('A1').setNote('Лист собирает скрипт SneakerFlow из листа «' + SHEET_NAME + '» (по дате заказа и статусу). ' +
                            'Руками не правь — при новом месяце он пересобирается.');
  return keys.map(monthLabel_);
}

function organize_(t) {
  // один раз для уже вписанных заказов (потом всё делает append): заголовки перед каждым месяцем, свёртка, «По месяцам»
  const added = [];
  for (let guard = 0; guard < 40; guard++) {
    const rows = scan_(t);
    let prev = null, target = null;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r.kind === 'header') { prev = r.key; continue; }
      if (r.kind === 'order' && r.key !== prev) { target = r; break; }
    }
    if (!target) break;
    insertHeader_(t, target.row, target.key);
    added.push(monthLabel_(target.key) + ' (строка ' + target.row + ')');
  }
  // уже стоящие заголовки — переписать формулу (исправление #ERROR! от запятых в русской таблице, 26.09)
  scan_(t).forEach(function (r) { if (r.kind === 'header') writeHeader_(t, r.row, r.key); });
  SpreadsheetApp.flush();
  const grouped = groupPast_(t);
  const months = buildMonthly_(t);
  SpreadsheetApp.flush();
  // проверка: ни одна наша формула не должна показывать ошибку
  const errors = [];
  scan_(t).forEach(function (r) {
    if (r.kind === 'header') {
      const v = String(t.sh.getRange(r.row, t.cols.model).getDisplayValue());
      if (v.charAt(0) === '#') errors.push('заголовок строки ' + r.row + ': ' + v);
    }
  });
  const m = monthlySheet_().getDataRange().getDisplayValues();
  m.forEach(function (row, i) { row.forEach(function (v, j) { if (String(v).charAt(0) === '#') errors.push('По месяцам ' + (i + 1) + ':' + (j + 1) + ' ' + v); }); });
  return { headers_added: added, grouped: grouped, monthly: months, separator: sep_(), errors: errors.slice(0, 10),
           sample: m.slice(0, 3) };
}

function monthlyAction_(t) {
  return { monthly: buildMonthly_(t) };
}

// ---------- убрать блок «Рассрочка» (версия 8) ----------

function removeInstallment_(t, req) {
  const EXPECT = ['свободный лимит', 'ближайший платеж', 'дата платежа', 'дней до платежа', 'вложено в товар за период'];
  const top = t.top, dry = !!req.dry;
  let r0 = -1, c0 = -1;
  for (let r = 0; r < t.headerRow - 1 && r0 < 0; r++) {
    for (let c = 0; c < top[r].length; c++) {
      if (soft_(top[r][c]).indexOf('рассрочка') === 0) { r0 = r; c0 = c; break; }
    }
  }
  const memo = cleanMemo_(true);
  if (r0 < 0) return { removed: false, reason: 'блока «Рассрочка» уже нет', memo: dry ? memo : cleanMemo_(false) };
  // строки блока: подписи под заголовком до первой пустой; подпись — в колонке заголовка (объединена на 3 ячейки)
  const labels = [];
  let r = r0 + 1;
  while (r < t.headerRow - 1 && String(top[r][c0]).trim() !== '') { labels.push(soft_(top[r][c0]).replace(/ё/g, 'е')); r++; }
  const unexpected = labels.filter(function (l) { return EXPECT.indexOf(l) < 0; });
  if (unexpected.length || labels.length !== EXPECT.length) {
    return { removed: false, reason: 'в блоке не те подписи — не трогаю', labels: labels };
  }
  // ширина блока: от колонки заголовка до последней непустой справа в этих строках (подпись + значение)
  let c1 = c0;
  for (let rr = r0; rr < r; rr++) {
    for (let c = c0; c < Math.min(top[rr].length, c0 + 6); c++) { if (String(top[rr][c]).trim() !== '') c1 = Math.max(c1, c); }
  }
  const rng = t.sh.getRange(r0 + 1, c0 + 1, r - r0, c1 - c0 + 1);
  const a1 = rng.getA1Notation();
  if (!dry) {
    rng.breakApart();
    rng.clear();                 // значения, формулы и оформление
    rng.clearDataValidations();
    cleanMemo_(false);
    SpreadsheetApp.flush();
  }
  return { removed: !dry, range: a1, labels: labels, memo: memo };
}

function cleanMemo_(dry) {
  // «Памятка»: строки про рассрочку (свободный лимит, ближайший платёж, дни до платежа) — стереть; заголовок про
  // «три жёлтые ячейки» -> «одну». Строки не удаляем (чтобы ничего не съехало), только текст.
  const sh = SpreadsheetApp.getActive().getSheetByName('Памятка');
  if (!sh) return [];
  const vals = sh.getDataRange().getDisplayValues();
  const done = [];
  vals.forEach(function (row, i) {
    row.forEach(function (v, j) {
      const s = soft_(v).replace(/ё/g, 'е');
      if (!s) return;
      if (s.indexOf('раз в неделю обновляешь три') === 0) {
        done.push('строка ' + (i + 1) + ': «' + v + '» -> «РАЗ В НЕДЕЛЮ ОБНОВЛЯЕШЬ ОДНУ ЖЁЛТУЮ ЯЧЕЙКУ»');
        if (!dry) sh.getRange(i + 1, j + 1).setValue('РАЗ В НЕДЕЛЮ ОБНОВЛЯЕШЬ ОДНУ ЖЁЛТУЮ ЯЧЕЙКУ');
      } else if (s.indexOf('свободный лимит') >= 0 || s.indexOf('ближайший платеж') >= 0 ||
                 s.indexOf('дней до платежа') >= 0) {
        done.push('строка ' + (i + 1) + ': стёрто «' + v + '»');
        if (!dry) sh.getRange(i + 1, 1, 1, row.length).clearContent();
      }
    });
  });
  return done;
}
