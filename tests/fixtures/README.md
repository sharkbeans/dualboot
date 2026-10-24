# Test fixtures

Fixtures are raw command output. GUIDs that identify a particular machine are
replaced or trimmed with `...` before they are committed.

| File | Source |
|---|---|
| `efibootmgr-v_lenovo-lmde.txt` | Real `efibootmgr -v` output (efibootmgr 18) from a Lenovo ThinkPad running LMDE 7 and Windows 11 on one shared EFI partition. |
| `bcdedit-enum-firmware_PLACEHOLDER.txt` | **PLACEHOLDER, not real output.** Hand-written from the documented `bcdedit /enum firmware` format, with fake GUIDs. It will be replaced by real output from the same machine. |

## Adding output from your machine

If detection fails on your machine, the output of these commands is the most
useful thing to put in a bug report:

- Linux: `efibootmgr -v`
- Windows, from an Administrator Command Prompt: `bcdedit /enum firmware`

Replace the GUIDs with fake ones (for example
`{00000000-0000-0000-0000-000000000001}`) before you share the output.
