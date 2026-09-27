from __future__ import annotations

import time
from collections import defaultdict

from .models import Event, EventType


_LOUD_TYPES = {EventType.RESTOCK, EventType.PREORDER_OPEN}

_COLOR = {
    EventType.RESTOCK: 0x2ECC71,
    EventType.PREORDER_OPEN: 0x3498DB,
    EventType.NEW_PRODUCT: 0x9B59B6,
    EventType.PRICE_CHANGE: 0xF1C40F,
}

_LABEL = {
    EventType.RESTOCK: "🟢 RESTOCK",
    EventType.PREORDER_OPEN: "🔵 PREORDER OPEN",
    EventType.NEW_PRODUCT: "🟣 NEW LISTING",
    EventType.PRICE_CHANGE: "🟡 PRICE CHANGE",
}


def route_loud(event: Event) -> bool:
    return event.type in _LOUD_TYPES


def route_deal_or_urgent(event: Event) -> bool:
    v = event.verdict
    if v is not None and v.status == "deal":
        return True
    return event.type in _LOUD_TYPES


def _market_line(event: Event) -> str:
    v = event.verdict

    if (
        v is None
        or v.status == "na"
        or v.market_usd is None
        or v.store_usd is None
    ):
        return "n/a"

    if v.status == "deal":
        return (
            f"🔥 {v.pct_under * 100:.0f}% under market "
            f"(≈US${v.store_usd:.2f} vs US${v.market_usd:.2f})"
        )

    if v.pct_under is not None and v.pct_under > 0:
        rel = f"{v.pct_under * 100:.0f}% under market"
    elif v.pct_under is not None and v.pct_under < 0:
        rel = f"{-v.pct_under * 100:.0f}% above market"
    else:
        rel = "at market"

    return f"{rel} (≈US${v.store_usd:.2f} vs US${v.market_usd:.2f})"


def build_embed(event: Event) -> dict:
    p = event.product

    cur = f"{p.currency} {p.price:.2f}"

    if event.type == EventType.PRICE_CHANGE and event.previous_price is not None:
        arrow = "▲" if p.price > event.previous_price else "▼"
        price_line = (
            f"{p.currency} {event.previous_price:.2f} → "
            f"{cur} {arrow}"
        )
    else:
        price_line = cur

    fields = [
        {"name": "Store", "value": p.store, "inline": True},
        {"name": "Price", "value": price_line, "inline": True},
        {"name": "Franchise", "value": p.franchise or "—", "inline": True},
        {"name": "Market", "value": _market_line(event), "inline": True},
    ]

    embed = {
        "title": f"{p.title} — {_LABEL[event.type]}"[:256],
        "url": p.url,
        "color": _COLOR[event.type],
        "fields": fields,
    }

    if p.image:
        embed["image"] = {"url": p.image}

    return embed


def _payload(embed: dict, loud: bool) -> dict:
    payload = {"embeds": [embed]}

    if loud:
        payload["content"] = "@here"
        payload["allowed_mentions"] = {"parse": ["everyone"]}

    return payload


def _franchise_key(event: Event) -> str | None:
    franchise = (event.product.franchise or "").strip().lower()

    if franchise in {"pokemon", "pokémon"}:
        return "pokemon"

    if franchise in {"one piece", "one-piece"}:
        return "one_piece"

    if franchise in {
        "dragon ball",
        "dragon ball super",
        "dragonball",
        "fusion world",
    }:
        return "dragon_ball"

    return None


def send_events(
    events,
    post_loud,
    post_quiet,
    max_events_per_store,
    route=route_loud,
    delay_seconds=0.0,
    sleep=time.sleep,
    post_pokemon=None,
    post_one_piece=None,
    post_dragon_ball=None,
    post_instock=None,
) -> int:
    by_store: dict[str, list[Event]] = defaultdict(list)

    for event in events:
        by_store[event.product.store].append(event)

    actions = []

    for store, store_events in by_store.items():
        if len(store_events) > max_events_per_store:
            actions.append(
                (
                    post_quiet,
                    {
                        "content": (
                            f"📦 **{store}**: {len(store_events)} changes this run "
                            f"(flood cap {max_events_per_store} exceeded — summarized)."
                        )
                    },
                )
            )
            continue

        for event in store_events:
            loud = route(event)
            payload = _payload(build_embed(event), loud)

            # Keep existing master/deal/tracker routing.
            actions.append(
                (post_loud if loud else post_quiet, payload)
            )

            # Franchise-specific routing.
            franchise = _franchise_key(event)

            if franchise == "pokemon" and post_pokemon is not None:
                actions.append((post_pokemon, payload))

            elif franchise == "one_piece" and post_one_piece is not None:
                actions.append((post_one_piece, payload))

            elif franchise == "dragon_ball" and post_dragon_ball is not None:
                actions.append((post_dragon_ball, payload))

            # Dedicated in-stock feed.
            # Only actual RESTOCK events are sent here.
            if event.type == EventType.RESTOCK and post_instock is not None:
                actions.append((post_instock, payload))

    for i, (poster, payload) in enumerate(actions):
        if i and delay_seconds:
            sleep(delay_seconds)

        poster(payload)

    return len(actions)
