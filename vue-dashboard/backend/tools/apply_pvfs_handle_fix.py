"""Apply the reviewed pypvfs 1.0.6 handle-release patch to this Python environment."""

import argparse
import hashlib
import importlib.metadata
from pathlib import Path

ORIGINAL = "0ae3f65ea28d92b1a506c790ee846e1340a332f8036748b555fa92992fe8f0b8"
PATCHED = "9b4e3235554a01427e0540ae0859ffe3b42ca8105f1859d55a0d91e938b6aee6"
CATALOG_ORIGINAL = "d3e61b5b7e4b85715e60394819503c74e2e0d5d7fa445687f27ff53a4894674c"
CATALOG_PATCHED = "5149378ac7cb4fa05a7186f5c3f002f0e895ff1ac07b881f4d8879f95a1563b9"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the patch if needed")
    args = parser.parse_args()
    distribution = importlib.metadata.distribution("pypvfs")
    if distribution.version != "1.0.6":
        raise SystemExit("This patch requires review for pypvfs versions other than 1.0.6")
    path = Path(distribution.locate_file("pvfs_tools/Core/indexed_data_file.py"))
    source = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode()).hexdigest()
    if digest not in {ORIGINAL, PATCHED}:
        raise SystemExit("Refusing to patch an unrecognized or independently modified pypvfs file")
    catalog_path = Path(distribution.locate_file("pvfs_tools/Core/pvfs_data_file.py"))
    catalog = catalog_path.read_text(encoding="utf-8")
    catalog_digest = hashlib.sha256(catalog.encode()).hexdigest()
    if catalog_digest not in {CATALOG_ORIGINAL, CATALOG_PATCHED}:
        raise SystemExit("Refusing to patch an unrecognized pypvfs channel factory")
    if digest == PATCHED and catalog_digest == CATALOG_PATCHED:
        print(f"Verified patched pypvfs: {path.parent}")
        return
    if not args.apply:
        raise SystemExit("pypvfs needs the handle-release fixes; rerun with --apply")
    start = source.index("    def open(")
    end = source.index("    def close(", start)
    method = source[start:end]
    method = method.replace(
        "        # Construct filenames\n",
        "        # Reopening must release the handles created by the previous create or open.\n"
        "        self.close()\n        opened = False\n\n        # Construct filenames\n",
        1,
    ).replace(
        "            self._read_all_indices()\n            return True",
        "            self._read_all_indices()\n            opened = True\n            return True",
        1,
    ).replace(
        "            pvfs_file.unlock()\n",
        "            pvfs_file.unlock()\n            if not opened:\n"
        "                self.close()\n",
        1,
    )
    patched = source[:start] + method + source[end:]
    if digest == PATCHED:
        patched = source
    if catalog_digest == CATALOG_ORIGINAL:
        catalog = catalog.replace(
            "            indexed_file.set_data_rate(data_rate)\n"
            "            self._indexed_data_files[channel_name] = indexed_file",
            "            indexed_file.set_data_rate(data_rate)\n"
            "            previous = self._indexed_data_files.get(channel_name)\n"
            "            if previous is not None:\n                previous.close()\n"
            "            self._indexed_data_files[channel_name] = indexed_file",
            1,
        )
    if (hashlib.sha256(patched.encode()).hexdigest() != PATCHED or
            hashlib.sha256(catalog.encode()).hexdigest() != CATALOG_PATCHED):
        raise SystemExit("Patch result differs from the reviewed source; installation unchanged")
    compile(patched, str(path), "exec")
    compile(catalog, str(catalog_path), "exec")
    if digest != PATCHED:
        path.write_text(patched, encoding="utf-8", newline="")
    if catalog_digest != CATALOG_PATCHED:
        catalog_path.write_text(catalog, encoding="utf-8", newline="")
    print(f"Applied pypvfs handle-release fixes: {path.parent}")


if __name__ == "__main__":
    main()
