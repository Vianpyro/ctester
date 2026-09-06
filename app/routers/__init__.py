"""The routers: one HTTP boundary per domain.

A router does ONLY translation: read a request, call `services/` or
`state.py`, return a response. No business rule has the right to live here --
that is what keeps `test_ctester.py` able to exercise the rules without
standing up a server.
"""
