# -*- coding: utf-8 -*-
"""
Финансовое ядро «Умный семейный бюджет» (Python-порт budget-core.js).

Все суммы внутри — целые копейки. Свободные деньги = Cash − Reserved.
Накопления (25%) не входят в Cash и не используются для платежей.

Порядок операций в один день: opening → incomes → arrears/reserve → payments → daily.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterator, List, Optional, Set


def _js_round(n: float) -> int:
    """Эквивалент Math.round: half toward +Infinity."""
    return int(math.floor(n + 0.5))

SAVINGS_RATE_NUM = 25
SAVINGS_RATE_DEN = 100
BUDGET_START = {"year": 2026, "month": 9, "day": 1}


def absKey(y: int, m: int, d: int) -> int:
    return y * 10000 + m * 100 + d


BUDGET_START_KEY = absKey(2026, 9, 1)

_MONTHS_RU_GENITIVE = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def addMonths(y: int, m: int, delta: int) -> Dict[str, int]:
    total = y * 12 + (m - 1) + delta
    return {"year": total // 12, "month": (total % 12) + 1}


def dim(y: int, m: int) -> int:
    if m == 12:
        return (date(y + 1, 1, 1) - timedelta(days=1)).day
    return (date(y, m + 1, 1) - timedelta(days=1)).day


def monthKey(y: int, m: int) -> str:
    return f"{y}-{m:02d}"


def daysBetween(a: Dict[str, int], b: Dict[str, int]) -> int:
    da = date(a["year"], a["month"], a["day"])
    db = date(b["year"], b["month"], b["day"])
    t = (db - da).days
    return max(1, round(t))


def daysInclusiveRemaining(
    from_: Dict[str, int], toExclusive: Optional[Dict[str, int]]
) -> int:
    if not toExclusive:
        return max(1, dim(from_["year"], from_["month"]) - from_["day"] + 1)
    da = date(from_["year"], from_["month"], from_["day"])
    db = date(toExclusive["year"], toExclusive["month"], toExclusive["day"])
    diff = (db - da).days
    return max(1, round(diff))


def toKop(rubles: Any) -> int:
    try:
        n = float(rubles)
    except (TypeError, ValueError):
        return 0
    if n != n or n == float("inf") or n == float("-inf") or n <= 0:  # NaN / Inf
        return 0
    return _js_round(n * 100)


def fromKop(kop: Any) -> float:
    try:
        return (float(kop) if kop is not None else 0.0) / 100.0
    except (TypeError, ValueError):
        return 0.0


def splitIncome(grossKop: int) -> Dict[str, int]:
    savings = (grossKop * SAVINGS_RATE_NUM) // SAVINGS_RATE_DEN
    return {"savings": savings, "usable": grossKop - savings}


def eachDay(
    fromY: int, fromM: int, toY: int, toM: int
) -> Iterator[Dict[str, Any]]:
    y, mo, d = fromY, fromM, 1
    endK = absKey(toY, toM, dim(toY, toM))
    while True:
        maxD = dim(y, mo)
        while d <= maxD:
            cell = {
                "year": y,
                "month": mo,
                "day": d,
                "key": absKey(y, mo, d),
                "mKey": monthKey(y, mo),
            }
            yield cell
            if cell["key"] >= endK:
                return
            d += 1
        n = addMonths(y, mo, 1)
        y, mo, d = n["year"], n["month"], 1


def monthsFromBudgetStart(
    selectedMonth: Dict[str, int], horizonMonths: Optional[int] = None
) -> List[Dict[str, Any]]:
    horizon = 2 if horizonMonths is None else horizonMonths
    end = addMonths(selectedMonth["year"], selectedMonth["month"], horizon)
    selKey = monthKey(selectedMonth["year"], selectedMonth["month"])
    endKey = monthKey(end["year"], end["month"])
    lst: List[Dict[str, Any]] = []
    cur = {"year": BUDGET_START["year"], "month": BUDGET_START["month"]}
    while monthKey(cur["year"], cur["month"]) <= endKey:
        lst.append(
            {
                "year": cur["year"],
                "month": cur["month"],
                "isSelected": monthKey(cur["year"], cur["month"]) == selKey,
            }
        )
        cur = addMonths(cur["year"], cur["month"], 1)
    return lst


def parseDateParts(dateStr: Any) -> Optional[Dict[str, int]]:
    if not dateStr:
        return None
    s = str(dateStr).strip()
    # JS: new Date(dateStr + 'T12:00:00') — noon avoids TZ day-shift
    try:
        if "T" in s or " " in s:
            # already has time
            date_part = s.replace(" ", "T").split("T")[0]
        else:
            date_part = s
        parts = date_part.split("-")
        if len(parts) != 3:
            return None
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        # validate
        date(y, m, d)
        return {"year": y, "month": m, "day": d}
    except (ValueError, TypeError):
        return None


def clampViewDay(viewDay: Any, selectedMonth: Dict[str, Any]) -> int:
    days = selectedMonth.get("days") or dim(
        selectedMonth["year"], selectedMonth["month"]
    )
    if viewDay is None:
        return 1
    try:
        v = round(float(viewDay) if viewDay is not None else 1)
    except (TypeError, ValueError):
        v = 1
    if v != v:  # NaN
        v = 1
    return min(max(1, int(v)), int(days))


def normalizeDaily(rows: List[Any], selKey: Optional[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, x in enumerate(rows or []):
        parts = None
        if x.get("year") and x.get("month") and x.get("day"):
            parts = {"year": x["year"], "month": x["month"], "day": x["day"]}
        else:
            parts = parseDateParts(x.get("date"))
        amount = toKop(x.get("amount"))
        if not parts or amount <= 0:
            continue
        mKey = monthKey(parts["year"], parts["month"])
        if selKey and mKey != selKey:
            continue
        out.append(
            {
                "id": x.get("id") or f"daily-{i}",
                "name": x.get("name") or "Расход",
                "year": parts["year"],
                "month": parts["month"],
                "day": parts["day"],
                "key": absKey(parts["year"], parts["month"], parts["day"]),
                "mKey": mKey,
                "amount": amount,
            }
        )
    out.sort(key=lambda a: (a["key"], str(a["id"])))
    return out


def buildChronology(input_: Dict[str, Any]) -> Dict[str, Any]:
    selectedMonth = input_["selectedMonth"]
    selKey = monthKey(selectedMonth["year"], selectedMonth["month"])
    months = monthsFromBudgetStart(selectedMonth)
    endMonth = months[-1]
    isMonthLocked: Callable[[int, int], bool] = input_.get("isMonthLocked") or (
        lambda _y, _m: False
    )
    getIncomeAmount = input_.get("getIncomeAmount")

    incomeEvents: List[Dict[str, Any]] = []
    for ym in months:
        year, month, isSelected = ym["year"], ym["month"], ym["isSelected"]
        days = dim(year, month)
        for i, inc in enumerate(input_.get("incomeRows") or []):
            if getIncomeAmount:
                amountRub = getIncomeAmount(i, year, month)
            else:
                try:
                    amountRub = float(inc.get("amount") or 0)
                except (TypeError, ValueError):
                    amountRub = 0
            amount = toKop(amountRub)
            if amount <= 0:
                continue
            try:
                day_raw = round(float(inc.get("day") or 1))
            except (TypeError, ValueError):
                day_raw = 1
            day = min(max(1, int(day_raw)), days)
            key = absKey(year, month, day)
            if key < BUDGET_START_KEY:
                continue
            incomeEvents.append(
                {
                    "id": f"inc-{year}-{month}-{i}",
                    "incomeIndex": i,
                    "name": inc.get("name") or "Доход",
                    "year": year,
                    "month": month,
                    "day": day,
                    "key": key,
                    "mKey": monthKey(year, month),
                    "amount": amount,
                    "isSelectedMonth": isSelected,
                    "isFact": isMonthLocked(year, month),
                }
            )
    incomeEvents.sort(key=lambda a: (a["key"], a["incomeIndex"]))

    obligations: List[Dict[str, Any]] = []
    for ym in months:
        year, month, isSelected = ym["year"], ym["month"], ym["isSelected"]
        days = dim(year, month)
        for i, fix in enumerate(input_.get("fixedRows") or []):
            amount = toKop(fix.get("amount"))
            if amount <= 0:
                continue
            try:
                day_raw = round(float(fix.get("day") or 1))
            except (TypeError, ValueError):
                day_raw = 1
            day = min(max(1, int(day_raw)), days)
            key = absKey(year, month, day)
            if key < BUDGET_START_KEY:
                continue
            obligations.append(
                {
                    "id": f"fix-{i}-{year}-{month}",
                    "fixIndex": i,
                    "name": fix.get("name") or "Постоянный платеж",
                    "year": year,
                    "month": month,
                    "day": day,
                    "key": key,
                    "mKey": monthKey(year, month),
                    "amount": amount,
                    "priority": 1,
                    "kind": "Постоянный платеж",
                    "isSelectedMonth": isSelected,
                    "sourceIndex": i,
                }
            )

    for i, o in enumerate(input_.get("onceRows") or []):
        amount = toKop(o.get("amount"))
        parts = parseDateParts(o.get("date"))
        if amount <= 0 or not parts:
            continue
        key = absKey(parts["year"], parts["month"], parts["day"])
        if key < BUDGET_START_KEY:
            continue
        if monthKey(parts["year"], parts["month"]) > monthKey(
            endMonth["year"], endMonth["month"]
        ):
            continue
        obligations.append(
            {
                "id": f"once-{i}",
                "onceIndex": i,
                "name": o.get("name") or "Крупный расход",
                "year": parts["year"],
                "month": parts["month"],
                "day": parts["day"],
                "key": key,
                "mKey": monthKey(parts["year"], parts["month"]),
                "amount": amount,
                "priority": 2,
                "kind": "Крупный разовый",
                "isSelectedMonth": monthKey(parts["year"], parts["month"]) == selKey,
                "sourceIndex": i,
            }
        )

    obligations.sort(
        key=lambda a: (a["key"], a["priority"], str(a["id"]))
    )

    daily = normalizeDaily(input_.get("dailyExpenses") or [], selKey)

    return {
        "incomeEvents": incomeEvents,
        "obligations": obligations,
        "dailyExpenses": daily,
        "selKey": selKey,
        "openingBalance": toKop(input_.get("openingBalanceRubles")),
        "simEnd": endMonth,
        "selectedMonth": selectedMonth,
        "viewDay": clampViewDay(input_.get("viewDay"), selectedMonth),
    }


def nextIncomeAfter(
    incomeEvents: List[Dict[str, Any]], key: int
) -> Optional[Dict[str, Any]]:
    for e in incomeEvents:
        if e["key"] > key:
            return e
    return None


def isMandatoryForIncome(
    ob: Dict[str, Any], incKey: int, nextKey: Optional[int]
) -> bool:
    if ob["key"] < incKey:
        return False
    if ob["key"] == incKey:
        return True
    if nextKey is None:
        return True
    return ob["key"] < nextKey


def findMaxSafeDailyLimit(chronology: Dict[str, Any]) -> int:
    incomeEvents = chronology["incomeEvents"]
    openingBalance = chronology["openingBalance"]
    hi = openingBalance
    for e in incomeEvents:
        hi += splitIncome(e["amount"])["usable"]
    hi = max(0, hi)

    lo = 0
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if canAffordWithDaily(chronology, mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def canAffordWithDaily(chronology: Dict[str, Any], dailyLimitKop: int) -> bool:
    result = simulate(
        chronology,
        {
            "targetDailyLimit": dailyLimitKop,
            "strictFeasibility": True,
            "recordHistory": False,
        },
    )
    return result["feasible"]


def fmtRub(kop: int) -> str:
    rub = _js_round(fromKop(kop))
    # ru-RU: space as thousands separator
    s = f"{int(rub):,}".replace(",", "\u00a0")
    return f"{s} ₽"


def fmtAbs(y: int, m: int, d: int) -> str:
    return f"{d} {_MONTHS_RU_GENITIVE[m]}"


def buildDisplayItems(
    obligations: List[Dict[str, Any]],
    paid: Set[str],
    arrears: List[Dict[str, Any]],
    reserveAtStart: Dict[str, int],
    rawAllocations: List[Dict[str, Any]],
    inc: Dict[str, Any],
    nextKey: Optional[int],
    getReserve: Callable[[str], int],
) -> List[Dict[str, Any]]:
    def arrears_has(oid: str) -> bool:
        return any(a["originalId"] == oid for a in arrears)

    filtered = [
        o
        for o in obligations
        if o["id"] not in paid
        and not arrears_has(o["id"])
        and o["key"] >= inc["key"]
        and (
            any(a["paymentId"] == o["id"] for a in rawAllocations)
            or (reserveAtStart.get(o["id"]) or 0) > 0
            or isMandatoryForIncome(o, inc["key"], nextKey)
        )
    ]
    filtered.sort(key=lambda a: (a["key"], a["priority"], str(a["id"])))

    result = []
    for o in filtered:
        alloc = next((a for a in rawAllocations if a["paymentId"] == o["id"]), None)
        prev = reserveAtStart.get(o["id"]) or 0
        add = alloc["amount"] if alloc else 0
        after = alloc["newReserve"] if alloc else prev
        mandatory = isMandatoryForIncome(o, inc["key"], nextKey)
        result.append(
            {
                "paymentId": o["id"],
                "name": o["name"],
                "dueYear": o["year"],
                "dueMonth": o["month"],
                "dueDay": o["day"],
                "dueKey": o["key"],
                "previousReserve": prev,
                "amount": add,
                "newReserve": after,
                "total": o["amount"],
                "kind": o["kind"],
                "targetMonthKey": o["mKey"],
                "remainingToFund": max(0, o["amount"] - after),
                "fullyFunded": after >= o["amount"],
                "mandatory": mandatory,
                "dueBeforeNextIncome": mandatory,
            }
        )
    return result


def simulate(
    chronology: Dict[str, Any], opts: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    opts = opts or {}
    recordHistory = opts.get("recordHistory", True) is not False
    targetDaily = (
        0 if opts.get("targetDailyLimit") is None else opts["targetDailyLimit"]
    )
    strict = bool(opts.get("strictFeasibility"))

    incomeEvents = chronology["incomeEvents"]
    obligations = chronology["obligations"]
    dailyExpenses = chronology["dailyExpenses"]
    selKey = chronology["selKey"]
    openingBalance = chronology["openingBalance"]
    simEnd = chronology["simEnd"]

    warnings: List[Dict[str, Any]] = []
    history: List[Dict[str, Any]] = []
    incomeCards: List[Dict[str, Any]] = []
    reserves: Dict[str, int] = {}
    paid: Set[str] = set()
    arrears: List[Dict[str, Any]] = []
    processedRemaining: Dict[str, int] = {}

    cash = 0
    savings = 0
    totalPaid = 0
    totalSpent = 0
    totalArrearsPaid = 0
    openingDone = False
    feasible = True
    peakDeficit = 0

    def getReserve(oid: str) -> int:
        return reserves.get(oid) or 0

    def reservedTotal() -> int:
        return sum(reserves.values())

    def freeCash() -> int:
        return cash - reservedTotal()

    def addWarning(key: str, payload: Dict[str, Any]) -> None:
        if any(w.get("key") == key for w in warnings):
            return
        w = {"key": key}
        w.update(payload)
        warnings.append(w)

    def recordAllocation(
        raw: List[Dict[str, Any]],
        ob: Dict[str, Any],
        prevRes: int,
        part: int,
        mandatory: bool,
    ) -> None:
        nonlocal reserves
        newRes = prevRes + part
        reserves[ob["id"]] = newRes
        raw.append(
            {
                "paymentId": ob["id"],
                "name": ob["name"],
                "dueYear": ob["year"],
                "dueMonth": ob["month"],
                "dueDay": ob["day"],
                "dueKey": ob["key"],
                "amount": part,
                "previousReserve": prevRes,
                "newReserve": newRes,
                "total": ob["amount"],
                "kind": ob["kind"],
                "targetMonthKey": ob["mKey"],
                "mandatory": mandatory,
            }
        )

    def repayArrears(cell: Dict[str, Any]) -> None:
        nonlocal cash, totalArrearsPaid, totalPaid
        arrears.sort(key=lambda a: (a["key"], str(a["id"])))
        i = 0
        while i < len(arrears):
            a = arrears[i]
            free = freeCash()
            if free <= 0:
                break
            pay = min(a["amount"], free)
            cash -= pay
            a["amount"] -= pay
            totalArrearsPaid += pay
            totalPaid += pay
            if recordHistory:
                history.append(
                    {
                        "type": "arrears_payment",
                        "year": cell["year"],
                        "month": cell["month"],
                        "day": cell["day"],
                        "key": cell["key"],
                        "mKey": cell["mKey"],
                        "name": a["name"] + " (просрочка)",
                        "amount": pay,
                        "remaining": a["amount"],
                    }
                )
            if a["amount"] <= 0:
                paid.add(a["originalId"])
                arrears.pop(i)
            else:
                i += 1

    def allocateFromIncome(inc: Dict[str, Any]) -> None:
        nonlocal cash, savings, feasible, peakDeficit
        split = splitIncome(inc["amount"])
        savAmt = split["savings"]
        usable = split["usable"]
        savings += savAmt
        cash += usable

        reserveAtStart = {o["id"]: getReserve(o["id"]) for o in obligations}

        # Порядок дня в истории: доход → погашение просрочек → резервы
        # (деньги на счёт уже зачислены; repayArrears идёт сразу после).
        income_hist: Optional[Dict[str, Any]] = None
        if recordHistory:
            income_hist = {
                "type": "income",
                "year": inc["year"],
                "month": inc["month"],
                "day": inc["day"],
                "key": inc["key"],
                "mKey": inc["mKey"],
                "name": inc["name"],
                "gross": inc["amount"],
                "savings": savAmt,
                "usable": usable,
                "sourceId": inc["id"],
                "allocations": [],
            }
            history.append(income_hist)

        repayArrears(inc)

        next_inc = nextIncomeAfter(incomeEvents, inc["key"])
        nextKey = next_inc["key"] if next_inc else None
        daysUntilNext = daysInclusiveRemaining(inc, next_inc)
        livingProtect = targetDaily * daysUntilNext

        rawAllocations: List[Dict[str, Any]] = []

        def unpaidNeed(ob: Dict[str, Any]) -> int:
            return max(0, ob["amount"] - getReserve(ob["id"]))

        mandatoryObs = [
            o
            for o in obligations
            if o["id"] not in paid
            and not any(a["originalId"] == o["id"] for a in arrears)
            and isMandatoryForIncome(o, inc["key"], nextKey)
            and unpaidNeed(o) > 0
        ]
        mandatoryObs.sort(key=lambda a: (a["key"], a["priority"], str(a["id"])))

        mandatoryNeed = sum(unpaidNeed(ob) for ob in mandatoryObs)

        for ob in mandatoryObs:
            prevRes = getReserve(ob["id"])
            need = unpaidNeed(ob)
            free = freeCash()
            if need <= 0 or free <= 0:
                continue
            part = min(need, free)
            recordAllocation(rawAllocations, ob, prevRes, part, True)

        mandatoryShortfall = sum(unpaidNeed(ob) for ob in mandatoryObs)
        if mandatoryShortfall > 0:
            feasible = False
            peakDeficit = max(peakDeficit, mandatoryShortfall)
            if recordHistory:
                addWarning(
                    f"gap-{inc['id']}",
                    {
                        "day": inc["day"],
                        "monthKey": inc["mKey"],
                        "message": (
                            f"Недостаточно средств до следующего дохода после «{inc['name']}». "
                            f"Обязательные платежи до следующего дохода: {fmtRub(mandatoryNeed)}. "
                            f"Доступно: {fmtRub(usable)}. Не хватает: {fmtRub(mandatoryShortfall)}."
                        ),
                    },
                )

        freeAfter = freeCash()
        pool = max(0, freeAfter - livingProtect)

        optionalObs = [
            o
            for o in obligations
            if o["id"] not in paid
            and not any(a["originalId"] == o["id"] for a in arrears)
            and o["key"] > inc["key"]
            and not isMandatoryForIncome(o, inc["key"], nextKey)
            and unpaidNeed(o) > 0
        ]
        optionalObs.sort(key=lambda a: (a["key"], a["priority"], str(a["id"])))

        for ob in optionalObs:
            if pool <= 0:
                break
            prevRes = getReserve(ob["id"])
            need = unpaidNeed(ob)
            if need <= 0:
                continue
            part = min(need, pool)
            # Не размазываем пыль копеек по отдалённым платежам — оставляем в Free Cash.
            if part < 100 and part < need:
                continue
            if part <= 0:
                continue
            recordAllocation(rawAllocations, ob, prevRes, part, False)
            pool -= part

        remainingFree = freeCash()
        processedRemaining[inc["id"]] = remainingFree

        if strict and targetDaily > 0 and remainingFree < livingProtect:
            feasible = False

        displayItems = buildDisplayItems(
            obligations,
            paid,
            arrears,
            reserveAtStart,
            rawAllocations,
            inc,
            nextKey,
            getReserve,
        )

        for o in displayItems:
            if o["dueBeforeNextIncome"] and not o["fullyFunded"] and recordHistory:
                addWarning(
                    f"under-{inc['id']}-{o['paymentId']}",
                    {
                        "day": inc["day"],
                        "monthKey": inc["mKey"],
                        "message": (
                            f"После «{inc['name']}» платёж «{o['name']}» "
                            f"({fmtAbs(o['dueYear'], o['dueMonth'], o['dueDay'])}) "
                            f"не обеспечен полностью: {fmtRub(o['newReserve'])} / {fmtRub(o['total'])}."
                        ),
                    },
                )

        card = {
            "id": inc["id"],
            "type": "income",
            "name": inc["name"],
            "year": inc["year"],
            "month": inc["month"],
            "day": inc["day"],
            "key": inc["key"],
            "mKey": inc["mKey"],
            "isSelectedMonth": inc["isSelectedMonth"],
            "isFact": inc["isFact"],
            "gross": inc["amount"],
            "savings": savAmt,
            "usable": usable,
            "remaining": remainingFree,
            "totalReserve": sum(a["amount"] for a in rawAllocations),
            "allocations": displayItems,
            "freeCash": remainingFree,
            "nextIncomeKey": nextKey,
            "livingProtect": livingProtect,
            "daysUntilNext": daysUntilNext,
        }
        incomeCards.append(card)

        if recordHistory and income_hist is not None:
            income_hist["allocations"] = [dict(a) for a in displayItems]
            for d in displayItems:
                if d["amount"] > 0:
                    history.append(
                        {
                            "type": "reserve",
                            "year": inc["year"],
                            "month": inc["month"],
                            "day": inc["day"],
                            "key": inc["key"],
                            "mKey": inc["mKey"],
                            "name": d["name"],
                            "amount": d["amount"],
                            "paymentId": d["paymentId"],
                            "previousReserve": d["previousReserve"],
                            "newReserve": d["newReserve"],
                            "total": d["total"],
                            "description": (
                                f"Резерв «{d['name']}»: {fmtRub(d['previousReserve'])} + "
                                f"{fmtRub(d['amount'])} = {fmtRub(d['newReserve'])} / "
                                f"{fmtRub(d['total'])}"
                            ),
                        }
                    )

    def payObligations(cell: Dict[str, Any]) -> None:
        nonlocal cash, totalPaid, feasible, peakDeficit
        due = [
            o
            for o in obligations
            if o["key"] == cell["key"]
            and o["id"] not in paid
            and not any(a["originalId"] == o["id"] for a in arrears)
        ]
        due.sort(key=lambda a: (a["priority"], str(a["id"])))

        for payment in due:
            reserved = getReserve(payment["id"])
            otherReserved = reservedTotal() - reserved
            available = max(0, cash - otherReserved)
            pay = min(payment["amount"], available)

            if pay > 0:
                cash -= pay
                totalPaid += pay
            reserves.pop(payment["id"], None)

            if pay >= payment["amount"]:
                paid.add(payment["id"])
                if recordHistory:
                    history.append(
                        {
                            "type": "payment",
                            "year": cell["year"],
                            "month": cell["month"],
                            "day": cell["day"],
                            "key": cell["key"],
                            "mKey": cell["mKey"],
                            "name": payment["name"],
                            "amount": pay,
                        }
                    )
            else:
                shortage = payment["amount"] - pay
                feasible = False
                peakDeficit = max(peakDeficit, shortage)
                arrears.append(
                    {
                        "id": f"arrears-{payment['id']}",
                        "originalId": payment["id"],
                        "name": payment["name"],
                        "year": payment["year"],
                        "month": payment["month"],
                        "day": payment["day"],
                        "key": payment["key"],
                        "mKey": payment["mKey"],
                        "amount": shortage,
                        "kind": payment["kind"],
                    }
                )
                if recordHistory:
                    if pay > 0:
                        history.append(
                            {
                                "type": "payment",
                                "year": cell["year"],
                                "month": cell["month"],
                                "day": cell["day"],
                                "key": cell["key"],
                                "mKey": cell["mKey"],
                                "name": payment["name"],
                                "amount": pay,
                            }
                        )
                    history.append(
                        {
                            "type": "arrears",
                            "year": cell["year"],
                            "month": cell["month"],
                            "day": cell["day"],
                            "key": cell["key"],
                            "mKey": cell["mKey"],
                            "name": payment["name"],
                            "amount": shortage,
                        }
                    )
                    addWarning(
                        f"pay-{payment['id']}",
                        {
                            "day": payment["day"],
                            "monthKey": payment["mKey"],
                            "message": (
                                f"К дате оплаты «{payment['name']}» "
                                f"({fmtAbs(payment['year'], payment['month'], payment['day'])}) "
                                f"не хватило {fmtRub(shortage)} — образовалась просрочка."
                            ),
                        },
                    )

    def processDaily(cell: Dict[str, Any]) -> None:
        nonlocal cash, totalSpent, feasible, peakDeficit
        if cell["mKey"] != selKey:
            return
        for expense in [e for e in dailyExpenses if e["key"] == cell["key"]]:
            free = freeCash()
            if free >= expense["amount"]:
                cash -= expense["amount"]
                totalSpent += expense["amount"]
                if recordHistory:
                    history.append(
                        {
                            "type": "daily_expense",
                            "year": cell["year"],
                            "month": cell["month"],
                            "day": cell["day"],
                            "key": cell["key"],
                            "mKey": cell["mKey"],
                            "name": expense["name"],
                            "amount": expense["amount"],
                        }
                    )
            else:
                feasible = False
                over = expense["amount"] - max(0, free)
                peakDeficit = max(peakDeficit, over)
                if free > 0:
                    cash -= free
                    totalSpent += free
                    if recordHistory:
                        history.append(
                            {
                                "type": "daily_expense",
                                "year": cell["year"],
                                "month": cell["month"],
                                "day": cell["day"],
                                "key": cell["key"],
                                "mKey": cell["mKey"],
                                "name": expense["name"],
                                "amount": free,
                            }
                        )
                if recordHistory:
                    addWarning(
                        f"daily-{expense['id']}-{cell['key']}",
                        {
                            "day": cell["day"],
                            "monthKey": cell["mKey"],
                            "message": (
                                f"«{expense['name']}» на {fmtRub(expense['amount'])} "
                                f"превышает свободный остаток {fmtRub(free)}. "
                                f"Резервы обязательных платежей не тронуты. "
                                f"Дефицит: {fmtRub(over)}."
                            ),
                        },
                    )

    endY, endM = simEnd["year"], simEnd["month"]

    for cell in eachDay(BUDGET_START["year"], BUDGET_START["month"], endY, endM):
        if (
            cell["key"] == BUDGET_START_KEY
            and openingBalance > 0
            and not openingDone
        ):
            cash += openingBalance
            openingDone = True
            if recordHistory:
                history.append(
                    {
                        "type": "opening",
                        "year": cell["year"],
                        "month": cell["month"],
                        "day": cell["day"],
                        "key": cell["key"],
                        "mKey": cell["mKey"],
                        "name": "Остаток на 1 сентября 2026",
                        "gross": openingBalance,
                        "usable": openingBalance,
                    }
                )

        for e in [ev for ev in incomeEvents if ev["key"] == cell["key"]]:
            allocateFromIncome(e)
        payObligations(cell)
        processDaily(cell)

        if recordHistory and cell["mKey"] == selKey:
            nInc = next(
                (
                    e
                    for e in incomeEvents
                    if e["mKey"] == selKey and e["key"] > cell["key"]
                ),
                None,
            )
            if nInc:
                days = daysInclusiveRemaining(cell, nInc)
            else:
                days = max(1, dim(cell["year"], cell["month"]) - cell["day"] + 1)
            free = freeCash()
            safeDaily = (free // days) if free > 0 else 0
            history.append(
                {
                    "type": "day_end",
                    "year": cell["year"],
                    "month": cell["month"],
                    "day": cell["day"],
                    "key": cell["key"],
                    "mKey": cell["mKey"],
                    "cash": cash,
                    "reserved": reservedTotal(),
                    "free": free,
                    "savings": savings,
                    "arrearsTotal": sum(a["amount"] for a in arrears),
                    "dailyLimit": safeDaily,
                    "untilKey": nInc["key"] if nInc else None,
                    "untilDay": nInc["day"] if nInc else None,
                    "untilYear": nInc["year"] if nInc else None,
                    "untilMonth": nInc["month"] if nInc else None,
                }
            )

    validationErrors: List[str] = []
    for card in incomeCards:
        for a in card["allocations"]:
            if a["previousReserve"] + a["amount"] != a["newReserve"]:
                validationErrors.append(
                    f"{card['name']} · {a['name']}: "
                    f"{a['previousReserve']}+{a['amount']}≠{a['newReserve']}"
                )
            if a["newReserve"] > a["total"]:
                validationErrors.append(
                    f"{a['name']}: резерв {a['newReserve']} > суммы {a['total']}"
                )
    for i, msg in enumerate(validationErrors):
        addWarning(f"validation-{i}", {"message": f"Ошибка расчёта: {msg}"})

    arrearsTotal = sum(a["amount"] for a in arrears)
    if arrearsTotal > 0:
        feasible = False

    return {
        "cash": cash,
        "savings": savings,
        "reserved": reservedTotal(),
        "free": freeCash(),
        "paid": totalPaid,
        "everydaySpent": totalSpent,
        "arrearsTotal": arrearsTotal,
        "arrears": [dict(a) for a in arrears],
        "deficit": peakDeficit,
        "feasible": feasible,
        "targetDailyLimit": targetDaily,
        "warnings": warnings,
        "history": history,
        "incomeCards": incomeCards,
        "selKey": selKey,
        "chronology": chronology,
        "validationErrors": validationErrors,
        "totalArrearsPaid": totalArrearsPaid,
    }


def pickViewSnapshot(
    result: Dict[str, Any], chronology: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    selKey = chronology["selKey"]
    day = chronology.get("viewDay") or 1
    snaps = [
        h
        for h in result["history"]
        if h["type"] == "day_end" and h["mKey"] == selKey and h["day"] == day
    ]
    if snaps:
        return snaps[-1]
    snaps = [
        h
        for h in result["history"]
        if h["type"] == "day_end" and h["mKey"] == selKey
    ]
    return snaps[-1] if snaps else None


def pickMonthEndSnapshot(
    result: Dict[str, Any], chronology: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    snaps = [
        h
        for h in result["history"]
        if h["type"] == "day_end" and h["mKey"] == chronology["selKey"]
    ]
    return snaps[-1] if snaps else None


_MONEY_FIELDS = frozenset(
    [
        "cash",
        "savings",
        "reserved",
        "free",
        "paid",
        "everydaySpent",
        "arrearsTotal",
        "deficit",
        "safeDailyLimit",
        "targetDailyLimit",
        "totalArrearsPaid",
        "gross",
        "usable",
        "amount",
        "previousReserve",
        "newReserve",
        "total",
        "remainingToFund",
        "remaining",
        "totalReserve",
        "freeCash",
        "livingProtect",
        "dailyLimit",
    ]
)


def toRublesView(result: Dict[str, Any]) -> Dict[str, Any]:
    deep_keys = frozenset(
        ["allocations", "history", "incomeCards", "arrears", "warnings"]
    )
    snap_keys = frozenset(["viewSnapshot", "monthEndSnapshot"])

    def convertDeep(node: Any) -> Any:
        if isinstance(node, list):
            return [convertDeep(x) for x in node]
        if not isinstance(node, dict):
            return node
        out: Dict[str, Any] = {}
        for k, v in node.items():
            if k in _MONEY_FIELDS and isinstance(v, (int, float)) and not isinstance(
                v, bool
            ):
                out[k] = fromKop(v)
            elif k in deep_keys:
                out[k] = convertDeep(v)
            elif k in snap_keys:
                out[k] = convertDeep(v)
            elif k == "chronology":
                out[k] = v
            else:
                out[k] = v
        return out

    rub = convertDeep(result)
    rub["_kop"] = {
        "cash": result["cash"],
        "savings": result["savings"],
        "reserved": result["reserved"],
        "free": result["free"],
        "paid": result["paid"],
        "everydaySpent": result["everydaySpent"],
        "arrearsTotal": result["arrearsTotal"],
        "deficit": result["deficit"],
    }
    return rub


def calculateBudget(input_: Dict[str, Any]) -> Dict[str, Any]:
    chronology = buildChronology(input_)
    safeDaily = findMaxSafeDailyLimit(chronology)
    result = simulate(
        chronology,
        {
            "targetDailyLimit": safeDaily,
            "strictFeasibility": False,
            "recordHistory": True,
        },
    )
    result["safeDailyLimit"] = safeDaily
    result["viewSnapshot"] = pickViewSnapshot(result, chronology)
    result["monthEndSnapshot"] = pickMonthEndSnapshot(result, chronology)
    return toRublesView(result)


def checkInvariants(
    result: Dict[str, Any], inputSummary: Optional[Dict[str, Any]] = None
) -> List[str]:
    errors: List[str] = []
    cash = result["cash"]
    reserved = result["reserved"]
    free = result["free"]
    if cash != reserved + free:
        errors.append(f"Cash ≠ Reserved + FreeCash: {cash} ≠ {reserved}+{free}")

    for card in result.get("incomeCards") or []:
        if card["gross"] != card["savings"] + card["usable"]:
            errors.append(
                f"Доход {card['name']}: {card['gross']} ≠ "
                f"{card['savings']}+{card['usable']}"
            )

    if inputSummary:
        expected = (
            inputSummary["openingKop"]
            + inputSummary["usableIncomesKop"]
            - result["paid"]
            - result["everydaySpent"]
        )
        if expected != cash:
            errors.append(
                f"Баланс: opening+usable-paid-spent={expected}, cash={cash}"
            )

    return errors
