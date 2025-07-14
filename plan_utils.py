"""
Helper functions for looking up users' plan and plan-limited features/quotas.
Reads clients.json (simple flat file for demo/prototype—replace with DB lookup for production).
"""

import json
from plan_rules import PLAN_RULES

# Simple in-memory cache for clients.json to avoid repeated disk reads
_CLIENTS_CACHE = None

def load_clients(force_refresh=False):
    """
    Loads the clients.json file, optionally forcing refresh.
    Returns a list of client dicts (with at least 'email' and 'plan' fields).
    """
    global _CLIENTS_CACHE
    if force_refresh or _CLIENTS_CACHE is None:
        try:
            with open("clients.json") as f:
                _CLIENTS_CACHE = json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to load clients.json: {e}")
            _CLIENTS_CACHE = []
    return _CLIENTS_CACHE

def get_plan(email, force_refresh=False):
    """
    Returns the user's plan as an uppercase string.
    Defaults to "FREE" if not found or error.
    """
    clients = load_clients(force_refresh=force_refresh)
    for client in clients:
        if isinstance(client.get("email"), str) and client["email"].lower() == email.lower():
            plan = client.get("plan", "FREE").upper()
            if plan not in PLAN_RULES:
                return "FREE"
            return plan
    return "FREE"

def get_plan_limits(email, force_refresh=False):
    """
    Returns the plan limits/rules dict for the user's plan.
    """
    plan = get_plan(email, force_refresh=force_refresh)
    return PLAN_RULES.get(plan, PLAN_RULES["FREE"])

def get_plan_feature(email, feature, force_refresh=False):
    """
    Returns the value of a specific feature for the user's plan.
    """
    limits = get_plan_limits(email, force_refresh=force_refresh)
    return limits.get(feature)

def get_all_features_for_email(email, force_refresh=False):
    """
    Returns all features/limits for a user's plan.
    """
    return get_plan_limits(email, force_refresh=force_refresh)

def refresh_clients():
    """
    Manually refreshes the in-memory cache from clients.json.
    """
    return load_clients(force_refresh=True)