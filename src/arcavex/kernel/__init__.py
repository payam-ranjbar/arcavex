"""Arcavex kernel: the small, stable, dependency-free core of the engine.

The kernel owns the intermediate representation, contracts (SPI), typed registries,
the diagnostics model, and the service API facade. It imports nothing from clients,
services, builtins, or the bootstrap composition root.
"""
