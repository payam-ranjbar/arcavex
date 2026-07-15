# ARC-EXT-021 — Extension entry could not be imported

An entry module could not be imported, the named class is missing, or the component could not be constructed with no arguments — often an import-time error or an unimplemented abstract method.

**Typical fix:** Check the module exists in the extension directory, defines the named class, imports only arcavex.sdk, and implements every method of its contract.
