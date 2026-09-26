#!/usr/bin/env python3
"""Check arm64 ABI selection and run the libffi consumer on the current Mac."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

from prepare_libffi_source import patch_arm64_pointer_authentication


def run(*arguments, **kwargs):
    return subprocess.check_output(arguments, text=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architectures", nargs="+", choices=["arm64", "arm64e", "arm64e.x1"],
                        default=["arm64", "arm64e"])
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    sdk = run("xcrun", "--sdk", "iphoneos", "--show-sdk-path").strip()
    with tempfile.TemporaryDirectory(prefix="zdlibffi-ptrauth-") as temporary:
        directory = Path(temporary)
        # A source upgrade configures arm64 once; consumers later choose their ABI.
        regenerated = directory / "fficonfig.h"
        regenerated.write_text("/* Define if your compiler supports pointer authentication. */\n/* #undef HAVE_ARM64E_PTRAUTH */\n")
        patch_arm64_pointer_authentication(regenerated)
        for arch in arguments.architectures:
            cc = ["xcrun", "--sdk", "iphoneos", "clang", "-target", f"{arch}-apple-ios18.4", "-isysroot", sdk]
            for config in [root / "Source/include/fficonfig.h", regenerated]:
                for language in ["c", "assembler-with-cpp"]:
                    macros = run(*cc, "-x", language, "-E", "-dM", "-include", str(config), "-", input="")
                    enabled = "#define HAVE_ARM64E_PTRAUTH 1" in macros
                    if enabled != (arch != "arm64"):
                        raise RuntimeError(f"Incorrect {arch} {language} configuration in {config}")
            output = directory / f"{arch}.o"
            run(*cc, "-I", str(root / "Source/include"), "-c", str(root / "Source/src/aarch64/sysv_arm64.S"), "-o", str(output))
            assembly = run("xcrun", "otool", "-tvV", str(output))
            entry = assembly.split("_ffi_call_SYSV:\n", 1)[1].split("\n_", 1)[0]
            expected = r"\bblraaz\s+x9\b" if arch != "arm64" else r"\bblr\s+x9\b"
            if re.search(expected, entry) is None:
                raise RuntimeError(f"Wrong ffi_call_SYSV branch instruction for {arch}")
            closure = assembly.split("_ffi_closure_trampoline_table_page:\n", 1)[1]
            expected = r"\bbraaz\s+x16\b" if arch != "arm64" else r"\bbr\s+x16\b"
            if re.search(expected, closure) is None:
                raise RuntimeError(f"Wrong closure trampoline branch instruction for {arch}")
            # Enabling the macro also activates C paths in closure setup.
            for source in ["src/aarch64/ffi_arm64.c", "src/common/closures.c"]:
                run(*cc, "-I", str(root / "Source/include"), "-DUSE_DL_PREFIX=1", "-DHAVE_MORECORE=0",
                    "-fsyntax-only", str(root / "Source" / source))
            print(f"{arch}: C/assembly configuration and ffi_call_SYSV authentication agree")
        environment = dict(os.environ, SDKROOT=run("xcrun", "--sdk", "macosx", "--show-sdk-path").strip())
        scratch = root / ".build/pointer-authentication"
        build = ["xcrun", "swift", "build", "--package-path", str(root), "--scratch-path", str(scratch)]
        subprocess.check_call(build, env=environment)
        binary_directory = Path(run(*build, "--show-bin-path", env=environment).strip())
        consumer = directory / "consumer"
        run("xcrun", "--sdk", "macosx", "clang", "-I", str(root / "Source/include"),
            str(root / "Tests/PointerAuthentication.c"), str(binary_directory / "libZDLibffi.a"),
            "-o", str(consumer), env=environment)
        print(run(str(consumer)).strip())


if __name__ == "__main__":
    main()
