"""Web push for the standalone server (VAPID, no FCM project needed).

VAPID keys are auto-generated on first boot and stored in the KV store, so
the user never has to generate them manually. Subscriptions are stored as a
list under one key; sending is best-effort (a dead endpoint is dropped).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

VAPID_KV_KEY = "global#vapid_keys"
SUBSCRIPTIONS_KV_KEY = "global#push_subscriptions"
VAPID_CLAIMS_SUB = "mailto:agentcloud@example.com"


def _generate_vapid_keypair() -> dict[str, str]:
    """Generate a VAPID keypair; returns PEM private + base64url public.

    The public key is the raw 65-byte uncompressed EC point, base64url
    encoded — exactly the format ``pushManager.subscribe`` expects.
    """
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    private_pem = vapid.private_pem().decode("utf-8")
    public_raw = vapid.public_key.public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    public_b64 = base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("=")
    return {"private_pem": private_pem, "public_key": public_b64}


async def get_vapid_public_key(store) -> str:
    """Return the public key, generating and persisting the pair once."""
    keys = await store.get("owner", VAPID_KV_KEY)
    if not keys:
        keys = _generate_vapid_keypair()
        await store.set("owner", VAPID_KV_KEY, keys)
        logger.info("Generated new VAPID keypair")
    return keys["public_key"]


async def save_subscription(store, subscription: dict) -> None:
    """Add a push subscription (dedup by endpoint)."""
    subs = await store.get("owner", SUBSCRIPTIONS_KV_KEY) or []
    subs = [s for s in subs if s.get("endpoint") != subscription.get("endpoint")]
    subs.append(subscription)
    await store.set("owner", SUBSCRIPTIONS_KV_KEY, subs)


async def remove_subscription(store, endpoint: str) -> None:
    subs = await store.get("owner", SUBSCRIPTIONS_KV_KEY) or []
    subs = [s for s in subs if s.get("endpoint") != endpoint]
    await store.set("owner", SUBSCRIPTIONS_KV_KEY, subs)


async def send_push(store, title: str, body: str) -> int:
    """Send a notification to every subscription; returns the success count.

    Best-effort: failures are logged, and permanently-dead endpoints
    (410 Gone) are pruned from the list.
    """
    keys = await store.get("owner", VAPID_KV_KEY)
    subs = await store.get("owner", SUBSCRIPTIONS_KV_KEY) or []
    if not keys or not subs:
        return 0

    from pywebpush import WebPushException, webpush

    sent = 0
    dead: list[str] = []
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps({"title": title, "body": body}),
                vapid_private_key=keys["private_pem"],
                vapid_claims={"sub": VAPID_CLAIMS_SUB},
                ttl=3600,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                dead.append(sub.get("endpoint", ""))
            logger.warning("Push to %s failed: %s", sub.get("endpoint", "?"), e)
        except Exception as e:  # noqa: BLE001 - one bad sub must not stop the rest
            logger.warning("Push error: %s", e)

    if dead:
        subs = [s for s in subs if s.get("endpoint") not in dead]
        await store.set("owner", SUBSCRIPTIONS_KV_KEY, subs)
    return sent
