# ARC-SKL-001 — Unknown skill install target

'arcavex skill install --target' was given a name that is not a known assistant. The known targets are fixed because each names a directory layout the engine writes to; anything else is reachable with '--path'.

**Typical fix:** Use one of the listed targets, or pass '--path DIR' to install anywhere else.
