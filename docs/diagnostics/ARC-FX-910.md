# ARC-FX-910 — Unknown effect

A node references an effect name that is not registered. Besides a typo, this is what an effect provided by an extension looks like before that extension is added and enabled; some shipped examples bundle one.

**Typical fix:** Use a registered effect (the message lists them), or add and enable the extension that provides it: 'arcavex ext add <dir>', then 'arcavex ext enable <name>'; 'arcavex ext list' shows added extensions and their state.
