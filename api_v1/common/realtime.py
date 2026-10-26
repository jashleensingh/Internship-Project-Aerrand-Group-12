"""Hook for pushing a change to the Aerrander's phone / the dashboard in real time.

Aerrand's real stack mirrors the delivery document into Firebase Realtime Database. Here it just logs, so the
rest of the code can call it from the right places. Replace the body with the real push.
"""
import logging

log = logging.getLogger("api_v1.realtime")


def push_realtime(topic, payload):
    log.info("realtime push topic=%s payload=%s", topic, payload)
