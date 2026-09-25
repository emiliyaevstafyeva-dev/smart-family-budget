/**
 * Финансовое ядро «Умный семейный бюджет».
 * Все суммы внутри — целые копейки. Свободные деньги = Cash − Reserved.
 * Накопления (25%) не входят в Cash и не используются для платежей.
 *
 * Порядок операций в один день: opening → incomes → arrears/reserve → payments → daily.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.BudgetCore = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const SAVINGS_RATE_NUM = 25;
  const SAVINGS_RATE_DEN = 100;
  const BUDGET_START = { year: 2026, month: 9, day: 1 };

  function absKey(y, m, d) {
    return y * 10000 + m * 100 + d;
  }

  const BUDGET_START_KEY = absKey(2026, 9, 1);

  function addMonths(y, m, delta) {
    const t = new Date(y, m - 1 + delta, 1);
    return { year: t.getFullYear(), month: t.getMonth() + 1 };
  }

  function dim(y, m) {
    return new Date(y, m, 0).getDate();
  }

  function monthKey(y, m) {
    return `${y}-${String(m).padStart(2, '0')}`;
  }

  function daysBetween(a, b) {
    const t =
      (new Date(b.year, b.month - 1, b.day) - new Date(a.year, a.month - 1, a.day)) /
      86400000;
    return Math.max(1, Math.round(t));
  }

  function daysInclusiveRemaining(from, toExclusive) {
    if (!toExclusive) {
      return Math.max(1, dim(from.year, from.month) - from.day + 1);
    }
    const diff =
      (new Date(toExclusive.year, toExclusive.month - 1, toExclusive.day) -
        new Date(from.year, from.month - 1, from.day)) /
      86400000;
    return Math.max(1, Math.round(diff));
  }

  /** Рубли → копейки (безопасное округление). */
  function toKop(rubles) {
    const n = Number(rubles);
    if (!Number.isFinite(n) || n <= 0) return 0;
    return Math.round(n * 100);
  }

  /** Копейки → рубли (число). */
  function fromKop(kop) {
    return (Number(kop) || 0) / 100;
  }

  /** 25% в накопления, 75% в бюджет; сумма частей = gross (без потери копейки). */
  function splitIncome(grossKop) {
    const savings = Math.floor((grossKop * SAVINGS_RATE_NUM) / SAVINGS_RATE_DEN);
    return { savings, usable: grossKop - savings };
  }

  function* eachDay(fromY, fromM, toY, toM) {
    let y = fromY;
    let mo = fromM;
    let d = 1;
    const endK = absKey(toY, toM, dim(toY, toM));
    while (true) {
      const maxD = dim(y, mo);
      for (; d <= maxD; d++) {
        const cell = {
          year: y,
          month: mo,
          day: d,
          key: absKey(y, mo, d),
          mKey: monthKey(y, mo)
        };
        yield cell;
        if (cell.key >= endK) return;
      }
      const n = addMonths(y, mo, 1);
      y = n.year;
      mo = n.month;
      d = 1;
    }
  }

  function monthsFromBudgetStart(selectedMonth, horizonMonths) {
    const horizon = horizonMonths == null ? 2 : horizonMonths;
    const end = addMonths(selectedMonth.year, selectedMonth.month, horizon);
    const selKey = monthKey(selectedMonth.year, selectedMonth.month);
    const endKey = monthKey(end.year, end.month);
    const list = [];
    let cur = { year: BUDGET_START.year, month: BUDGET_START.month };
    while (monthKey(cur.year, cur.month) <= endKey) {
      list.push({
        year: cur.year,
        month: cur.month,
        isSelected: monthKey(cur.year, cur.month) === selKey
      });
      cur = addMonths(cur.year, cur.month, 1);
    }
    return list;
  }

  function parseDateParts(dateStr) {
    if (!dateStr) return null;
    const d = new Date(String(dateStr) + 'T12:00:00');
    if (Number.isNaN(d.getTime())) return null;
    return { year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate() };
  }

  /**
   * @param {object} input
   * @param {number} input.openingBalanceRubles
   * @param {Array} input.incomeRows — {name, day, amount} шаблон
   * @param {function} input.getIncomeAmount — (idx, year, month) → рубли
   * @param {Array} input.fixedRows — {name, day, amount}
   * @param {Array} input.onceRows — {name, date, amount}
   * @param {{year,month,days}} input.selectedMonth
   * @param {Array} input.dailyExpenses — {id?, name, date|year/month/day, amount} в рублях
   * @param {function} [input.isMonthLocked]
   * @param {number} [input.viewDay] — день «сегодня» в выбранном месяце (1..days)
   */
  function buildChronology(input) {
    const selectedMonth = input.selectedMonth;
    const selKey = monthKey(selectedMonth.year, selectedMonth.month);
    const months = monthsFromBudgetStart(selectedMonth);
    const endMonth = months[months.length - 1];
    const isMonthLocked = input.isMonthLocked || (() => false);
    const getIncomeAmount = input.getIncomeAmount;

    const incomeEvents = [];
    months.forEach(({ year, month, isSelected }) => {
      const days = dim(year, month);
      (input.incomeRows || []).forEach((inc, i) => {
        const amountRub = getIncomeAmount
          ? getIncomeAmount(i, year, month)
          : Number(inc.amount) || 0;
        const amount = toKop(amountRub);
        if (amount <= 0) return;
        const day = Math.min(Math.max(1, Math.round(Number(inc.day) || 1)), days);
        const key = absKey(year, month, day);
        if (key < BUDGET_START_KEY) return;
        incomeEvents.push({
          id: `inc-${year}-${month}-${i}`,
          incomeIndex: i,
          name: inc.name || 'Доход',
          year,
          month,
          day,
          key,
          mKey: monthKey(year, month),
          amount,
          isSelectedMonth: isSelected,
          isFact: isMonthLocked(year, month)
        });
      });
    });
    incomeEvents.sort((a, b) => a.key - b.key || a.incomeIndex - b.incomeIndex);

    const obligations = [];
    months.forEach(({ year, month, isSelected }) => {
      const days = dim(year, month);
      (input.fixedRows || []).forEach((fix, i) => {
        const amount = toKop(fix.amount);
        if (amount <= 0) return;
        const day = Math.min(Math.max(1, Math.round(Number(fix.day) || 1)), days);
        const key = absKey(year, month, day);
        if (key < BUDGET_START_KEY) return;
        obligations.push({
          id: `fix-${i}-${year}-${month}`,
          fixIndex: i,
          name: fix.name || 'Постоянный платеж',
          year,
          month,
          day,
          key,
          mKey: monthKey(year, month),
          amount,
          priority: 1,
          kind: 'Постоянный платеж',
          isSelectedMonth: isSelected,
          sourceIndex: i
        });
      });
    });

    (input.onceRows || []).forEach((o, i) => {
      const amount = toKop(o.amount);
      const parts = parseDateParts(o.date);
      if (amount <= 0 || !parts) return;
      const key = absKey(parts.year, parts.month, parts.day);
      if (key < BUDGET_START_KEY) return;
      if (monthKey(parts.year, parts.month) > monthKey(endMonth.year, endMonth.month)) return;
      obligations.push({
        id: `once-${i}`,
        onceIndex: i,
        name: o.name || 'Крупный расход',
        year: parts.year,
        month: parts.month,
        day: parts.day,
        key,
        mKey: monthKey(parts.year, parts.month),
        amount,
        priority: 2,
        kind: 'Крупный разовый',
        isSelectedMonth: monthKey(parts.year, parts.month) === selKey,
        sourceIndex: i
      });
    });

    obligations.sort(
      (a, b) => a.key - b.key || a.priority - b.priority || String(a.id).localeCompare(String(b.id))
    );

    const daily = normalizeDaily(input.dailyExpenses || [], selKey);

    return {
      incomeEvents,
      obligations,
      dailyExpenses: daily,
      selKey,
      openingBalance: toKop(input.openingBalanceRubles),
      simEnd: endMonth,
      selectedMonth,
      viewDay: clampViewDay(input.viewDay, selectedMonth)
    };
  }

  function clampViewDay(viewDay, selectedMonth) {
    const days = selectedMonth.days || dim(selectedMonth.year, selectedMonth.month);
    if (viewDay == null) return 1;
    return Math.min(Math.max(1, Math.round(Number(viewDay) || 1)), days);
  }

  function normalizeDaily(rows, selKey) {
    const out = [];
    rows.forEach((x, i) => {
      let parts = null;
      if (x.year && x.month && x.day) {
        parts = { year: x.year, month: x.month, day: x.day };
      } else {
        parts = parseDateParts(x.date);
      }
      const amount = toKop(x.amount);
      if (!parts || amount <= 0) return;
      const mKey = monthKey(parts.year, parts.month);
      if (selKey && mKey !== selKey) return;
      out.push({
        id: x.id || `daily-${i}`,
        name: x.name || 'Расход',
        year: parts.year,
        month: parts.month,
        day: parts.day,
        key: absKey(parts.year, parts.month, parts.day),
        mKey,
        amount
      });
    });
    out.sort((a, b) => a.key - b.key || String(a.id).localeCompare(String(b.id)));
    return out;
  }

  function nextIncomeAfter(incomeEvents, key) {
    return incomeEvents.find((e) => e.key > key) || null;
  }

  function isMandatoryForIncome(ob, incKey, nextKey) {
    // Платёж в день дохода обеспечивается этим доходом (оплата идёт после поступления).
    // Далее — всё до следующего дохода (не включая день следующего дохода).
    if (ob.key < incKey) return false;
    if (ob.key === incKey) return true;
    if (nextKey == null) return true;
    return ob.key < nextKey;
  }

  /**
   * Максимальный равномерный дневной лимит L (копейки), при котором
   * все обязательства оплачиваются вовремя без траты накоплений.
   * Бинарный поиск + жадное резервирование ближайших платежей.
   */
  function findMaxSafeDailyLimit(chronology) {
    const { incomeEvents, obligations, openingBalance, dailyExpenses, simEnd } = chronology;
    let hi = openingBalance;
    incomeEvents.forEach((e) => {
      hi += splitIncome(e.amount).usable;
    });
    hi = Math.max(0, hi);

    let lo = 0;
    let best = 0;
    while (lo <= hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (canAffordWithDaily(chronology, mid)) {
        best = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return best;
  }

  function canAffordWithDaily(chronology, dailyLimitKop) {
    const result = simulate(chronology, {
      targetDailyLimit: dailyLimitKop,
      strictFeasibility: true,
      recordHistory: false
    });
    return result.feasible;
  }

  /**
   * Основная симуляция.
   * @param {object} chronology
   * @param {object} [opts]
   * @param {number} [opts.targetDailyLimit] — защищаемый дневной бюджет (коп.)
   * @param {boolean} [opts.strictFeasibility] — true: не резервировать optional ниже защиты; проверять denficit
   * @param {boolean} [opts.recordHistory]
   */
  function simulate(chronology, opts) {
    opts = opts || {};
    const recordHistory = opts.recordHistory !== false;
    const targetDaily = opts.targetDailyLimit == null ? 0 : opts.targetDailyLimit;
    const strict = !!opts.strictFeasibility;

    const { incomeEvents, obligations, dailyExpenses, selKey, openingBalance, simEnd } =
      chronology;
    const warnings = [];
    const history = [];
    const incomeCards = [];
    const reserves = Object.create(null);
    const paid = new Set();
    /** @type {Array<{id,name,year,month,day,key,mKey,amount,kind,originalId}>} */
    const arrears = [];
    const processedRemaining = new Map();

    let cash = 0;
    let savings = 0;
    let totalPaid = 0;
    let totalSpent = 0;
    let totalArrearsPaid = 0;
    let openingDone = false;
    let feasible = true;
    let peakDeficit = 0;

    function getReserve(id) {
      return reserves[id] || 0;
    }

    function reservedTotal() {
      let s = 0;
      for (const k in reserves) s += reserves[k];
      return s;
    }

    function freeCash() {
      return cash - reservedTotal();
    }

    function addWarning(key, payload) {
      if (warnings.some((w) => w.key === key)) return;
      warnings.push(Object.assign({ key }, payload));
    }

    function recordAllocation(raw, ob, prevRes, part, mandatory) {
      const newRes = prevRes + part;
      reserves[ob.id] = newRes;
      raw.push({
        paymentId: ob.id,
        name: ob.name,
        dueYear: ob.year,
        dueMonth: ob.month,
        dueDay: ob.day,
        dueKey: ob.key,
        amount: part,
        previousReserve: prevRes,
        newReserve: newRes,
        total: ob.amount,
        kind: ob.kind,
        targetMonthKey: ob.mKey,
        mandatory
      });
    }

    function repayArrears(cell) {
      arrears.sort(
        (a, b) => a.key - b.key || String(a.id).localeCompare(String(b.id))
      );
      for (let i = 0; i < arrears.length; ) {
        const a = arrears[i];
        const free = freeCash();
        if (free <= 0) break;
        const pay = Math.min(a.amount, free);
        cash -= pay;
        a.amount -= pay;
        totalArrearsPaid += pay;
        totalPaid += pay;
        if (recordHistory) {
          history.push({
            type: 'arrears_payment',
            year: cell.year,
            month: cell.month,
            day: cell.day,
            key: cell.key,
            mKey: cell.mKey,
            name: a.name + ' (просрочка)',
            amount: pay,
            remaining: a.amount
          });
        }
        if (a.amount <= 0) {
          paid.add(a.originalId);
          arrears.splice(i, 1);
        } else {
          i++;
        }
      }
    }

    function allocateFromIncome(inc) {
      const { savings: savAmt, usable } = splitIncome(inc.amount);
      savings += savAmt;
      cash += usable;

      const reserveAtStart = Object.create(null);
      obligations.forEach((o) => {
        reserveAtStart[o.id] = getReserve(o.id);
      });

      // Сначала погашаем просрочки из свободных после дохода.
      repayArrears(inc);

      const next = nextIncomeAfter(incomeEvents, inc.key);
      const nextKey = next ? next.key : null;
      const daysUntilNext = daysInclusiveRemaining(inc, next);
      const livingProtect = targetDaily * daysUntilNext;

      const rawAllocations = [];

      const unpaidNeed = (ob) => Math.max(0, ob.amount - getReserve(ob.id));

      const mandatoryObs = obligations
        .filter(
          (o) =>
            !paid.has(o.id) &&
            !arrears.some((a) => a.originalId === o.id) &&
            isMandatoryForIncome(o, inc.key, nextKey) &&
            unpaidNeed(o) > 0
        )
        .sort(
          (a, b) =>
            a.key - b.key || a.priority - b.priority || String(a.id).localeCompare(String(b.id))
        );

      let mandatoryNeed = 0;
      mandatoryObs.forEach((ob) => {
        mandatoryNeed += unpaidNeed(ob);
      });

      // 1) Ближайшие обязательства до следующего дохода — полный приоритет.
      mandatoryObs.forEach((ob) => {
        const prevRes = getReserve(ob.id);
        const need = unpaidNeed(ob);
        const free = freeCash();
        if (need <= 0 || free <= 0) return;
        const part = Math.min(need, free);
        recordAllocation(rawAllocations, ob, prevRes, part, true);
      });

      let mandatoryShortfall = 0;
      mandatoryObs.forEach((ob) => {
        const gap = unpaidNeed(ob);
        if (gap > 0) mandatoryShortfall += gap;
      });
      if (mandatoryShortfall > 0) {
        feasible = false;
        peakDeficit = Math.max(peakDeficit, mandatoryShortfall);
        if (recordHistory) {
          addWarning(`gap-${inc.id}`, {
            day: inc.day,
            monthKey: inc.mKey,
            message:
              `Недостаточно средств до следующего дохода после «${inc.name}». ` +
              `Обязательные платежи до следующего дохода: ${fmtRub(mandatoryNeed)}. ` +
              `Доступно: ${fmtRub(usable)}. Не хватает: ${fmtRub(mandatoryShortfall)}.`
          });
        }
      }

      // 2) Более поздние — только из излишка сверх защищённого дневного бюджета.
      // Излишек сверх защищённого дневного бюджета → ближайшие более поздние платежи.
      // Полное покрытие необязательно: следующий доход до срока сделает платёж mandatory.
      const freeAfter = freeCash();
      let pool = Math.max(0, freeAfter - livingProtect);

      const optionalObs = obligations
        .filter(
          (o) =>
            !paid.has(o.id) &&
            !arrears.some((a) => a.originalId === o.id) &&
            o.key > inc.key &&
            !isMandatoryForIncome(o, inc.key, nextKey) &&
            unpaidNeed(o) > 0
        )
        .sort(
          (a, b) =>
            a.key - b.key || a.priority - b.priority || String(a.id).localeCompare(String(b.id))
        );

      optionalObs.forEach((ob) => {
        if (pool <= 0) return;
        const prevRes = getReserve(ob.id);
        const need = unpaidNeed(ob);
        if (need <= 0) return;
        const part = Math.min(need, pool);
        // Не размазываем пыль копеек по отдалённым платежам — оставляем в Free Cash.
        if (part < 100 && part < need) return;
        if (part <= 0) return;
        recordAllocation(rawAllocations, ob, prevRes, part, false);
        pool -= part;
      });

      const remainingFree = freeCash();
      processedRemaining.set(inc.id, remainingFree);

      // Для подбора L: после mandatory свободных должно хватить на жизнь до следующего дохода.
      if (strict && targetDaily > 0 && remainingFree < livingProtect) {
        feasible = false;
      }

      const displayItems = buildDisplayItems(
        obligations,
        paid,
        arrears,
        reserveAtStart,
        rawAllocations,
        inc,
        nextKey,
        getReserve
      );

      displayItems
        .filter((o) => o.dueBeforeNextIncome && !o.fullyFunded)
        .forEach((o) => {
          if (recordHistory) {
            addWarning(`under-${inc.id}-${o.paymentId}`, {
              day: inc.day,
              monthKey: inc.mKey,
              message:
                `После «${inc.name}» платёж «${o.name}» (${fmtAbs(o.dueYear, o.dueMonth, o.dueDay)}) ` +
                `не обеспечен полностью: ${fmtRub(o.newReserve)} / ${fmtRub(o.total)}.`
            });
          }
        });

      const card = {
        id: inc.id,
        type: 'income',
        name: inc.name,
        year: inc.year,
        month: inc.month,
        day: inc.day,
        key: inc.key,
        mKey: inc.mKey,
        isSelectedMonth: inc.isSelectedMonth,
        isFact: inc.isFact,
        gross: inc.amount,
        savings: savAmt,
        usable,
        remaining: remainingFree,
        totalReserve: rawAllocations.reduce((s, a) => s + a.amount, 0),
        allocations: displayItems,
        freeCash: remainingFree,
        nextIncomeKey: nextKey,
        livingProtect,
        daysUntilNext
      };
      incomeCards.push(card);

      if (recordHistory) {
        history.push({
          type: 'income',
          year: inc.year,
          month: inc.month,
          day: inc.day,
          key: inc.key,
          mKey: inc.mKey,
          name: inc.name,
          gross: inc.amount,
          savings: savAmt,
          usable,
          sourceId: inc.id,
          allocations: displayItems.map((a) => Object.assign({}, a))
        });
        displayItems
          .filter((d) => d.amount > 0)
          .forEach((d) => {
            history.push({
              type: 'reserve',
              year: inc.year,
              month: inc.month,
              day: inc.day,
              key: inc.key,
              mKey: inc.mKey,
              name: d.name,
              amount: d.amount,
              paymentId: d.paymentId,
              previousReserve: d.previousReserve,
              newReserve: d.newReserve,
              total: d.total,
              description: `Резерв «${d.name}»: ${fmtRub(d.previousReserve)} + ${fmtRub(d.amount)} = ${fmtRub(d.newReserve)} / ${fmtRub(d.total)}`
            });
          });
      }
    }

    function payObligations(cell) {
      const due = obligations
        .filter(
          (o) =>
            o.key === cell.key &&
            !paid.has(o.id) &&
            !arrears.some((a) => a.originalId === o.id)
        )
        .sort(
          (a, b) =>
            a.priority - b.priority || String(a.id).localeCompare(String(b.id))
        );

      due.forEach((payment) => {
        const reserved = getReserve(payment.id);
        const otherReserved = reservedTotal() - reserved;
        const available = Math.max(0, cash - otherReserved);
        const pay = Math.min(payment.amount, available);

        if (pay > 0) {
          cash -= pay;
          totalPaid += pay;
        }
        delete reserves[payment.id];

        if (pay >= payment.amount) {
          paid.add(payment.id);
          if (recordHistory) {
            history.push({
              type: 'payment',
              year: cell.year,
              month: cell.month,
              day: cell.day,
              key: cell.key,
              mKey: cell.mKey,
              name: payment.name,
              amount: pay
            });
          }
        } else {
          const shortage = payment.amount - pay;
          feasible = false;
          peakDeficit = Math.max(peakDeficit, shortage);
          arrears.push({
            id: `arrears-${payment.id}`,
            originalId: payment.id,
            name: payment.name,
            year: payment.year,
            month: payment.month,
            day: payment.day,
            key: payment.key,
            mKey: payment.mKey,
            amount: shortage,
            kind: payment.kind
          });
          if (recordHistory) {
            if (pay > 0) {
              history.push({
                type: 'payment',
                year: cell.year,
                month: cell.month,
                day: cell.day,
                key: cell.key,
                mKey: cell.mKey,
                name: payment.name,
                amount: pay
              });
            }
            history.push({
              type: 'arrears',
              year: cell.year,
              month: cell.month,
              day: cell.day,
              key: cell.key,
              mKey: cell.mKey,
              name: payment.name,
              amount: shortage
            });
            addWarning(`pay-${payment.id}`, {
              day: payment.day,
              monthKey: payment.mKey,
              message:
                `К дате оплаты «${payment.name}» (${fmtAbs(payment.year, payment.month, payment.day)}) ` +
                `не хватило ${fmtRub(shortage)} — образовалась просрочка.`
            });
          }
        }
      });
    }

    function processDaily(cell) {
      if (cell.mKey !== selKey) return;
      dailyExpenses
        .filter((e) => e.key === cell.key)
        .forEach((expense) => {
          const free = freeCash();
          if (free >= expense.amount) {
            cash -= expense.amount;
            totalSpent += expense.amount;
            if (recordHistory) {
              history.push({
                type: 'daily_expense',
                year: cell.year,
                month: cell.month,
                day: cell.day,
                key: cell.key,
                mKey: cell.mKey,
                name: expense.name,
                amount: expense.amount
              });
            }
          } else {
            feasible = false;
            const over = expense.amount - Math.max(0, free);
            peakDeficit = Math.max(peakDeficit, over);
            if (free > 0) {
              cash -= free;
              totalSpent += free;
              if (recordHistory) {
                history.push({
                  type: 'daily_expense',
                  year: cell.year,
                  month: cell.month,
                  day: cell.day,
                  key: cell.key,
                  mKey: cell.mKey,
                  name: expense.name,
                  amount: free
                });
              }
            }
            if (recordHistory) {
              addWarning(`daily-${expense.id}-${cell.key}`, {
                day: cell.day,
                monthKey: cell.mKey,
                message:
                  `«${expense.name}» на ${fmtRub(expense.amount)} превышает свободный остаток ${fmtRub(free)}. ` +
                  `Резервы обязательных платежей не тронуты. Дефицит: ${fmtRub(over)}.`
              });
            }
          }
        });
    }

    const { year: endY, month: endM } = simEnd;

    for (const cell of eachDay(BUDGET_START.year, BUDGET_START.month, endY, endM)) {
      if (cell.key === BUDGET_START_KEY && openingBalance > 0 && !openingDone) {
        cash += openingBalance;
        openingDone = true;
        if (recordHistory) {
          history.push({
            type: 'opening',
            year: cell.year,
            month: cell.month,
            day: cell.day,
            key: cell.key,
            mKey: cell.mKey,
            name: 'Остаток на 1 сентября 2026',
            gross: openingBalance,
            usable: openingBalance
          });
        }
      }

      // Порядок дня: доходы → погашение просрочек внутри allocate → оплаты → бытовые
      incomeEvents.filter((e) => e.key === cell.key).forEach(allocateFromIncome);
      payObligations(cell);
      processDaily(cell);

      if (recordHistory && cell.mKey === selKey) {
        const nInc = incomeEvents.find((e) => e.mKey === selKey && e.key > cell.key);
        const days = nInc
          ? daysInclusiveRemaining(cell, nInc)
          : Math.max(1, dim(cell.year, cell.month) - cell.day + 1);
        const free = freeCash();
        const safeDaily = free > 0 ? Math.floor(free / days) : 0;
        history.push({
          type: 'day_end',
          year: cell.year,
          month: cell.month,
          day: cell.day,
          key: cell.key,
          mKey: cell.mKey,
          cash,
          reserved: reservedTotal(),
          free,
          savings,
          arrearsTotal: arrears.reduce((s, a) => s + a.amount, 0),
          dailyLimit: safeDaily,
          untilKey: nInc ? nInc.key : null,
          untilDay: nInc ? nInc.day : null,
          untilYear: nInc ? nInc.year : null,
          untilMonth: nInc ? nInc.month : null
        });
      }
    }

    // Инварианты резервов по карточкам
    const validationErrors = [];
    incomeCards.forEach((card) => {
      card.allocations.forEach((a) => {
        if (a.previousReserve + a.amount !== a.newReserve) {
          validationErrors.push(
            `${card.name} · ${a.name}: ${a.previousReserve}+${a.amount}≠${a.newReserve}`
          );
        }
        if (a.newReserve > a.total) {
          validationErrors.push(`${a.name}: резерв ${a.newReserve} > суммы ${a.total}`);
        }
      });
    });
    validationErrors.forEach((msg, i) => {
      addWarning(`validation-${i}`, { message: `Ошибка расчёта: ${msg}` });
    });

    const arrearsTotal = arrears.reduce((s, a) => s + a.amount, 0);
    if (arrearsTotal > 0) feasible = false;

    return {
      cash,
      savings,
      reserved: reservedTotal(),
      free: freeCash(),
      paid: totalPaid,
      everydaySpent: totalSpent,
      arrearsTotal,
      arrears: arrears.map((a) => Object.assign({}, a)),
      deficit: peakDeficit,
      feasible,
      targetDailyLimit: targetDaily,
      warnings,
      history,
      incomeCards,
      selKey,
      chronology,
      validationErrors,
      totalArrearsPaid
    };
  }

  function buildDisplayItems(
    obligations,
    paid,
    arrears,
    reserveAtStart,
    rawAllocations,
    inc,
    nextKey,
    getReserve
  ) {
    return obligations
      .filter(
        (o) =>
          !paid.has(o.id) &&
          !arrears.some((a) => a.originalId === o.id) &&
          o.key >= inc.key &&
          (rawAllocations.some((a) => a.paymentId === o.id) ||
            (reserveAtStart[o.id] || 0) > 0 ||
            isMandatoryForIncome(o, inc.key, nextKey))
      )
      .sort(
        (a, b) =>
          a.key - b.key || a.priority - b.priority || String(a.id).localeCompare(String(b.id))
      )
      .map((o) => {
        const alloc = rawAllocations.find((a) => a.paymentId === o.id);
        const prev = reserveAtStart[o.id] || 0;
        const add = alloc ? alloc.amount : 0;
        const after = alloc ? alloc.newReserve : prev;
        const mandatory = isMandatoryForIncome(o, inc.key, nextKey);
        return {
          paymentId: o.id,
          name: o.name,
          dueYear: o.year,
          dueMonth: o.month,
          dueDay: o.day,
          dueKey: o.key,
          previousReserve: prev,
          amount: add,
          newReserve: after,
          total: o.amount,
          kind: o.kind,
          targetMonthKey: o.mKey,
          remainingToFund: Math.max(0, o.amount - after),
          fullyFunded: after >= o.amount,
          mandatory,
          dueBeforeNextIncome: mandatory
        };
      });
  }

  function fmtRub(kop) {
    const rub = Math.round(fromKop(kop));
    return (
      new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(rub) + ' ₽'
    );
  }

  function fmtAbs(y, m, d) {
    return new Date(y, m - 1, d).toLocaleDateString('ru-RU', {
      day: 'numeric',
      month: 'long'
    });
  }

  /**
   * Полный пересчёт плана: подбирает безопасный дневной лимит и симулирует.
   */
  function calculateBudget(input) {
    const chronology = buildChronology(input);
    const safeDaily = findMaxSafeDailyLimit(chronology);
    const result = simulate(chronology, {
      targetDailyLimit: safeDaily,
      strictFeasibility: false,
      recordHistory: true
    });
    result.safeDailyLimit = safeDaily;
    result.viewSnapshot = pickViewSnapshot(result, chronology);
    result.monthEndSnapshot = pickMonthEndSnapshot(result, chronology);
    return toRublesView(result);
  }

  function pickViewSnapshot(result, chronology) {
    const selKey = chronology.selKey;
    const day = chronology.viewDay || 1;
    const snap = result.history
      .filter((h) => h.type === 'day_end' && h.mKey === selKey && h.day === day)
      .pop();
    return snap || result.history.filter((h) => h.type === 'day_end' && h.mKey === selKey).pop();
  }

  function pickMonthEndSnapshot(result, chronology) {
    return result.history
      .filter((h) => h.type === 'day_end' && h.mKey === chronology.selKey)
      .pop();
  }

  function mapKopFields(obj, fields) {
    if (!obj) return obj;
    const out = Object.assign({}, obj);
    fields.forEach((f) => {
      if (out[f] != null) out[f] = fromKop(out[f]);
    });
    return out;
  }

  function toRublesView(result) {
    const moneyFields = [
      'cash',
      'savings',
      'reserved',
      'free',
      'paid',
      'everydaySpent',
      'arrearsTotal',
      'deficit',
      'safeDailyLimit',
      'targetDailyLimit',
      'totalArrearsPaid',
      'gross',
      'usable',
      'amount',
      'previousReserve',
      'newReserve',
      'total',
      'remainingToFund',
      'remaining',
      'totalReserve',
      'freeCash',
      'livingProtect',
      'dailyLimit'
    ];

    function convertDeep(node) {
      if (Array.isArray(node)) return node.map(convertDeep);
      if (!node || typeof node !== 'object') return node;
      const out = {};
      Object.keys(node).forEach((k) => {
        const v = node[k];
        if (moneyFields.indexOf(k) >= 0 && typeof v === 'number') {
          out[k] = fromKop(v);
        } else if (k === 'allocations' || k === 'history' || k === 'incomeCards' || k === 'arrears' || k === 'warnings') {
          out[k] = convertDeep(v);
        } else if (k === 'viewSnapshot' || k === 'monthEndSnapshot') {
          out[k] = convertDeep(v);
        } else if (k === 'chronology') {
          out[k] = v; // оставляем в копейках для отладки
        } else {
          out[k] = v;
        }
      });
      return out;
    }

    const rub = convertDeep(result);
    rub._kop = {
      cash: result.cash,
      savings: result.savings,
      reserved: result.reserved,
      free: result.free,
      paid: result.paid,
      everydaySpent: result.everydaySpent,
      arrearsTotal: result.arrearsTotal,
      deficit: result.deficit
    };
    return rub;
  }

  /** Инварианты (в копейках). */
  function checkInvariants(result, inputSummary) {
    const errors = [];
    const cash = result.cash;
    const reserved = result.reserved;
    const free = result.free;
    if (cash !== reserved + free) {
      errors.push(`Cash ≠ Reserved + FreeCash: ${cash} ≠ ${reserved}+${free}`);
    }

    (result.incomeCards || []).forEach((card) => {
      if (card.gross !== card.savings + card.usable) {
        errors.push(
          `Доход ${card.name}: ${card.gross} ≠ ${card.savings}+${card.usable}`
        );
      }
    });

    if (inputSummary) {
      const expected =
        inputSummary.openingKop +
        inputSummary.usableIncomesKop -
        result.paid -
        result.everydaySpent;
      // paid включает оплаты обязательств и просрочек; cash конечный должен совпасть
      // с учётом того, что reserves всё ещё в cash.
      // opening + usable - paid - spent = cash (конечный)
      if (expected !== cash) {
        errors.push(
          `Баланс: opening+usable-paid-spent=${expected}, cash=${cash}`
        );
      }
    }

    return errors;
  }

  return {
    SAVINGS_RATE_NUM,
    SAVINGS_RATE_DEN,
    BUDGET_START,
    BUDGET_START_KEY,
    absKey,
    addMonths,
    dim,
    monthKey,
    daysBetween,
    daysInclusiveRemaining,
    toKop,
    fromKop,
    splitIncome,
    eachDay,
    monthsFromBudgetStart,
    parseDateParts,
    buildChronology,
    findMaxSafeDailyLimit,
    simulate,
    calculateBudget,
    checkInvariants,
    fmtRub,
    fmtAbs,
    isMandatoryForIncome
  };
});
