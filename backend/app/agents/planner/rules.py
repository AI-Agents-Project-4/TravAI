"""The planner's deterministic half: costs, schedule checks and budget fitting.

The model only proposes (themes, which flight/hotel, which activity on which
day). Everything with a number in it is decided here, from stored option prices,
so a plan can never claim a total the options don't add up to (product rule 1)
and the infeasible verdict never depends on the model (product rule 3).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from app.agents.planner.types import (
    DayPlan,
    Dropped,
    Item,
    PlanDraft,
    PlanningFailed,
    ResearchFacts,
    Scheduled,
    TripFacts,
)

DAY_START = 9 * 60  # 09:00
DAY_END = 23 * 60  # nothing ends after 23:00
ACTIVE_MINUTES = 600  # at most 10 hours of activities and transport a day
GAP_MINUTES = 30  # walking/transit between items
DEFAULT_MINUTES = 90
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
STALE_AFTER = timedelta(hours=48)
SAFETY_LEVELS = ("reconsider", "do_not_travel")
CONTENT_KINDS = ("activity", "food")


def money(amount: Decimal, currency: str) -> str:
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(currency)
    text = f"{amount:,.0f}" if amount == amount.to_integral() else f"{amount:,.2f}"
    return f"{symbol}{text}" if symbol else f"{text} {currency}"


def round_up_to(amount: Decimal, step: int) -> Decimal:
    return (amount / step).to_integral_value(rounding=ROUND_CEILING) * step


def _clock(minutes: int) -> str:
    minutes = min(minutes, 24 * 60 - 1)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _parse_clock(value: Any) -> int | None:
    try:
        h, m = str(value).split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


@dataclass
class Fixed:
    """The parts of a plan that aren't a choice of activities."""

    flight: Item | None
    hotels: dict[str | None, Item]  # one per stop; the first stop's is `hotel_option_id`
    # (day, "start" | "end", item): return flight, transfers, drives, trains, later hotels
    placed: list[tuple[int, str, Item]] = field(default_factory=list)

    @property
    def hotel(self) -> Item | None:
        return next(iter(self.hotels.values()), None)

    def items(self) -> list[Item]:
        out = [i for i in (self.flight,) if i]
        out += list(self.hotels.values())
        out += [i for _, _, i in self.placed]
        return out

    def cost(self) -> Decimal:
        # Later-stop hotels are in both `hotels` and `placed`: count each hotel once.
        total = sum((h.price for h in self.hotels.values()), Decimal(0))
        if self.flight is not None:
            total += self.flight.price
        return total + sum((i.price for _, _, i in self.placed if i.kind != "hotel"), Decimal(0))


class Catalog:
    """All options for one trip, indexed the ways the planner needs."""

    def __init__(self, items: Iterable[Item], trip: TripFacts, research: ResearchFacts):
        self.trip = trip
        self.research = research
        self.items = [i for i in items if i.currency == trip.currency]
        self.other_currency = [i for i in items if i.currency != trip.currency]
        self.by_id = {i.id: i for i in self.items}
        self.flights = [i for i in self.items if i.kind == "flight"]
        self.hotels = [i for i in self.items if i.kind == "hotel"]
        self.activities = [i for i in self.items if i.kind in CONTENT_KINDS]
        self.n_days = trip.duration_days
        self.dates = [trip.start_date + timedelta(days=d) for d in range(self.n_days)]
        self.stops = self._stops()
        self._day_stop = [self._stop_on(d) for d in self.dates]
        self._centres = self._stop_centres()

    # ---- stops and days --------------------------------------------------

    def _stops(self) -> list[str | None]:
        """Stops in travel order, from hotel check-in dates; [None] for a single place."""
        firsts: dict[str, str] = {}
        for h in self.hotels:
            if h.stop:
                check_in = str(h.details.get("check_in") or "9999")
                firsts[h.stop] = min(firsts.get(h.stop, check_in), check_in)
        ordered = sorted(firsts, key=lambda s: firsts[s])
        return list(ordered) if len(ordered) > 1 else [ordered[0] if ordered else None]

    def _stop_centres(self) -> dict[str, tuple[float, float]]:
        points: dict[str, list[tuple[float, float]]] = {}
        for h in self.hotels:
            if h.stop and h.lat is not None and h.lng is not None:
                points.setdefault(h.stop, []).append((h.lat, h.lng))
        return {
            stop: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            for stop, pts in points.items()
        }

    def stop_for(self, item: Item) -> str | None:
        """Which stop an option belongs to. Hotels and transport say so; for activities
        it's the nearest stop (by its hotels' locations), since they only name a neighborhood."""
        if len(self.stops) == 1:
            return self.stops[0]
        if item.kind in ("hotel", "transport", "flight"):
            return item.stop
        if item.lat is None or item.lng is None or not self._centres:
            return item.stop
        lat, lng = item.lat, item.lng
        return min(
            self._centres,
            key=lambda s: (self._centres[s][0] - lat) ** 2 + (self._centres[s][1] - lng) ** 2,
        )

    def _stop_on(self, day: date) -> str | None:
        if len(self.stops) == 1:
            return self.stops[0]
        for h in self.hotels:
            try:
                start = date.fromisoformat(str(h.details.get("check_in")))
                end = date.fromisoformat(str(h.details.get("check_out")))
            except ValueError:
                continue
            if start <= day < end:
                return h.stop
        return self.stops[-1]  # departure day

    def stop_of(self, day: int) -> str | None:
        return self._day_stop[day - 1]

    def first_day_at(self, stop: str | None) -> int:
        return next((d for d in range(1, self.n_days + 1) if self.stop_of(d) == stop), 1)

    def nights(self) -> int:
        return self.n_days if self.n_days > 1 else 0

    # ---- choices ---------------------------------------------------------

    def hotels_at(self, stop: str | None) -> list[Item]:
        if stop is None:
            return sorted(self.hotels, key=lambda h: h.price)
        return sorted((h for h in self.hotels if h.stop == stop), key=lambda h: h.price)

    def flight_choices(self) -> list[Item]:
        """Flights that can be a plan's main flight: round trips, or outbound one-ways."""
        rt = [f for f in self.flights if f.role == "round_trip"]
        return rt or [f for f in self.flights if f.role == "outbound"]

    def cheapest_return(self) -> Item | None:
        returns = [f for f in self.flights if f.role == "return"]
        return min(returns, key=lambda f: f.price) if returns else None

    def _transfer(self, airport: Any, stop: str | None) -> Item | None:
        transfers = [i for i in self.items if i.role == "airport_transfer"]
        match = [t for t in transfers if airport and t.details.get("airport") == airport]
        match = match or [t for t in transfers if stop and t.stop == stop]
        return min(match, key=lambda t: t.price) if match else None

    def fixed_for(self, flight: Item | None, hotels: dict[str | None, Item]) -> Fixed:
        """Everything a plan must pay for besides activities, for a given flight and hotels."""
        n = self.n_days
        placed: list[tuple[int, str, Item]] = []
        if self.trip.transport_mode == "fly" and flight is not None:
            depart_airport = flight.details.get("return_depart_airport")
            if flight.role == "outbound":
                back = self.cheapest_return()
                if back is not None:
                    placed.append((n, "end", back))
                    depart_airport = back.details.get("depart_airport")
            arrive = self._transfer(flight.details.get("arrive_airport"), self.stops[0])
            if arrive is not None:
                placed.append((1, "start", arrive))
            leave = self._transfer(depart_airport, self.stops[-1])
            if leave is not None:
                placed.append((n, "end", leave))
        if self.trip.transport_mode == "drive":
            drives = [i for i in self.items if i.role == "drive"]
            if drives:
                drive = min(drives, key=lambda i: i.price)
                placed += [(1, "start", drive), (n, "end", drive)]  # there and back
        for a, b in zip(self.stops, self.stops[1:], strict=False):
            legs = [
                i
                for i in self.items
                if i.role == "intercity" and i.details.get("from") == a and i.details.get("to") == b
            ]
            if legs:
                placed.append((self.first_day_at(b), "start", min(legs, key=lambda i: i.price)))
        for stop, hotel in list(hotels.items())[1:]:
            placed.append((self.first_day_at(stop), "start", hotel))
        return Fixed(flight=flight, hotels=hotels, placed=placed)

    def cheapest_hotels(self) -> dict[str | None, Item]:
        if self.nights() == 0:
            return {}
        return {stop: self.hotels_at(stop)[0] for stop in self.stops if self.hotels_at(stop)}

    def cheapest_fixed(self) -> Fixed:
        hotels = self.cheapest_hotels()
        options: list[Item | None] = list(self.flight_choices()) or [None]
        candidates = [self.fixed_for(f, hotels) for f in options]
        return min(candidates, key=lambda f: f.cost())

    def check_enough_data(self) -> None:
        """Raise PlanningFailed if a plan would have to leave out something it needs."""
        problems = []
        if self.trip.transport_mode == "fly" and not self.flight_choices():
            problems.append("no flights")
        if self.nights() and len(self.cheapest_hotels()) < len(self.stops):
            missing = [s or self.trip.destination for s in self.stops if not self.hotels_at(s)]
            problems.append(f"no places to stay in {', '.join(missing)}")
        if self.trip.transport_mode == "drive" and not any(i.role == "drive" for i in self.items):
            problems.append("no driving route")
        if problems:
            gaps = "; ".join(self.research.gaps[:3])
            raise PlanningFailed(
                f"The research found {' and '.join(problems)} for this trip, so an honest plan "
                "isn't possible yet." + (f" Details: {gaps}" if gaps else "")
            )

    # ---- feasibility -----------------------------------------------------

    def minimum_total(self) -> Decimal:
        """Cheapest flight + hotels + required transport + food and local transport."""
        return self.cheapest_fixed().cost() + self.research.other_costs


# ---- assembling a plan ---------------------------------------------------


def _duration(item: Item) -> int:
    if item.kind in ("flight", "hotel"):
        return 0
    minutes = item.duration_minutes or DEFAULT_MINUTES
    if item.role == "day_trip":
        minutes += int(item.details.get("round_trip_from_base_minutes") or 0)
    return min(minutes, ACTIVE_MINUTES)


def _fits_hours(item: Item, day: date | None, start: int, minutes: int) -> tuple[bool, int, str]:
    """(fits, start time, reason) for opening hours on that date."""
    hours = item.hours
    if hours is None or day is None:
        return True, start, ""
    today = hours.get(WEEKDAYS[day.weekday()])
    if not isinstance(today, dict):
        return False, start, f"Closed on {day.strftime('%A')}s."
    opens, closes = _parse_clock(today.get("open")), _parse_clock(today.get("close"))
    if opens is None or closes is None:
        return True, start, ""
    if closes <= opens:
        closes += 24 * 60  # closes after midnight
    begin = max(start, opens)
    if begin + minutes > closes:
        return (
            False,
            start,
            f"Not open long enough on {day.strftime('%A')} ({today['open']}–{today['close']}).",
        )
    return True, begin, ""


@dataclass
class _Slot:
    item: Item
    locked: bool = False
    required: bool = False
    where: str = "middle"  # start | middle | end


def _time_day(
    slots: list[_Slot], day: date | None
) -> tuple[list[Scheduled], list[tuple[_Slot, str]]]:
    """Give start/end times in order. Returns (scheduled, misfits). Locked and required items always stay."""
    ordered = (
        [s for s in slots if s.where == "start"]
        + [s for s in slots if s.where == "middle"]
        + [s for s in slots if s.where == "end"]
    )
    t, active = DAY_START, 0
    out: list[Scheduled] = []
    misfits: list[tuple[_Slot, str]] = []
    for slot in ordered:
        minutes = _duration(slot.item)
        keep = slot.locked or slot.required
        if minutes == 0:
            out.append(Scheduled(slot.item.id, None, None, slot.locked))
            continue
        fits, begin, reason = _fits_hours(slot.item, day, t, minutes)
        if fits and (begin + minutes > DAY_END or active + minutes > ACTIVE_MINUTES):
            fits, reason = False, "The day is already full."
        if not fits and not keep:
            misfits.append((slot, reason))
            continue
        out.append(Scheduled(slot.item.id, _clock(begin), _clock(begin + minutes), slot.locked))
        t, active = begin + minutes + GAP_MINUTES, active + minutes
    return out, misfits


@dataclass
class PlanInput:
    """A proposal to assemble: from the model, the fallback, or the user's edited plan."""

    title: str
    summary: str
    flight_id: str | None
    hotel_ids: list[str]
    days: dict[int, list[Scheduled]]  # day -> items in order (locked flags from the user)


class Assembler:
    def __init__(self, catalog: Catalog):
        self.cat = catalog

    def _choose_fixed(self, plan: PlanInput) -> Fixed:
        cat = self.cat
        choices = {f.id: f for f in cat.flight_choices()}
        flight = choices.get(plan.flight_id or "")
        if cat.trip.transport_mode == "fly" and flight is None:
            flight = cat.cheapest_fixed().flight
        if cat.trip.transport_mode != "fly":
            flight = None
        hotels: dict[str | None, Item] = {}
        if cat.nights():
            wanted = [cat.by_id[h] for h in plan.hotel_ids if h in cat.by_id]
            for stop in cat.stops:
                pick = next(
                    (h for h in wanted if h.kind == "hotel" and (stop is None or h.stop == stop)),
                    None,
                )
                if pick is None and cat.hotels_at(stop):
                    pick = cat.hotels_at(stop)[0]
                if pick is not None:
                    hotels[stop] = pick
        return cat.fixed_for(flight, hotels)

    def assemble(
        self,
        plan: PlanInput,
        *,
        removed: set[str] | None = None,
        user_items: set[str] | None = None,
        allow_swap: bool = True,
    ) -> tuple[PlanDraft, list[Dropped]]:
        """Build a checked, timed, priced plan.

        Locked items are never dropped or moved (product rule 5). `user_items` are the
        unlocked items the user kept; any of them that don't survive are reported in
        `dropped`. Removed items never come back.
        """
        cat = self.cat
        removed = removed or set()
        user_items = user_items or set()
        dropped: list[Dropped] = []
        fixed = self._choose_fixed(plan)
        fixed_ids = {i.id for i in fixed.items()}

        def drop(item_id: str, reason: str) -> None:
            if item_id in user_items and all(d.option_id != item_id for d in dropped):
                dropped.append(Dropped(item_id, reason))

        # 1. Collect slots per day. Locked items stay where the user put them.
        days: dict[int, list[_Slot]] = {d: [] for d in range(1, cat.n_days + 1)}
        seen: set[str] = set()
        for day_no in sorted(plan.days):
            for s in plan.days[day_no]:
                item = cat.by_id.get(s.option_id)
                if item is None or s.option_id in removed:
                    if item is None:
                        drop(s.option_id, "This option is no longer available.")
                    continue
                if not s.locked and (s.option_id in fixed_ids or item.kind in ("flight", "hotel")):
                    continue  # required items are re-added below
                if s.option_id in seen and not s.locked:
                    continue
                target = day_no if day_no in days else (cat.n_days if s.locked else None)
                if target is None:
                    drop(s.option_id, f"Your trip has {cat.n_days} days.")
                    continue
                seen.add(s.option_id)
                days[target].append(_Slot(item, locked=s.locked))

        # 2. Required items (transfers, drives, return flight, later hotels), unless removed.
        for day_no, where, item in fixed.placed:
            if item.id in removed:
                continue
            already = [x for x in days[day_no] if x.item.id == item.id and x.locked]
            if already:
                continue
            days[day_no].append(_Slot(item, required=True, where=where))

        # 3. Day trips take the whole day; items must be at the day's stop.
        for day_no in days:
            trips = [slot for slot in days[day_no] if slot.item.role == "day_trip"]
            keep_trip = next((t for t in trips if t.locked), trips[0] if trips else None)
            if keep_trip is None:
                continue
            for slot in list(days[day_no]):
                if (
                    slot is keep_trip
                    or slot.locked
                    or slot.required
                    or slot.item.kind not in CONTENT_KINDS
                ):
                    continue
                days[day_no].remove(slot)
                self._move_or_drop(days, slot, day_no, "A day trip takes the whole day.", drop)

        for day_no in days:
            stop = cat.stop_of(day_no)
            for slot in list(days[day_no]):
                at = cat.stop_for(slot.item)
                if slot.locked or slot.required or stop is None or at in (None, stop):
                    continue
                days[day_no].remove(slot)
                reason = f"It's in {at}, not {stop}."
                self._move_or_drop(days, slot, day_no, reason, drop)

        # 4. Opening hours and day length.
        timed = self._time_all(days, drop)

        # 5. Budget: drop unlocked activities, most expensive first; then cheaper flight/hotels.
        budget = cat.trip.budget

        def total_of(fx: Fixed, tm: dict[int, list[Scheduled]]) -> Decimal:
            return self._totals(fx, tm)[1]

        while total_of(fixed, timed) > budget:
            candidates = [
                (cat.by_id[s.option_id].price, d, s)
                for d, items in timed.items()
                for s in items
                if not s.locked
                and cat.by_id[s.option_id].kind in CONTENT_KINDS
                and cat.by_id[s.option_id].price > 0
            ]
            if not candidates:
                break
            price, d, s = max(candidates, key=lambda c: c[0])
            over = total_of(fixed, timed) - budget
            timed[d].remove(s)
            for slots in days.values():
                for x in list(slots):
                    if x.item.id == s.option_id and not x.locked:
                        slots.remove(x)
            drop(
                s.option_id,
                f"Dropped to stay under budget (it costs {money(price, cat.trip.currency)}; the plan was {money(over, cat.trip.currency)} over).",
            )
        timed = self._time_all(days, drop)  # re-time the days after drops
        if allow_swap and total_of(fixed, timed) > budget:
            cheap = cat.cheapest_fixed()
            if cheap.cost() < fixed.cost():
                for slots in days.values():
                    slots[:] = [s for s in slots if not s.required]
                fixed = cat.fixed_for(cheap.flight, cheap.hotels)
                for day_no, where, item in fixed.placed:
                    if item.id not in removed:
                        days[day_no].append(_Slot(item, required=True, where=where))
                timed = self._time_all(days, drop)

        breakdown, total = self._totals(fixed, timed)
        draft = PlanDraft(
            title=plan.title,
            summary=plan.summary,
            flight_id=fixed.flight.id if fixed.flight else None,
            hotel_id=fixed.hotel.id if fixed.hotel else None,
            days=[DayPlan(d, cat.dates[d - 1], timed[d]) for d in range(1, cat.n_days + 1)],
            cost_breakdown=breakdown,
            total=total,
            warnings=self.warnings(fixed, timed, total, removed),
        )
        return draft, dropped

    def price(self, plan: PlanInput) -> PlanDraft:
        """Totals and warnings for a plan exactly as given (saving the user's edits).

        Nothing is moved, dropped or re-timed: the user's plan is theirs. Unknown ids
        are ignored here; the API rejects them before this is called.
        """
        cat = self.cat
        fixed = self._choose_fixed(plan)
        timed = {
            d: [s for s in plan.days.get(d, []) if s.option_id in cat.by_id]
            for d in range(1, cat.n_days + 1)
        }
        breakdown, total = self._totals(fixed, timed)
        return PlanDraft(
            title=plan.title,
            summary=plan.summary,
            flight_id=fixed.flight.id if fixed.flight else None,
            hotel_id=fixed.hotel.id if fixed.hotel else None,
            days=[DayPlan(d, cat.dates[d - 1], timed[d]) for d in range(1, cat.n_days + 1)],
            cost_breakdown=breakdown,
            total=total,
            warnings=self.warnings(fixed, timed, total, set()),
        )

    def _move_or_drop(
        self, days: dict[int, list[_Slot]], slot: _Slot, from_day: int, reason: str, drop: Any
    ) -> None:
        cat = self.cat
        for d in sorted(days, key=lambda x: (len(days[x]), x)):
            at = cat.stop_for(slot.item)
            if d == from_day or (at and cat.stop_of(d) not in (None, at)):
                continue
            if any(s.item.role == "day_trip" for s in days[d]):
                continue
            days[d].append(slot)
            return
        drop(slot.item.id, reason)

    def _time_all(self, days: dict[int, list[_Slot]], drop: Any) -> dict[int, list[Scheduled]]:
        cat = self.cat
        timed: dict[int, list[Scheduled]] = {}
        pending: list[tuple[_Slot, str, int]] = []
        for d in sorted(days):
            scheduled, misfits = _time_day(days[d], cat.dates[d - 1])
            timed[d] = scheduled
            for slot, reason in misfits:
                days[d].remove(slot)
                pending.append((slot, reason, d))
        for slot, reason, from_day in pending:  # try once on another day at the same stop
            placed = False
            for d in sorted(days, key=lambda x: (len(days[x]), x)):
                if d == from_day or (
                    cat.stop_for(slot.item)
                    and cat.stop_of(d) not in (None, cat.stop_for(slot.item))
                ):
                    continue
                if any(s.item.role == "day_trip" for s in days[d]) and slot.item.role != "day_trip":
                    continue
                trial, misfits = _time_day([*days[d], slot], cat.dates[d - 1])
                if not misfits:
                    days[d].append(slot)
                    timed[d] = trial
                    placed = True
                    break
            if not placed:
                drop(slot.item.id, reason or "It didn't fit the schedule.")
        return timed

    def _totals(
        self, fixed: Fixed, timed: dict[int, list[Scheduled]]
    ) -> tuple[list[tuple[str, Decimal]], Decimal]:
        """Same arithmetic as the frontend's running total: flight + hotel + every scheduled item + other costs."""
        cat = self.cat
        by: dict[str, Decimal] = {}

        def add(category: str, amount: Decimal) -> None:
            by[category] = by.get(category, Decimal(0)) + amount

        if fixed.flight:
            add("flight", fixed.flight.price)
        if fixed.hotel:
            add("hotel", fixed.hotel.price)
        for items in timed.values():
            for s in items:
                item = cat.by_id[s.option_id]
                add(item.kind, item.price)
        if cat.research.other_costs > 0:
            add("other", cat.research.other_costs)
        order = ["flight", "hotel", "transport", "activity", "food", "other"]
        breakdown = [(c, by[c]) for c in order if c in by]
        return breakdown, sum((a for _, a in breakdown), Decimal(0))

    def warnings(
        self, fixed: Fixed, timed: dict[int, list[Scheduled]], total: Decimal, removed: set[str]
    ) -> list[dict[str, Any]]:
        cat = self.cat
        cur = cat.trip.currency
        out: list[dict[str, Any]] = []
        for a in cat.research.advisories:
            if a.get("level") in SAFETY_LEVELS or a.get("map_data_reliability") in (
                "poor",
                "uncertain",
            ):
                out.append(
                    {
                        "kind": "safety",
                        "message": f"Travel advisory for {a.get('region')}: {a.get('summary', '')[:300]} Map and price data there may be out of date.",
                        "source_url": a.get("source_url"),
                    }
                )
        used = [cat.by_id[s.option_id] for items in timed.values() for s in items]
        used += [i for i in (fixed.flight, fixed.hotel) if i]
        if any(i.details.get("synthetic") for i in used):
            out.append(
                {
                    "kind": "estimate",
                    "message": "TEST DATA: some flight and hotel prices are synthetic, generated for testing. They are not real quotes.",
                }
            )
        estimates = [i for i in used if i.is_estimate]
        if estimates or cat.research.other_costs > 0:
            parts = []
            if estimates:
                parts.append(
                    f"{len(estimates)} price{'s are' if len(estimates) > 1 else ' is an'} estimate{'s' if len(estimates) > 1 else ''}, rounded up"
                )
            if cat.research.other_costs > 0:
                parts.append(
                    f"food and local transport ({money(cat.research.other_costs, cur)}) is an estimate, set high, with no single source"
                )
            out.append({"kind": "estimate", "message": "; ".join(parts).capitalize() + "."})
        if cat.trip.start_date_assumed:
            out.append(
                {
                    "kind": "estimate",
                    "message": f"No start date was given, so prices are for a trip starting {cat.trip.start_date.isoformat()}.",
                }
            )
        now = datetime.now(UTC)
        oldest = min((i.fetched_at for i in used), default=None)
        if oldest is not None and now - oldest > STALE_AFTER:
            out.append(
                {
                    "kind": "stale_data",
                    "message": f"Some prices were recorded on {oldest.date().isoformat()} and may have changed. Check the source links before booking.",
                }
            )
        if total > cat.trip.budget:
            out.append(
                {
                    "kind": "over_budget",
                    "message": f"This plan is {money(total - cat.trip.budget, cur)} over your {money(cat.trip.budget, cur)} budget. Your locked items or required costs alone go over it. Unlock or remove something to fit.",
                }
            )
        missing = [i for i in fixed.items() if i.id in removed and i.kind == "transport"]
        if missing:
            out.append(
                {
                    "kind": "estimate",
                    "message": "You removed required transport ("
                    + ", ".join(i.title for i in missing)
                    + "), so the total doesn't include getting there.",
                }
            )
        return out


def infeasible_reason(cat: Catalog, minimum: Decimal) -> str:
    trip = cat.trip
    fixed = cat.cheapest_fixed()
    parts = []
    if fixed.flight:
        parts.append(f"the cheapest flight ({money(fixed.flight.price, trip.currency)})")
    if fixed.hotels:
        parts.append(
            f"the cheapest place to stay ({money(sum((h.price for h in fixed.hotels.values()), Decimal(0)), trip.currency)} for {cat.nights()} nights)"
        )
    if cat.research.other_costs:
        parts.append(f"food and local transport ({money(cat.research.other_costs, trip.currency)})")
    what = ", ".join(parts) if parts else "the required costs"
    return (
        f"For {trip.duration_days} days, {what} come to at least {money(round_up_to(minimum, 50), trip.currency)} "
        f"before any activities. That's more than your {money(trip.budget, trip.currency)} budget."
    )
