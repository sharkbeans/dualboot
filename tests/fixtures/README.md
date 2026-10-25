# Test fixtures

Fixtures are raw command output. GUIDs that identify a particular machine are
replaced with fake ones (`00000000-...`) before they are committed. A given
real GUID always becomes the same fake one, so references between blocks
(like bcdedit's `displayorder`) still line up.

| File | Source |
|---|---|
| `efibootmgr-v_lenovo-lmde.txt` | Real `efibootmgr -v` output (efibootmgr 18) from a Lenovo ThinkPad running LMDE 7 and Windows 11 on one shared EFI partition. Device-path GUIDs and the `dp:` hex dumps are shortened to `...`. |
| `bcdedit_firmware_en_us.txt` | Real `bcdedit /enum firmware` output from Windows 11 (build 22621, en-US) on the same ThinkPad. Byte for byte apart from the GUIDs. |
| `bcdedit_firmware_two_linux.txt` | **Hand-made**: `bcdedit_firmware_en_us.txt` plus an extra `\EFI\ubuntu\grubx64.efi` entry, to test choosing between two Linux installs. |

## Adding output from your machine

If detection goes wrong on your machine, the output of these commands is the
most useful thing to put in a bug report:

- Linux: `efibootmgr -v`
- Windows, from an Administrator Command Prompt: `bcdedit /enum firmware`

Replace the GUIDs with fake ones (for example
`{00000000-0000-0000-0000-000000000001}`) before you share the output.
