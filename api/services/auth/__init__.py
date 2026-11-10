"""Accounts: passwords, single-use tokens, sessions, throttling, mail and the sign-in flows.

Each module does one thing and takes its collaborators (a store, a hasher, a clock-free
setting) as arguments; ``flows.AuthService`` composes them for the routers.
"""
