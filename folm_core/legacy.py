"""legacy - run old FOMM C# script installers (fomod/script.cs) natively and safely.

The script is compiled with Mono's mcs together with FOLM's FOMM-compatible shim
(fomm_shim/FommShim.cs), then run under bubblewrap:
  - read-only: the extracted archive, the game folder (for GetExistingDataFile), system libs
  - writable:  one staging folder (the new mod) and a private /tmp
  - no network, no access to the player's home folder
  - the X11 display is shared so the mod's own Windows Forms installer window can appear
The script's plugin and INI changes come back as a plan; nothing is applied silently.
"""

import json
import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(HERE, "fomm_shim", "FommShim.cs")


class LegacyError(RuntimeError):
    pass


def find_script(module_root):
    for d in os.listdir(module_root):
        if d.lower() == "fomod" and os.path.isdir(os.path.join(module_root, d)):
            for f in os.listdir(os.path.join(module_root, d)):
                if f.lower() == "script.cs":
                    return os.path.join(module_root, d, f)
    raise LegacyError("no fomod/script.cs found")


def compile_script(script, out_dir):
    """Compile script.cs + FOLM's shim. Returns the .exe path; raises with compiler errors."""
    if not shutil.which("mcs") or not shutil.which("mono"):
        raise LegacyError("Mono is needed for old FOMM installers (packages: mono-complete)")
    exe = os.path.join(out_dir, "installer.exe")
    r = subprocess.run(["mcs", "-nologo", "-target:exe", f"-out:{exe}", "-r:System.Windows.Forms",
                        "-r:System.Drawing", "-r:System.Core", "-r:System.Xml",
                        "-main:fomm.Scripting.FolmHost", SHIM, script],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        errors = [l for l in r.stdout.splitlines() + r.stderr.splitlines() if ": error " in l]
        missing = sorted({l.split("`")[1] for l in errors if "does not exist" in l and "`" in l})
        msg = "script didn't compile with FOLM's FOMM shim"
        if missing:
            msg += f"; FOMM functions FOLM doesn't provide yet: {', '.join(missing)}"
        raise LegacyError(msg + "\n" + "\n".join(errors[:10]))
    return exe


def sandbox_cmd(exe, module_root, game_dir, staging, plan, active_file, ini_dir):
    """bubblewrap command line that runs the installer locked down."""
    if not shutil.which("bwrap"):
        raise LegacyError("bubblewrap is needed to run old installers safely (package: bubblewrap)")
    cmd = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
           "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
           "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/home"]
    for d in ("/bin", "/sbin", "/lib", "/lib64", "/lib32"):
        if os.path.islink(d):
            cmd += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            cmd += ["--ro-bind", d, d]
    if os.path.isdir("/tmp/.X11-unix"):
        cmd += ["--ro-bind", "/tmp/.X11-unix", "/tmp/.X11-unix"]
    xauth = os.environ.get("XAUTHORITY")
    if xauth and os.path.exists(xauth):
        cmd += ["--ro-bind", xauth, "/tmp/.Xauthority", "--setenv", "XAUTHORITY", "/tmp/.Xauthority"]
    cmd += ["--ro-bind", module_root, "/folm/fomod",
            "--ro-bind", game_dir, "/folm/game",
            "--bind", staging, "/folm/stage",
            "--bind", os.path.dirname(plan), "/folm/out",
            "--ro-bind", exe, "/folm/installer.exe",
            "--ro-bind", active_file, "/folm/active.txt"]
    if ini_dir and os.path.isdir(ini_dir):
        cmd += ["--ro-bind", ini_dir, "/folm/ini"]
    env = {"FOLM_FOMOD_ROOT": "/folm/fomod", "FOLM_GAME_VIEW": "/folm/game/Data", "FOLM_STAGING": "/folm/stage",
           "FOLM_PLAN": "/folm/out/" + os.path.basename(plan), "FOLM_ACTIVE_PLUGINS": "/folm/active.txt",
           "FOLM_INI_DIR": "/folm/ini", "HOME": "/tmp", "DISPLAY": os.environ.get("DISPLAY", ":0")}
    for k, v in env.items():
        cmd += ["--setenv", k, v]
    return cmd + ["mono", "/folm/installer.exe"]


def run(module_root, game_dir, staging, active_plugins, ini_dir=None, log=lambda *a: None, timeout=3600):
    """Compile and run a legacy installer. Returns its plan dict; files land in `staging`."""
    script = find_script(module_root)
    with tempfile.TemporaryDirectory() as work:
        exe = compile_script(script, work)
        log("  compiled the mod's FOMM script with FOLM's shim")
        active = os.path.join(work, "active.txt")
        with open(active, "w") as fh:
            fh.write("\n".join(active_plugins))
        out = os.path.join(work, "out")
        os.makedirs(out)
        plan = os.path.join(out, "plan.json")
        cmd = sandbox_cmd(exe, module_root, game_dir, staging, plan, active, ini_dir)
        log("  running the mod's own installer (sandboxed: no network, no home folder)")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if not os.path.exists(plan):
            raise LegacyError(f"the installer stopped without finishing (exit {r.returncode}): "
                              f"{(r.stderr or r.stdout).strip()[-600:]}")
        with open(plan) as fh:
            result = json.load(fh)
    if result.get("error"):
        raise LegacyError("the installer's script failed: " + result["error"].splitlines()[0][:300])
    return result
