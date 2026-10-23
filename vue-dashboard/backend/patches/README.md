# PVFS handle-release fix

The reviewed patches fix handle leaks in pypvfs 1.0.6. `IndexedDataFile.open()` now closes existing channel handles before replacing them, and closes partially opened handles if opening fails. `PvfsDataFile.create_channel()` closes the displaced channel instance when a legacy layout repeats a name such as `NC`. No labels, file format, or sample values change. Repeated names retain their documented legacy data collision.

After installing or reinstalling the backend's PVFS dependency, run from the backend directory:

```powershell
.venv/Scripts/python.exe tools/apply_pvfs_handle_fix.py --apply
.venv/Scripts/python.exe tools/apply_pvfs_handle_fix.py
```

Use the environment's `python` on other platforms. The script checks the installed version and source hash before writing. It leaves an already patched installation unchanged and refuses unknown versions or independently modified files. Restart running backend processes after applying it.

The patch is required for the verified local PVFS file-release guarantee. Reinstalling pypvfs removes this local dependency correction. The application release process must reapply and verify it until an upstream release includes equivalent behavior. This task does not publish a patched upstream package.

The native proof records exact sample readback, unchanged source bytes, and successful file renaming after both writer and reader close in `.audit/pvfs-wrapper/stage3-persistence/dependency-verification/report.json` at the repository root. The user approved this dependency edit for plan 35 step 3 on 2026-10-07.
