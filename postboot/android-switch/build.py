#!/usr/bin/env python3
"""Offline Android build and host-only source tests. No downloads or device commands."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
PACKAGE = pathlib.Path("cn/armada/dualswitch")
DEFAULT_CONFIG = ROOT / "config/deployment.example.json"
STRING_FIELDS = {
    "MODEL": "model", "DEVICE": "device", "LINUX_PARTLABEL": "linuxPartlabel",
    "LINUX_PATH": "linuxPath", "BOOT_PATH": "bootPath", "IMAGE_SHA256": "imageSha256",
    "SOURCE_RUN": "sourceRun", "SOURCE_COMMIT": "sourceCommit", "AIDL_HASH": "aidlHash",
}
INT_FIELDS = {"ANDROID_SLOT": "androidSlot", "LINUX_SLOT": "linuxSlot", "AIDL_VERSION": "aidlVersion"}
LONG_FIELDS = {"LINUX_BYTES": "linuxBytes", "IMAGE_BYTES": "imageBytes"}
PURE_SOURCES = (
    "TargetConfig.java", "Policy.java", "BlockIdentity.java", "InputGuard.java",
    "ProcessSession.java", "ImageDigest.java", "SwitchDeadline.java", "SwitchCoordinator.java",
)
HELPER_SOURCES = (
    "TargetConfig.java", "Policy.java", "BlockIdentity.java", "InputGuard.java",
    "ImageDigest.java", "SwitchDeadline.java", "SwitchCoordinator.java",
    "BootControlClient.java", "BootControlHelper.java",
)
DIAGNOSTIC_SHARED = (
    "TargetConfig.java", "Policy.java", "BlockIdentity.java", "ImageDigest.java",
    "SwitchDeadline.java", "BootControlClient.java",
)
DIAGNOSTIC_SOURCES = ("BootControlDiagnostic.java", "DiagnosticCoordinator.java", "DiagnosticState.java")
TRANSACTIONS = {
    "GET_ACTIVE": ("getActiveBootSlot", 0), "GET_CURRENT": ("getCurrentSlot", 1),
    "GET_SLOTS": ("getNumberSlots", 2), "GET_MERGE": ("getSnapshotMergeStatus", 3),
    "GET_SUFFIX": ("getSuffix", 4), "IS_BOOTABLE": ("isSlotBootable", 5),
    "SET_ACTIVE": ("setActiveBootSlot", 8), "GET_VERSION": ("getInterfaceVersion", 16777214),
    "GET_HASH": ("getInterfaceHash", 16777213),
}


def run(*args, java_home=None):
    command = [str(arg) for arg in args]
    print("+", " ".join(command), flush=True)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    selected_home = java_home or env.get("ARMADA_JAVA_HOME") or env.get("JAVA_HOME")
    if selected_home:
        home = str(pathlib.Path(selected_home).expanduser().resolve())
        env["JAVA_HOME"] = home
        env["PATH"] = str(pathlib.Path(home) / "bin") + os.pathsep + env.get("PATH", "")
    subprocess.run(command, check=True, cwd=ROOT, env=env)


def java_tool(name, java_home):
    home = java_home or os.environ.get("ARMADA_JAVA_HOME") or os.environ.get("JAVA_HOME")
    if home:
        result = pathlib.Path(home).expanduser().resolve() / "bin" / name
        if not result.is_file():
            raise ValueError("JDK executable not found: " + str(result))
        return result
    result = shutil.which(name)
    if not result:
        raise ValueError("Install a JDK and set JAVA_HOME or --java-home")
    return pathlib.Path(result)


def sdk_root(value):
    value = value or os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not value:
        raise ValueError("Set ANDROID_SDK_ROOT or --sdk-root to an installed Android SDK")
    return pathlib.Path(value).expanduser().resolve()


def validate_paths(c):
    if c["bootPath"] != "/dev/block/by-name/boot_b":
        raise ValueError("bootPath must be /dev/block/by-name/boot_b")
    if c["linuxPath"] != "/dev/block/by-name/linux":
        raise ValueError("linuxPath must be /dev/block/by-name/linux")


def validate_config(c):
    required = set(STRING_FIELDS.values()) | set(INT_FIELDS.values()) | set(LONG_FIELDS.values()) | {"deploymentReady"}
    if not isinstance(c, dict) or set(c) != required:
        raise ValueError("Configuration must contain exactly the fields in deployment.example.json")
    for field in STRING_FIELDS.values():
        if type(c[field]) is not str:
            raise ValueError(field + " must be a string")
    for field in list(INT_FIELDS.values()) + list(LONG_FIELDS.values()):
        if type(c[field]) is not int:
            raise ValueError(field + " must be an integer")
    if type(c["deploymentReady"]) is not bool:
        raise ValueError("deploymentReady must be a boolean")
    if c["androidSlot"] != 0 or c["linuxSlot"] != 1:
        raise ValueError("Only Android a to Linux b is supported; update policy and tests for another mapping")
    if c["linuxBytes"] != 64 * 1024 ** 3 or c["linuxPartlabel"] != "linux":
        raise ValueError("Expected independent GPT linux partition of exactly 64 GiB")
    validate_paths(c)
    if not 0 <= c["imageBytes"] <= 1024 ** 3:
        raise ValueError("Invalid image length")
    frozen_hash = (ROOT / "aidl/v1/.hash").read_text().strip()
    if c["aidlVersion"] != 1 or c["aidlHash"] != frozen_hash:
        raise ValueError("AIDL configuration differs from frozen v1")
    if c["deploymentReady"]:
        if c["imageBytes"] <= 0 or not re.fullmatch("[0-9a-f]{64}", c["imageSha256"]):
            raise ValueError("Deployment needs exact image length and SHA256")
        if any(not c[key] or c[key].startswith("REPLACE_") for key in ("model", "device")):
            raise ValueError("Deployment needs verified model and device values")
    return c


def render_config(c):
    validate_config(c)
    lines = ["package cn.armada.dualswitch;",
             "/** Generated from explicit build configuration by build.py. */",
             "public final class TargetConfig {"]
    for const, field in STRING_FIELDS.items():
        lines.append("    public static final String " + const + " = " + json.dumps(c[field], ensure_ascii=True) + ";")
    for const, field in INT_FIELDS.items():
        lines.append("    public static final int " + const + " = " + str(c[field]) + ";")
    for const, field in LONG_FIELDS.items():
        lines.append("    public static final long " + const + " = " + str(c[field]) + "L;")
    lines.append("    public static final boolean DEPLOYMENT_READY = " + str(c["deploymentReady"]).lower() + ";")
    lines.extend(["    private TargetConfig() {}", "}"])
    return "\n".join(lines) + "\n"


def generate_config(config_path, destination):
    c = validate_config(json.loads(pathlib.Path(config_path).read_text()))
    destination = pathlib.Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_config(c))
    return c


def check_diagnostic_source():
    paths = [ROOT / "src" / PACKAGE / name for name in DIAGNOSTIC_SHARED]
    paths += [ROOT / "diagnostic/src" / PACKAGE / name for name in DIAGNOSTIC_SOURCES]
    for path in paths:
        text = path.read_text()
        if any(marker in text for marker in ("ProcessBuilder", "Runtime.getRuntime", "/system/bin/reboot")):
            raise ValueError("Diagnostic process/reboot API is forbidden: " + path.name)
    print("Diagnostic no-process/no-reboot source check: PASS")


def run_source_tests(java_home=None):
    run(sys.executable, "-B", ROOT / "tests/test_build_config.py", java_home=java_home)
    check_diagnostic_source()
    javac, java = java_tool("javac", java_home), java_tool("java", java_home)
    source = ROOT / "src" / PACKAGE
    with tempfile.TemporaryDirectory(prefix=".source-test-", dir=ROOT) as temp:
        work = pathlib.Path(temp)
        classes = work / "unit"
        classes.mkdir()
        diagnostic = ROOT / "diagnostic/src" / PACKAGE / "DiagnosticCoordinator.java"
        tests = sorted((ROOT / "tests/cn/armada/dualswitch").glob("*.java"))
        tests += sorted((ROOT / "diagnostic/tests").rglob("*.java"))
        run(javac, "-encoding", "UTF-8", "-d", classes,
            *[source / name for name in PURE_SOURCES], diagnostic, *tests, java_home=java_home)
        for name in ("PolicyTest", "SwitchCoordinatorTest", "ImageDigestTest", "SwitchDeadlineTest",
                     "BlockIdentityTest", "InputGuardTest", "ProcessSessionTest", "DiagnosticCoordinatorTest"):
            run(java, "-cp", classes, "cn.armada.dualswitch." + name, java_home=java_home)
        binder = work / "binder"
        binder.mkdir()
        run(javac, "-encoding", "UTF-8", "-d", binder, source / "TargetConfig.java", source / "BootControlClient.java",
            *sorted((ROOT / "tests/binder").rglob("*.java")), java_home=java_home)
        run(java, "-cp", binder, "cn.armada.dualswitch.BootControlClientTest", java_home=java_home)
    print("Host-only source tests: PASS; temporary class output removed")


def check_aidl(c, tools, build, java_home):
    generated = build / "aidl-generated"
    generated.mkdir(parents=True, exist_ok=True)
    run(tools / "aidl", "--lang=java", "--structured", "--stability=vintf", "--version=1",
        "--hash=" + c["aidlHash"], "--min_sdk_version=29", "-I", ROOT / "aidl/v1",
        "--out=" + str(generated), ROOT / "aidl/v1/android/hardware/boot/IBootControl.aidl", java_home=java_home)
    java = (generated / "android/hardware/boot/IBootControl.java").read_text()
    client = (ROOT / "src" / PACKAGE / "BootControlClient.java").read_text()
    for const, (method, offset) in TRANSACTIONS.items():
        expected = f"TRANSACTION_{method} = (android.os.IBinder.FIRST_CALL_TRANSACTION + {offset});"
        if expected not in java or f"{const} = IBinder.FIRST_CALL_TRANSACTION + {offset};" not in client:
            raise ValueError("AIDL transaction mismatch: " + method)
    print("AIDL frozen v1 transaction map, version and hash: PASS")


def compile_java(sources, classes, android, tools, java_home):
    classes.mkdir(parents=True, exist_ok=True)
    run(java_tool("javac", java_home), "-encoding", "UTF-8", "-source", "8", "-target", "8",
        "-bootclasspath", str(android) + os.pathsep + str(tools / "core-lambda-stubs.jar"),
        "-d", classes, *sources, java_home=java_home)


def dex(classes, destination, android, tools, java_home):
    destination.mkdir(parents=True, exist_ok=True)
    run(tools / "d8", "--min-api", "29", "--lib", android, "--output", destination,
        *sorted(classes.rglob("*.class")), java_home=java_home)


def helper_jar(sources, stem, build, out, android, tools, java_home):
    classes = build / (stem + "-classes")
    compile_java(sources, classes, android, tools, java_home)
    destination = build / (stem + "-dex")
    dex(classes, destination, android, tools, java_home)
    final = out / (stem + ".jar")
    with zipfile.ZipFile(final, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(destination.glob("classes*.dex")):
            archive.write(path, path.name)
    return final


def make_apk(generated_config, build, out, android, tools, args):
    compiled = build / "resources.zip"
    run(tools / "aapt2", "compile", "--dir", ROOT / "res", "-o", compiled, java_home=args.java_home)
    resources = build / "resources.apk"
    generated = build / "r-generated"
    generated.mkdir()
    run(tools / "aapt2", "link", "-o", resources, "--manifest", ROOT / "AndroidManifest.xml", "-I", android,
        "--java", generated, "--min-sdk-version", "30", "--target-sdk-version", "35", compiled, java_home=args.java_home)
    sources = [p for p in sorted((ROOT / "src").rglob("*.java")) if p.name != "TargetConfig.java"]
    sources += [generated_config] + sorted(generated.rglob("*.java"))
    classes = build / "app-classes"
    compile_java(sources, classes, android, tools, args.java_home)
    destination = build / "app-dex"
    dex(classes, destination, android, tools, args.java_home)
    unsigned = build / "unsigned.apk"
    shutil.copyfile(resources, unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(destination.glob("classes*.dex")):
            archive.write(path, path.name)
    aligned = out / "armada-dual-boot-unsigned.apk"
    run(tools / "zipalign", "-f", "-p", "4", unsigned, aligned, java_home=args.java_home)
    if args.keystore:
        final = out / "armada-dual-boot.apk"
        run(tools / "apksigner", "sign", "--ks", pathlib.Path(args.keystore).expanduser().resolve(),
            "--ks-key-alias", args.key_alias, "--ks-pass", "env:" + args.ks_pass_env,
            "--v1-signing-enabled", "false", "--v2-signing-enabled", "true", "--v3-signing-enabled", "true",
            "--v4-signing-enabled", "false", "--out", final, aligned, java_home=args.java_home)
        run(tools / "apksigner", "verify", "--verbose", "--print-certs", final, java_home=args.java_home)
    else:
        final = aligned
    run(tools / "zipalign", "-c", "-p", "4", final, java_home=args.java_home)
    run(tools / "aapt2", "dump", "permissions", final, java_home=args.java_home)
    return final


def validate_signing(args):
    if bool(args.keystore) != bool(args.key_alias):
        raise ValueError("Use --keystore and --key-alias together")
    if not args.keystore:
        return
    keystore = pathlib.Path(args.keystore).expanduser().resolve()
    if keystore.is_relative_to(ROOT) or not keystore.is_file():
        raise ValueError("Signing keystore must be an existing file outside this source tree")
    if not re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", args.ks_pass_env) or not os.environ.get(args.ks_pass_env):
        raise ValueError("Set the password environment variable named by --ks-pass-env")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--test", action="store_true", help="Run source tests using only Python and a JDK; remove temporary classes")
    mode.add_argument("--helper-only", action="store_true", help="Build the app's app_process helper JAR only")
    mode.add_argument("--diagnostic-only", action="store_true", help="Build the optional no-reboot diagnostic JAR only")
    parser.add_argument("--config", type=pathlib.Path, default=DEFAULT_CONFIG)
    parser.add_argument("--sdk-root", help="Installed SDK; otherwise ANDROID_SDK_ROOT or ANDROID_HOME")
    parser.add_argument("--java-home", help="JDK home; otherwise ARMADA_JAVA_HOME, JAVA_HOME, or PATH")
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "out")
    parser.add_argument("--keystore", help="Optional signing key outside this source tree; read-only use")
    parser.add_argument("--key-alias", help="Alias in the externally managed signing keystore")
    parser.add_argument("--ks-pass-env", default="ANDROID_SWITCH_KEYSTORE_PASSWORD", help="Name of password environment variable; never pass the password as an argument")
    args = parser.parse_args()
    if args.test:
        run_source_tests(args.java_home)
        return
    validate_signing(args)
    sdk = sdk_root(args.sdk_root)
    tools, android = sdk / "build-tools/35.0.0", sdk / "platforms/android-35/android.jar"
    needed = [tools / name for name in ("aidl", "d8", "core-lambda-stubs.jar")] + [android]
    if not args.helper_only and not args.diagnostic_only:
        needed += [tools / name for name in ("aapt2", "zipalign")]
        if args.keystore:
            needed.append(tools / "apksigner")
    if any(not path.is_file() for path in needed):
        raise ValueError("Install SDK platform android-35 and build-tools 35.0.0 before building")
    run_source_tests(args.java_home)
    out = args.output_dir.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    outputs = []
    with tempfile.TemporaryDirectory(prefix=".source-build-", dir=ROOT) as temp:
        build = pathlib.Path(temp)
        generated_config = build / "config" / PACKAGE / "TargetConfig.java"
        c = generate_config(args.config, generated_config)
        check_aidl(c, tools, build, args.java_home)
        source = ROOT / "src" / PACKAGE
        def configured(names):
            return [generated_config if name == "TargetConfig.java" else source / name for name in names]
        if args.diagnostic_only:
            diagnostic = [ROOT / "diagnostic/src" / PACKAGE / name for name in DIAGNOSTIC_SOURCES]
            outputs.append(helper_jar(configured(DIAGNOSTIC_SHARED) + diagnostic, "armada-slot-diagnostic", build, out, android, tools, args.java_home))
        else:
            outputs.append(helper_jar(configured(HELPER_SOURCES), "armada-boot-helper", build, out, android, tools, args.java_home))
            if not args.helper_only:
                outputs.append(make_apk(generated_config, build, out, android, tools, args))
    checksums = []
    for path in outputs:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums.append(digest + "  " + path.name)
        print(path.name, path.stat().st_size, digest)
    (out / "SHA256SUMS").write_text("\n".join(checksums) + "\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print("build:", error, file=sys.stderr)
        sys.exit(1)
