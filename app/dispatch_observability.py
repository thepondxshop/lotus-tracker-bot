"""DEL1: phase attribution and a bounded optional FX lookup; no event replay."""
import asyncio
import contextvars
import json
import time
from app.display_time import new_york_time

_state = contextvars.ContextVar('lotus_dispatch_state', default=None)


def mark_phase(name, **details):
    state = _state.get()
    if state is not None:
        state.update(phase=name, phase_started=time.monotonic(), **details)


def primary_confirmed(message, event):
    """Record Discord's timestamp immediately, even if later mention/save work times out."""
    mark_phase('RECIPIENT_CHUNKS', primary_message_id=str(message.id))
    print('LOTUS PRIMARY DELIVERED | ' + json.dumps({
        'message_id': str(message.id), 'store': event.get('store_name'),
        'product_url': event.get('product_url'),
        'discord_created_at': message.created_at.isoformat(),
        'discord_created_at_new_york': new_york_time(message.created_at),
        'note': 'Discord message creation; not the store publication time or phone notification receipt'
    }), flush=True)


async def traced_dispatch(awaitable, event, *, timeout):
    state = {'phase':'START', 'phase_started':time.monotonic(), 'primary_message_id':None}
    token = _state.set(state)
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError:
        print('LOTUS DISPATCH TIMEOUT DETAIL | ' + json.dumps({
            'store':event.get('store_name'), 'event':event.get('event_type'),
            'product_url':event.get('product_url'), 'phase':state['phase'],
            'phase_seconds':round(time.monotonic()-state['phase_started'],3),
            'primary_message_id':state['primary_message_id'],
            'delivery_state':'PRIMARY_CONFIRMED' if state['primary_message_id'] else 'NOT_CONFIRMED',
            'automatic_replay':False}), flush=True)
        raise
    finally:
        _state.reset(token)


async def optional_conversion(awaitable, *, timeout=2.0):
    """Native price is authoritative; optional conversion must not stall sending."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError:
        print('LOTUS OPTIONAL FX | Outcome=TIMEOUT | NativePriceRetained=True', flush=True)
        return None
    except Exception as error:
        print(f'LOTUS OPTIONAL FX | Outcome=ERROR | Type={type(error).__name__} | NativePriceRetained=True', flush=True)
        return None
