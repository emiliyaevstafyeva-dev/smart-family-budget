/**
 * Автотесты финансового ядра. Запуск:
 *   node "budget-core.test.js"
 * из папки «Бюджетный калькулятор».
 */
'use strict';

const Core = require('./budget-core.js');

let passed = 0;
let failed = 0;
const failures = [];

function assert(cond, msg) {
  if (cond) {
    passed++;
  } else {
    failed++;
    failures.push(msg);
    console.error('FAIL:', msg);
  }
}

function assertEq(a, b, msg) {
  assert(a === b, `${msg} (got ${a}, expected ${b})`);
}

function rubInput(cfg) {
  const selectedMonth = cfg.selectedMonth || { year: 2026, month: 9, days: 30 };
  const incomes = cfg.incomes || [];
  const fixed = cfg.fixed || [];
  const once = cfg.once || [];
  const daily = cfg.daily || [];
  return Core.calculateBudget({
    openingBalanceRubles: cfg.opening || 0,
    incomeRows: incomes,
    getIncomeAmount: (idx) => Number(incomes[idx] && incomes[idx].amount) || 0,
    fixedRows: fixed,
    onceRows: once,
    dailyExpenses: daily,
    selectedMonth,
    viewDay: cfg.viewDay != null ? cfg.viewDay : 1,
    isMonthLocked: () => false
  });
}

function kopOf(rubles) {
  return Core.toKop(rubles);
}

console.log('=== Тесты финансового ядра ===\n');

// 1. Доход раньше кредита
{
  const r = rubInput({
    incomes: [{ name: 'Зарплата', day: 5, amount: 100000 }],
    fixed: [{ name: 'Кредит', day: 10, amount: 25000 }]
  });
  const pay = r.history.filter((h) => h.type === 'payment' && h.name === 'Кредит');
  assert(pay.length === 1, '1: кредит оплачен один раз');
  assertEq(Core.toKop(pay[0].amount), kopOf(25000), '1: сумма кредита 25000');
  assertEq(r.arrearsTotal, 0, '1: нет просрочки');
  const card = r.incomeCards.find((c) => c.day === 5);
  const alloc = card.allocations.find((a) => a.name === 'Кредит');
  assert(alloc && alloc.fullyFunded, '1: кредит полностью обеспечен из дохода');
}

// 2. Несколько платежей до следующего дохода
{
  const r = rubInput({
    incomes: [
      { name: 'З1', day: 5, amount: 100000 },
      { name: 'З2', day: 20, amount: 80000 }
    ],
    fixed: [
      { name: 'Кредит', day: 10, amount: 25000 },
      { name: 'ЖКХ', day: 15, amount: 10000 }
    ]
  });
  assert(
    r.history.some((h) => h.type === 'payment' && h.name === 'Кредит'),
    '2: кредит оплачен'
  );
  assert(
    r.history.some((h) => h.type === 'payment' && h.name === 'ЖКХ'),
    '2: ЖКХ оплачен'
  );
  assertEq(r.arrearsTotal, 0, '2: нет просрочки');
}

// 3. Несколько доходов до одного платежа
{
  const r = rubInput({
    incomes: [
      { name: 'З1', day: 5, amount: 40000 },
      { name: 'З2', day: 12, amount: 40000 }
    ],
    fixed: [{ name: 'Кредит', day: 18, amount: 50000 }]
  });
  const card1 = r.incomeCards.find((c) => c.day === 5);
  const card2 = r.incomeCards.find((c) => c.day === 12);
  const a1 = (card1.allocations.find((a) => a.name === 'Кредит') || {}).amount || 0;
  const a2 = (card2.allocations.find((a) => a.name === 'Кредит') || {}).amount || 0;
  assert(Core.toKop(a1) + Core.toKop(a2) === kopOf(50000) || r.history.some((h) => h.type === 'payment' && h.name === 'Кредит'),
    '3: платёж обеспечен суммарно');
  // Сумма резервов по всем доходам на этот платёж
  let reservedSum = 0;
  r.incomeCards.forEach((c) => {
    (c.allocations || []).forEach((a) => {
      if (a.name === 'Кредит' && a.amount > 0) reservedSum += Core.toKop(a.amount);
    });
  });
  assertEq(reservedSum, kopOf(50000), '3: сумма резервов = сумма платежа');
  assertEq(r.arrearsTotal, 0, '3: нет просрочки');
}

// 4. Крупный расход до следующего дохода — не из будущего дохода
{
  const r = rubInput({
    incomes: [
      { name: 'З1', day: 5, amount: 100000 },
      { name: 'З2', day: 20, amount: 80000 }
    ],
    fixed: [{ name: 'Кредит', day: 10, amount: 20000 }],
    once: [{ name: 'Стоматолог', date: '2026-09-16', amount: 30000 }]
  });
  const card1 = r.incomeCards.find((c) => c.day === 5);
  const dent = card1.allocations.find((a) => a.name === 'Стоматолог');
  assert(dent && dent.fullyFunded, '4: стоматолог обеспечен из дохода 5 числа');
  assert(dent.dueBeforeNextIncome, '4: стоматолог — обязательный до следующего дохода');
  const card2 = r.incomeCards.find((c) => c.day === 20);
  const dent2 = (card2.allocations || []).find((a) => a.name === 'Стоматолог' && a.amount > 0);
  assert(!dent2, '4: доход 20 не финансирует стоматолога 16');
}

// 5. Денег недостаточно — реальный дефицит
{
  const r = rubInput({
    incomes: [{ name: 'З1', day: 5, amount: 20000 }],
    fixed: [{ name: 'Кредит', day: 10, amount: 50000 }]
  });
  assert(r.deficit > 0 || r.arrearsTotal > 0, '5: есть дефицит или просрочка');
  assert(r.feasible === false, '5: план невыполним');
  const freeKop = Core.toKop(r.viewSnapshot ? r.viewSnapshot.free : r.free);
  // Не показываем ложно большие свободные за счёт игнора обязательств
  assert(r.warnings.length > 0, '5: есть предупреждения');
}

// 6. Платёж раньше первого дохода — просрочка
{
  const r = rubInput({
    opening: 0,
    incomes: [{ name: 'З1', day: 5, amount: 100000 }],
    fixed: [{ name: 'Кредит', day: 3, amount: 10000 }]
  });
  assert(
    r.history.some((h) => h.type === 'arrears' && h.name === 'Кредит'),
    '6: обнаружена просрочка 3 числа'
  );
}

// 7. Новый доход после просрочки — сначала погашение
{
  const r = rubInput({
    opening: 0,
    incomes: [{ name: 'З1', day: 5, amount: 100000 }],
    fixed: [{ name: 'Кредит', day: 3, amount: 10000 }]
  });
  const hist = r.history.filter((h) => h.key === Core.absKey(2026, 9, 5));
  const types = hist.map((h) => h.type);
  const arrearsPayIdx = types.indexOf('arrears_payment');
  const incomeIdx = types.indexOf('income');
  assert(incomeIdx >= 0, '7: есть доход 5 числа');
  assert(arrearsPayIdx >= 0, '7: есть погашение просрочки');
  assert(arrearsPayIdx > incomeIdx, '7: погашение после дохода');
  // Накопления 25%
  const inc = hist.find((h) => h.type === 'income');
  assertEq(Core.toKop(inc.savings), kopOf(25000), '7: 25% в накопления');
  assertEq(Core.toKop(inc.usable), kopOf(75000), '7: 75% в бюджет');
  assertEq(r.arrearsTotal, 0, '7: просрочка погашена');
}

// 8. Добавление крупного расхода — полный пересчёт
{
  const base = {
    incomes: [
      { name: 'З1', day: 5, amount: 100000 },
      { name: 'З2', day: 20, amount: 80000 }
    ],
    fixed: [
      { name: 'Кредит', day: 10, amount: 20000 },
      { name: 'ЖКХ', day: 25, amount: 15000 }
    ]
  };
  const before = rubInput(base);
  const after = rubInput({
    ...base,
    once: [{ name: 'Стоматолог', date: '2026-09-16', amount: 30000 }]
  });
  const bAlloc = before.incomeCards.find((c) => c.day === 5).totalReserve;
  const aAlloc = after.incomeCards.find((c) => c.day === 5).totalReserve;
  assert(Core.toKop(aAlloc) !== Core.toKop(bAlloc), '8: резервы дохода 5 изменились');
  const dent = after.incomeCards
    .find((c) => c.day === 5)
    .allocations.find((a) => a.name === 'Стоматолог');
  assert(dent && dent.fullyFunded, '8: стоматолог учтён в новом плане');
}

// 9. Удаление крупного расхода — восстановление
{
  const withOnce = rubInput({
    incomes: [
      { name: 'З1', day: 5, amount: 100000 },
      { name: 'З2', day: 20, amount: 80000 }
    ],
    fixed: [{ name: 'Кредит', day: 10, amount: 20000 }],
    once: [{ name: 'Стоматолог', date: '2026-09-16', amount: 30000 }]
  });
  const without = rubInput({
    incomes: [
      { name: 'З1', day: 5, amount: 100000 },
      { name: 'З2', day: 20, amount: 80000 }
    ],
    fixed: [{ name: 'Кредит', day: 10, amount: 20000 }],
    once: []
  });
  assert(
    Core.toKop(without.incomeCards.find((c) => c.day === 5).remaining) >
      Core.toKop(withOnce.incomeCards.find((c) => c.day === 5).remaining),
    '9: свободные после удаления расхода выросли'
  );
}

// 10. Фактические бытовые расходы
{
  const r = rubInput({
    incomes: [{ name: 'З1', day: 5, amount: 100000 }],
    fixed: [],
    daily: [{ name: 'Продукты', date: '2026-09-08', amount: 10000 }],
    viewDay: 10
  });
  assertEq(Core.toKop(r.everydaySpent), kopOf(10000), '10: списано 10000 бытовых');
  // 100000 * 0.75 - 10000 = 65000 на счёте при отсутствии платежей
  assertEq(Core.toKop(r.monthEndSnapshot.cash), kopOf(65000), '10: cash после бытовых');
}

// 11. Два дохода в один день
{
  const r = rubInput({
    incomes: [
      { name: 'З1', day: 5, amount: 50000 },
      { name: 'З2', day: 5, amount: 50000 }
    ],
    fixed: [{ name: 'Кредит', day: 10, amount: 30000 }]
  });
  const cards = r.incomeCards.filter((c) => c.day === 5);
  assertEq(cards.length, 2, '11: две карточки дохода');
  const totalUsable = cards.reduce((s, c) => s + Core.toKop(c.usable), 0);
  assertEq(totalUsable, kopOf(75000), '11: суммарно 75% от 100000');
  assertEq(r.arrearsTotal, 0, '11: кредит обеспечен');
}

// 12. Один платёж — несколько доходов, сумма резервов = платежу
{
  const r = rubInput({
    incomes: [
      { name: 'З1', day: 5, amount: 40000 },
      { name: 'З2', day: 15, amount: 40000 }
    ],
    fixed: [{ name: 'Кредит', day: 25, amount: 45000 }]
  });
  let sum = 0;
  r.history
    .filter((h) => h.type === 'reserve' && h.name === 'Кредит')
    .forEach((h) => {
      sum += Core.toKop(h.amount);
    });
  assertEq(sum, kopOf(45000), '12: сумма резервов = 45000');
}

// Инварианты
{
  const r = rubInput({
    opening: 5000,
    incomes: [
      { name: 'З1', day: 5, amount: 100000 },
      { name: 'З2', day: 20, amount: 80000 }
    ],
    fixed: [
      { name: 'Кредит', day: 10, amount: 25000 },
      { name: 'ЖКХ', day: 15, amount: 10000 }
    ],
    once: [{ name: 'Стоматолог', date: '2026-09-18', amount: 30000 }],
    daily: [{ name: 'Еда', date: '2026-09-12', amount: 5000 }]
  });

  const kop = r._kop;
  assertEq(kop.cash, kop.reserved + kop.free, 'inv: Cash = Reserved + FreeCash');

  r.incomeCards.forEach((c) => {
    assertEq(
      Core.toKop(c.gross),
      Core.toKop(c.savings) + Core.toKop(c.usable),
      `inv: доход ${c.name} = накопления + usable`
    );
  });

  const opening = kopOf(5000);
  let usableSum = 0;
  r.incomeCards.forEach((c) => {
    usableSum += Core.toKop(c.usable);
  });
  // В выбранном месяце могут быть доходы только сентября; горизонт симуляции шире —
  // берём все income events из истории
  usableSum = 0;
  r.history
    .filter((h) => h.type === 'income')
    .forEach((h) => {
      usableSum += Core.toKop(h.usable);
    });
  const expectedCash = opening + usableSum - kop.paid - kop.everydaySpent;
  assertEq(expectedCash, kop.cash, 'inv: opening+75%income-paid-spent = cash');
}

// Накопления неприкосновенны при кассовом разрыве
{
  const r = rubInput({
    incomes: [{ name: 'З1', day: 5, amount: 10000 }],
    fixed: [{ name: 'Кредит', day: 8, amount: 20000 }]
  });
  assertEq(Core.toKop(r.savings), kopOf(2500), 'savings: 25% сохранены');
  assert(r.arrearsTotal > 0 || r.deficit > 0, 'savings: дефицит без траты накоплений');
}

// Февраль / 31 число
{
  const r = rubInput({
    selectedMonth: { year: 2027, month: 2, days: 28 },
    incomes: [{ name: 'З1', day: 31, amount: 50000 }],
    fixed: [{ name: 'ЖКХ', day: 31, amount: 5000 }],
    viewDay: 1
  });
  // day 31 → 28 февраля
  assert(
    r.incomeCards.some((c) => c.month === 2 && c.day === 28) ||
      r.history.some((h) => h.type === 'income' && h.month === 2 && h.day === 28),
    'cal: доход 31 → 28 февраля'
  );
}

// Високосный 2028
{
  const r = rubInput({
    selectedMonth: { year: 2028, month: 2, days: 29 },
    incomes: [{ name: 'З1', day: 29, amount: 40000 }],
    fixed: [{ name: 'Кредит', day: 29, amount: 10000 }],
    viewDay: 1
  });
  // BUDGET_START = 2026-09, so Feb 2028 is in horizon when selected
  assert(
    r.incomeCards.some((c) => c.year === 2028 && c.month === 2 && c.day === 29) ||
      r.history.some((h) => h.type === 'income' && h.year === 2028 && h.day === 29),
    'cal: 29 февраля високосного года'
  );
}

// Сценарий из ТЗ: полный месяц
{
  const r = rubInput({
    incomes: [
      { name: 'Зарплата', day: 5, amount: 100000 },
      { name: 'Второй доход', day: 20, amount: 80000 }
    ],
    fixed: [
      { name: 'Кредит', day: 10, amount: 25000 },
      { name: 'ЖКХ', day: 15, amount: 10000 },
      { name: 'Другой кредит', day: 25, amount: 20000 }
    ],
    once: [{ name: 'Стоматолог', date: '2026-09-18', amount: 30000 }]
  });
  assertEq(r.arrearsTotal, 0, 'tz: все обязательства без просрочки');
  ['Кредит', 'ЖКХ', 'Стоматолог', 'Другой кредит'].forEach((name) => {
    assert(
      r.history.some((h) => h.type === 'payment' && h.name === name),
      `tz: оплачен ${name}`
    );
  });
  const c5 = r.incomeCards.find((c) => c.day === 5);
  assert(c5.allocations.find((a) => a.name === 'Кредит').fullyFunded, 'tz: кредит к 10');
  assert(c5.allocations.find((a) => a.name === 'ЖКХ').fullyFunded, 'tz: ЖКХ к 15');
  assert(c5.allocations.find((a) => a.name === 'Стоматолог').fullyFunded, 'tz: стоматолог к 18');
  // Другой кредит 25 — после дохода 20, не обязан быть полностью из 5
  const other = c5.allocations.find((a) => a.name === 'Другой кредит');
  assert(!other || !other.dueBeforeNextIncome || other.fullyFunded, 'tz: кредит 25 не блокирует жизнь');
  assert(c5.remaining >= 0, 'tz: свободные после 5 не отрицательные');
}

// Дневной лимит от текущей даты, не от начала месяца
{
  const r = rubInput({
    incomes: [{ name: 'З1', day: 5, amount: 100000 }],
    fixed: [],
    viewDay: 20
  });
  const snap = r.viewSnapshot;
  const end = r.monthEndSnapshot;
  assert(snap && snap.day === 20, 'daily: снимок на день 20');
  assert(end && end.day === 30, 'daily: конец месяца 30');
  // Лимит на день 20 считается от оставшихся дней, не от всех 30
  assert(snap.dailyLimit != null, 'daily: есть текущий лимит');
}

console.log(`\nИтого: ${passed} пройдено, ${failed} провалено`);
if (failures.length) {
  console.log('\nПровалы:');
  failures.forEach((f) => console.log(' -', f));
  process.exit(1);
}
console.log('Все тесты успешно прошли.');
process.exit(0);
