"""CLI/Commands.

Command modules register themselves with the ``main`` group on import.
The ``main`` group imports them lazily through ``registry.LAZY_COMMANDS``,
so this package must not import them here.
"""
