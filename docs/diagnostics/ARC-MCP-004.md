# ARC-MCP-004 — Could not register the MCP server

Either the host's CLI ('claude mcp add', 'codex mcp add') exited with an error, or the host's config file could not be updated: it is not valid JSON/TOML, its top level is not the expected shape, the existing 'arcavex' entry is written in a layout this command cannot rewrite safely, or the write itself failed. The message carries what the CLI or the OS said. A file is only ever replaced atomically with its previous content kept beside it as '.bak', so a failure leaves it as it was.

**Typical fix:** Fix what the message reports — repair the file, or move it aside — and run again; or paste the snippet from 'arcavex mcp install --print' into the file yourself.
