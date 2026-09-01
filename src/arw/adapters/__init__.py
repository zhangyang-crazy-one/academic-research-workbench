"""ARW v2 adapters: existing implementations behind the ports.

Adapters are thin translation shells — any logic bigger than argument
mapping stays in the existing module. The kernel never imports from here;
the composition root (cli) wires providers.
"""
