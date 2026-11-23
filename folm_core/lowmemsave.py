"""lowmemsave - save the game by itself when its memory runs low (New Vegas).

When the memory gauge first warns that the game's 4 GB are nearly full, FOLM asks the game to save, so
a crash soon after costs a few minutes at most. A save made while memory is low can itself be cut off by
a crash; it goes to its own file, so your other saves are never at risk.

How the game is asked, with nothing installed but what the player already has (xNVSE and JIP LN):
- On deploy, FOLM writes a small script, Data/NVSE/plugins/scripts/gr_folm_lowmemsave.txt. JIP LN runs
  `gr_` scripts once at game start; this one registers a check that runs every 5 seconds of play (never
  in menus, so never during dialogue or the Pip-Boy) and saves as "FOLM_LowMemory" when the file
  Data/FOLM/save-now.txt exists. Undeploy removes the script again. The check asks for both
  "Data\\FOLM\\..." and "FOLM\\...": JIP LN's own file paths start at the game's folder, but this isn't
  confirmed for FileExists, and the wrong one simply never matches. The check runs every 300 frames
  (5 seconds at 60 FPS).
- FOLM writes that file when the gauge warns, removes it as soon as the save appears, then renames the
  save (and its script-extender co-saves) to a unique name, e.g. "FOLM_LowMemory_2026-11-21_21-04".
"""
import os
import re
import threading
import time

NAME = "FOLM_LowMemory"
REQUEST = "FOLM/save-now.txt"                      # under Data
SCRIPT_NAME = "gr_folm_lowmemsave.txt"
MIN_XNVSE = (6, 2, 1)                              # text scripts with lambdas
SCRIPT = f"""; FOLM: save the game when its memory runs low. Written by FOLM on deploy, removed on undeploy.
; Every 5 seconds of play (never in menus): if FOLM has written Data\\FOLM\\save-now.txt, save as
; "{NAME}". FOLM then removes that file and gives the save a unique name.
SetGameMainLoopCallback (begin function {{}}
    if player.GetDead == 0
        if FileExists "Data\\FOLM\\save-now.txt"
            con_Save "{NAME}"
        elseif FileExists "FOLM\\save-now.txt"
            con_Save "{NAME}"
        endif
    endif
end) 1 300 1
"""


def _ci(base, rel, create=False):
    """base/rel with each folder's existing letter case (NVSE/Plugins vs nvse/plugins); missing parts
    are created when asked. None if a part is missing and create is False."""
    cur = base
    for part in rel.split("/"):
        try:
            names = {n.lower(): n for n in os.listdir(cur)}
        except (FileNotFoundError, NotADirectoryError):
            names = {}
        nxt = os.path.join(cur, names.get(part.lower(), part))
        if part.lower() not in names and not create:
            return None
        cur = nxt
    if create:
        os.makedirs(cur, exist_ok=True)
    return cur


def xnvse_version(game_dir):
    from . import tools
    for f in os.listdir(game_dir) if os.path.isdir(game_dir) else []:
        if f.lower() == "nvse_1_4.dll":
            v = tools.pe_version(os.path.join(game_dir, f)) or ""
            nums = [int(x) for x in re.findall(r"\d+", v)]
            if nums and nums[0] == 0:                      # xNVSE states 6.4.9 as 0.6.4.9
                nums = nums[1:]
            return tuple(nums[:3]) if nums else None
    return None


def why_not(edition, game_dir, data_dir):
    """None if the game can save on request here, else why not (in plain words)."""
    if edition != "courier":
        return "only for New Vegas (Fallout 3's script extender can't run the check)"
    if not _ci(data_dir, "NVSE/Plugins/jip_nvse.dll"):
        return "needs JIP LN NVSE"
    v = xnvse_version(game_dir)
    if not v:
        return "needs xNVSE"
    if v < MIN_XNVSE:
        return f"needs xNVSE {'.'.join(map(str, MIN_XNVSE))} or newer (you have {'.'.join(map(str, v))})"
    return None


def install(data_dir):
    """Write the game-start script. Returns its path."""
    folder = _ci(data_dir, "NVSE/Plugins/scripts", create=True)
    path = os.path.join(folder, SCRIPT_NAME)
    with open(path, "w", newline="\r\n") as fh:
        fh.write(SCRIPT)
    return path


def clear_request(data_dir):
    p = _ci(data_dir, REQUEST)
    if p and os.path.exists(p):
        os.remove(p)
    d = _ci(data_dir, "FOLM")
    if d and os.path.isdir(d) and not os.listdir(d):
        os.rmdir(d)


def installed(data_dir):
    return bool(_ci(data_dir, "NVSE/Plugins/scripts/" + SCRIPT_NAME))


class Saver:
    """Ask the game for one save and give it a unique name. .result is the new save's name once done,
    .problem a note if it didn't happen. Runs in its own thread; stop() cancels a pending request."""

    def __init__(self, data_dir, save_dir, on_done=None, give_up=600, quiet=3.0):
        self.data_dir, self.save_dir, self.on_done, self.give_up = data_dir, save_dir, on_done, give_up
        self.quiet = quiet                                 # seconds without change = the game is done writing
        self.result = self.problem = None
        self._stop = threading.Event()

    def start(self):
        req = os.path.join(_ci(self.data_dir, "FOLM", create=True), "save-now.txt")
        with open(req, "w") as fh:
            fh.write("FOLM: the game's memory is nearly full. Save now.\n")
        threading.Thread(target=self._run, daemon=True).start()

    def _files(self):
        try:
            return [f for f in os.listdir(self.save_dir) if f.split(".")[0] == NAME]
        except OSError:
            return []

    def _run(self):
        before = {f: os.stat(os.path.join(self.save_dir, f)).st_mtime for f in self._files()}
        t0 = time.time()
        try:
            while not self._stop.is_set():
                new = [f for f in self._files() if f.lower().endswith(".fos")
                       and os.stat(os.path.join(self.save_dir, f)).st_mtime != before.get(f)]
                if new:
                    clear_request(self.data_dir)                   # one save, not one every 5 seconds
                    self._settle()
                    self.result = self._rename()
                    break
                if time.time() - t0 > self.give_up:
                    self.problem = "the game didn't save (it may have been in a menu the whole time)"
                    break
                self._stop.wait(0.5)
        except OSError as e:
            self.problem = f"couldn't finish the save's name ({e})"
        finally:
            clear_request(self.data_dir)
            if self.on_done:
                self.on_done(self)

    def _settle(self, longest=60):
        """Wait until the game has finished writing the save and its co-saves."""
        t0, last, still = time.time(), None, time.time()
        while time.time() - t0 < longest and not self._stop.is_set():
            now = sorted((f, os.stat(os.path.join(self.save_dir, f)).st_size) for f in self._files())
            if now != last:
                last, still = now, time.time()
            elif time.time() - still >= self.quiet:
                return
            self._stop.wait(0.5)

    def _rename(self):
        stamp = time.strftime("%Y-%m-%d_%H-%M")
        new, n = f"{NAME}_{stamp}", 2
        while any(f.split(".")[0] == new for f in os.listdir(self.save_dir)):
            new, n = f"{NAME}_{stamp}_{n}", n + 1
        for f in self._files():
            os.rename(os.path.join(self.save_dir, f), os.path.join(self.save_dir, new + f[len(NAME):]))
        return new

    def stop(self):
        self._stop.set()
        clear_request(self.data_dir)
