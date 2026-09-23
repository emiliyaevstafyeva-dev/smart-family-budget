# -*- coding: utf-8 -*-
"""
Автотесты финансового ядра. Запуск:
  python budget_core_test.py
из папки «Бюджетный калькулятор».
"""
from __future__ import annotations

import sys

import budget_core as Core

passed = 0
failed = 0
failures = []


def assert_(cond, msg):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        failures.append(msg)
        print("FAIL:", msg, file=sys.stderr)


def assertEq(a, b, msg):
    assert_(a == b, f"{msg} (got {a}, expected {b})")


def rubInput(cfg):
    selectedMonth = cfg.get("selectedMonth") or {"year": 2026, "month": 9, "days": 30}
    incomes = cfg.get("incomes") or []
    fixed = cfg.get("fixed") or []
    once = cfg.get("once") or []
    daily = cfg.get("daily") or []

    def getIncomeAmount(idx, _year, _month):
        return float(incomes[idx]["amount"]) if idx < len(incomes) and incomes[idx] else 0

    return Core.calculateBudget({
        "openingBalanceRubles": cfg.get("opening") or 0,
        "incomeRows": incomes,
        "getIncomeAmount": getIncomeAmount,
        "fixedRows": fixed,
        "onceRows": once,
        "dailyExpenses": daily,
        "selectedMonth": selectedMonth,
        "viewDay": cfg["viewDay"] if cfg.get("viewDay") is not None else 1,
        "isMonthLocked": lambda _y, _m: False,
    })


def kopOf(rubles):
    return Core.toKop(rubles)


print("=== Тесты финансового ядра ===\n")

# 1. Доход раньше кредита
r = rubInput({
    "incomes": [{"name": "Зарплата", "day": 5, "amount": 100000}],
    "fixed": [{"name": "Кредит", "day": 10, "amount": 25000}],
})
sel = "2026-09"
pay = [
    h
    for h in r["history"]
    if h["type"] == "payment" and h["name"] == "Кредит" and h["mKey"] == sel
]
assert_(len(pay) == 1, "1: кредит оплачен один раз")
assertEq(Core.toKop(pay[0]["amount"]), kopOf(25000), "1: сумма кредита 25000")
assertEq(r["arrearsTotal"], 0, "1: нет просрочки")
card = next(c for c in r["incomeCards"] if c["day"] == 5 and c["isSelectedMonth"])
alloc = next((a for a in card["allocations"] if a["name"] == "Кредит"), None)
assert_(alloc and alloc["fullyFunded"], "1: кредит полностью обеспечен из дохода")

# 2. Несколько платежей до следующего дохода
r = rubInput({
    "incomes": [
        {"name": "З1", "day": 5, "amount": 100000},
        {"name": "З2", "day": 20, "amount": 80000},
    ],
    "fixed": [
        {"name": "Кредит", "day": 10, "amount": 25000},
        {"name": "ЖКХ", "day": 15, "amount": 10000},
    ],
})
assert_(
    any(h["type"] == "payment" and h["name"] == "Кредит" for h in r["history"]),
    "2: кредит оплачен",
)
assert_(
    any(h["type"] == "payment" and h["name"] == "ЖКХ" for h in r["history"]),
    "2: ЖКХ оплачен",
)
assertEq(r["arrearsTotal"], 0, "2: нет просрочки")

# 3. Несколько доходов до одного платежа
r = rubInput({
    "incomes": [
        {"name": "З1", "day": 5, "amount": 40000},
        {"name": "З2", "day": 12, "amount": 40000},
    ],
    "fixed": [{"name": "Кредит", "day": 18, "amount": 50000}],
})
card1 = next(c for c in r["incomeCards"] if c["day"] == 5 and c["isSelectedMonth"])
card2 = next(c for c in r["incomeCards"] if c["day"] == 12 and c["isSelectedMonth"])
a1 = next((a for a in card1["allocations"] if a["name"] == "Кредит"), None)
a2 = next((a for a in card2["allocations"] if a["name"] == "Кредит"), None)
a1amt = (a1 or {}).get("amount") or 0
a2amt = (a2 or {}).get("amount") or 0
assert_(
    Core.toKop(a1amt) + Core.toKop(a2amt) == kopOf(50000)
    or any(
        h["type"] == "payment" and h["name"] == "Кредит" and h["mKey"] == "2026-09"
        for h in r["history"]
    ),
    "3: платёж обеспечен суммарно",
)
reservedSum = 0
for c in r["incomeCards"]:
    if not c["isSelectedMonth"]:
        continue
    for a in c.get("allocations") or []:
        if (
            a["name"] == "Кредит"
            and a["amount"] > 0
            and a.get("targetMonthKey") == "2026-09"
        ):
            reservedSum += Core.toKop(a["amount"])
assertEq(reservedSum, kopOf(50000), "3: сумма резервов = сумма платежа")
assertEq(r["arrearsTotal"], 0, "3: нет просрочки")

# 4. Крупный расход до следующего дохода — не из будущего дохода
r = rubInput({
    "incomes": [
        {"name": "З1", "day": 5, "amount": 100000},
        {"name": "З2", "day": 20, "amount": 80000},
    ],
    "fixed": [{"name": "Кредит", "day": 10, "amount": 20000}],
    "once": [{"name": "Стоматолог", "date": "2026-09-16", "amount": 30000}],
})
card1 = next(c for c in r["incomeCards"] if c["day"] == 5)
dent = next((a for a in card1["allocations"] if a["name"] == "Стоматолог"), None)
assert_(dent and dent["fullyFunded"], "4: стоматолог обеспечен из дохода 5 числа")
assert_(dent["dueBeforeNextIncome"], "4: стоматолог — обязательный до следующего дохода")
card2 = next(c for c in r["incomeCards"] if c["day"] == 20)
dent2 = next(
    (
        a
        for a in (card2.get("allocations") or [])
        if a["name"] == "Стоматолог" and a["amount"] > 0
    ),
    None,
)
assert_(not dent2, "4: доход 20 не финансирует стоматолога 16")

# 5. Денег недостаточно — реальный дефицит
r = rubInput({
    "incomes": [{"name": "З1", "day": 5, "amount": 20000}],
    "fixed": [{"name": "Кредит", "day": 10, "amount": 50000}],
})
assert_(r["deficit"] > 0 or r["arrearsTotal"] > 0, "5: есть дефицит или просрочка")
assert_(r["feasible"] is False, "5: план невыполним")
assert_(len(r["warnings"]) > 0, "5: есть предупреждения")

# 6. Платёж раньше первого дохода — просрочка
r = rubInput({
    "opening": 0,
    "incomes": [{"name": "З1", "day": 5, "amount": 100000}],
    "fixed": [{"name": "Кредит", "day": 3, "amount": 10000}],
})
assert_(
    any(h["type"] == "arrears" and h["name"] == "Кредит" for h in r["history"]),
    "6: обнаружена просрочка 3 числа",
)

# 7. Новый доход после просрочки — сначала погашение
r = rubInput({
    "opening": 0,
    "incomes": [{"name": "З1", "day": 5, "amount": 100000}],
    "fixed": [{"name": "Кредит", "day": 3, "amount": 10000}],
})
hist = [h for h in r["history"] if h["key"] == Core.absKey(2026, 9, 5)]
types = [h["type"] for h in hist]
arrearsPayIdx = types.index("arrears_payment") if "arrears_payment" in types else -1
incomeIdx = types.index("income") if "income" in types else -1
assert_(incomeIdx >= 0, "7: есть доход 5 числа")
assert_(arrearsPayIdx >= 0, "7: есть погашение просрочки")
assert_(arrearsPayIdx > incomeIdx, "7: погашение после дохода")
inc = next(h for h in hist if h["type"] == "income")
assertEq(Core.toKop(inc["savings"]), kopOf(25000), "7: 25% в накопления")
assertEq(Core.toKop(inc["usable"]), kopOf(75000), "7: 75% в бюджет")
assertEq(r["arrearsTotal"], 0, "7: просрочка погашена")

# 8. Добавление крупного расхода — полный пересчёт
base = {
    "incomes": [
        {"name": "З1", "day": 5, "amount": 100000},
        {"name": "З2", "day": 20, "amount": 80000},
    ],
    "fixed": [
        {"name": "Кредит", "day": 10, "amount": 20000},
        {"name": "ЖКХ", "day": 25, "amount": 15000},
    ],
}
before = rubInput(base)
after = rubInput({
    **base,
    "once": [{"name": "Стоматолог", "date": "2026-09-16", "amount": 30000}],
})
bAlloc = next(c for c in before["incomeCards"] if c["day"] == 5)["totalReserve"]
aAlloc = next(c for c in after["incomeCards"] if c["day"] == 5)["totalReserve"]
assert_(Core.toKop(aAlloc) != Core.toKop(bAlloc), "8: резервы дохода 5 изменились")
dent = next(
    a
    for a in next(c for c in after["incomeCards"] if c["day"] == 5)["allocations"]
    if a["name"] == "Стоматолог"
)
assert_(dent and dent["fullyFunded"], "8: стоматолог учтён в новом плане")

# 9. Удаление крупного расхода — восстановление
withOnce = rubInput({
    "incomes": [
        {"name": "З1", "day": 5, "amount": 100000},
        {"name": "З2", "day": 20, "amount": 80000},
    ],
    "fixed": [{"name": "Кредит", "day": 10, "amount": 20000}],
    "once": [{"name": "Стоматолог", "date": "2026-09-16", "amount": 30000}],
})
without = rubInput({
    "incomes": [
        {"name": "З1", "day": 5, "amount": 100000},
        {"name": "З2", "day": 20, "amount": 80000},
    ],
    "fixed": [{"name": "Кредит", "day": 10, "amount": 20000}],
    "once": [],
})
rem_with = Core.toKop(
    next(c for c in withOnce["incomeCards"] if c["day"] == 5)["remaining"]
)
rem_without = Core.toKop(
    next(c for c in without["incomeCards"] if c["day"] == 5)["remaining"]
)
assert_(rem_without > rem_with, "9: свободные после удаления расхода выросли")

# 10. Фактические бытовые расходы
r = rubInput({
    "incomes": [{"name": "З1", "day": 5, "amount": 100000}],
    "fixed": [],
    "daily": [{"name": "Продукты", "date": "2026-09-08", "amount": 10000}],
    "viewDay": 10,
})
assertEq(Core.toKop(r["everydaySpent"]), kopOf(10000), "10: списано 10000 бытовых")
assertEq(
    Core.toKop(r["monthEndSnapshot"]["cash"]),
    kopOf(65000),
    "10: cash после бытовых",
)

# 11. Два дохода в один день
r = rubInput({
    "incomes": [
        {"name": "З1", "day": 5, "amount": 50000},
        {"name": "З2", "day": 5, "amount": 50000},
    ],
    "fixed": [{"name": "Кредит", "day": 10, "amount": 30000}],
})
cards = [c for c in r["incomeCards"] if c["day"] == 5 and c["isSelectedMonth"]]
assertEq(len(cards), 2, "11: две карточки дохода")
totalUsable = sum(Core.toKop(c["usable"]) for c in cards)
assertEq(totalUsable, kopOf(75000), "11: суммарно 75% от 100000")
assertEq(r["arrearsTotal"], 0, "11: кредит обеспечен")

# 12. Один платёж — несколько доходов, сумма резервов = платежу
r = rubInput({
    "incomes": [
        {"name": "З1", "day": 5, "amount": 40000},
        {"name": "З2", "day": 15, "amount": 40000},
    ],
    "fixed": [{"name": "Кредит", "day": 25, "amount": 45000}],
})
s = 0
for h in r["history"]:
    if h["type"] == "reserve" and h["name"] == "Кредит" and h["mKey"] == "2026-09":
        s += Core.toKop(h["amount"])
assertEq(s, kopOf(45000), "12: сумма резервов = 45000")

# Инварианты
r = rubInput({
    "opening": 5000,
    "incomes": [
        {"name": "З1", "day": 5, "amount": 100000},
        {"name": "З2", "day": 20, "amount": 80000},
    ],
    "fixed": [
        {"name": "Кредит", "day": 10, "amount": 25000},
        {"name": "ЖКХ", "day": 15, "amount": 10000},
    ],
    "once": [{"name": "Стоматолог", "date": "2026-09-18", "amount": 30000}],
    "daily": [{"name": "Еда", "date": "2026-09-12", "amount": 5000}],
})

kop = r["_kop"]
assertEq(kop["cash"], kop["reserved"] + kop["free"], "inv: Cash = Reserved + FreeCash")

for c in r["incomeCards"]:
    assertEq(
        Core.toKop(c["gross"]),
        Core.toKop(c["savings"]) + Core.toKop(c["usable"]),
        f"inv: доход {c['name']} = накопления + usable",
    )

opening = kopOf(5000)
usableSum = 0
for h in r["history"]:
    if h["type"] == "income":
        usableSum += Core.toKop(h["usable"])
expectedCash = opening + usableSum - kop["paid"] - kop["everydaySpent"]
assertEq(expectedCash, kop["cash"], "inv: opening+75%income-paid-spent = cash")

# Накопления неприкосновенны при кассовом разрыве
r = rubInput({
    "incomes": [{"name": "З1", "day": 5, "amount": 10000}],
    "fixed": [{"name": "Кредит", "day": 8, "amount": 20000}],
})
assertEq(
    Core.toKop(next(c for c in r["incomeCards"] if c["isSelectedMonth"])["savings"]),
    kopOf(2500),
    "savings: 25% сохранены",
)
assert_(
    r["arrearsTotal"] > 0 or r["deficit"] > 0,
    "savings: дефицит без траты накоплений",
)

# Февраль / 31 число
r = rubInput({
    "selectedMonth": {"year": 2027, "month": 2, "days": 28},
    "incomes": [{"name": "З1", "day": 31, "amount": 50000}],
    "fixed": [{"name": "ЖКХ", "day": 31, "amount": 5000}],
    "viewDay": 1,
})
assert_(
    any(c["month"] == 2 and c["day"] == 28 for c in r["incomeCards"])
    or any(
        h["type"] == "income" and h["month"] == 2 and h["day"] == 28
        for h in r["history"]
    ),
    "cal: доход 31 → 28 февраля",
)

# Високосный 2028
r = rubInput({
    "selectedMonth": {"year": 2028, "month": 2, "days": 29},
    "incomes": [{"name": "З1", "day": 29, "amount": 40000}],
    "fixed": [{"name": "Кредит", "day": 29, "amount": 10000}],
    "viewDay": 1,
})
assert_(
    any(
        c["year"] == 2028 and c["month"] == 2 and c["day"] == 29
        for c in r["incomeCards"]
    )
    or any(
        h["type"] == "income" and h["year"] == 2028 and h["day"] == 29
        for h in r["history"]
    ),
    "cal: 29 февраля високосного года",
)

# Сценарий из ТЗ: полный месяц
r = rubInput({
    "incomes": [
        {"name": "Зарплата", "day": 5, "amount": 100000},
        {"name": "Второй доход", "day": 20, "amount": 80000},
    ],
    "fixed": [
        {"name": "Кредит", "day": 10, "amount": 25000},
        {"name": "ЖКХ", "day": 15, "amount": 10000},
        {"name": "Другой кредит", "day": 25, "amount": 20000},
    ],
    "once": [{"name": "Стоматолог", "date": "2026-09-18", "amount": 30000}],
})
assertEq(r["arrearsTotal"], 0, "tz: все обязательства без просрочки")
for name in ["Кредит", "ЖКХ", "Стоматолог", "Другой кредит"]:
    assert_(
        any(h["type"] == "payment" and h["name"] == name for h in r["history"]),
        f"tz: оплачен {name}",
    )
c5 = next(c for c in r["incomeCards"] if c["day"] == 5)
assert_(
    next(a for a in c5["allocations"] if a["name"] == "Кредит")["fullyFunded"],
    "tz: кредит к 10",
)
assert_(
    next(a for a in c5["allocations"] if a["name"] == "ЖКХ")["fullyFunded"],
    "tz: ЖКХ к 15",
)
assert_(
    next(a for a in c5["allocations"] if a["name"] == "Стоматолог")["fullyFunded"],
    "tz: стоматолог к 18",
)
other = next((a for a in c5["allocations"] if a["name"] == "Другой кредит"), None)
assert_(
    not other or not other["dueBeforeNextIncome"] or other["fullyFunded"],
    "tz: кредит 25 не блокирует жизнь",
)
assert_(c5["remaining"] >= 0, "tz: свободные после 5 не отрицательные")

# Дневной лимит от текущей даты, не от начала месяца
r = rubInput({
    "incomes": [{"name": "З1", "day": 5, "amount": 100000}],
    "fixed": [],
    "viewDay": 20,
})
snap = r["viewSnapshot"]
end = r["monthEndSnapshot"]
assert_(snap and snap["day"] == 20, "daily: снимок на день 20")
assert_(end and end["day"] == 30, "daily: конец месяца 30")
assert_(snap.get("dailyLimit") is not None, "daily: есть текущий лимит")

print(f"\nИтого: {passed} пройдено, {failed} провалено")
if failures:
    print("\nПровалы:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("Все тесты успешно прошли.")
sys.exit(0)
