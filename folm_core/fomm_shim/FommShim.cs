// FOLM's FOMM-compatible scripting shim. Lets old FOMM C# installers (fomod/script.cs)
// run natively on Linux under Mono. Written from scratch for FOLM; it implements the
// documented FOMM script functions, but nothing touches the game directly:
//   - installed / generated files go into the mod's FOLM staging folder (FOLM_STAGING)
//   - reads come from the extracted archive (FOLM_FOMOD_ROOT) and a read-only
//     snapshot of the player's Data folder (FOLM_GAME_VIEW)
//   - plugin activation and INI edits are recorded in a plan file (FOLM_PLAN) that
//     FOLM applies itself
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;

namespace fomm.Scripting
{
    public class BaseScript
    {
        static string Env(string k) { return Environment.GetEnvironmentVariable(k) ?? ""; }
        static readonly string Root = Env("FOLM_FOMOD_ROOT");
        static readonly string View = Env("FOLM_GAME_VIEW");
        static readonly string Staging = Env("FOLM_STAGING");
        static readonly string IniDir = Env("FOLM_INI_DIR");
        internal static readonly List<string> Plan = new List<string>();
        internal static readonly List<string> Installed = new List<string>();
        static string[] activeCache;

        // ---------------------------------------------------------- helpers
        protected static string Norm(string p)
        {
            p = (p ?? "").Replace('\\', '/').Trim('/');
            while (p.StartsWith("./")) p = p.Substring(2);
            if (p.ToLowerInvariant().StartsWith("data/")) p = p.Substring(5);
            return p;
        }

        /// Resolve a path under baseDir ignoring letter case (Linux file systems are case-sensitive).
        protected static string Resolve(string baseDir, string rel)
        {
            string cur = baseDir;
            foreach (var part in Norm(rel).Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (!Directory.Exists(cur)) return null;
                string hit = Directory.EnumerateFileSystemEntries(cur)
                    .FirstOrDefault(e => string.Equals(Path.GetFileName(e), part, StringComparison.OrdinalIgnoreCase));
                if (hit == null) return null;
                cur = hit;
            }
            return cur;
        }

        static string StagingPath(string rel)
        {
            string p = Path.Combine(Staging, Norm(rel).Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(p));
            return p;
        }

        static string J(string s) { return "\"" + (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "") + "\""; }
        static void Record(string json) { Plan.Add(json); }
        protected static void Log(string msg) { Record("{\"op\":\"log\",\"text\":" + J(msg) + "}"); }

        // ---------------------------------------------------------- installing
        public static bool PerformBasicInstall()
        {
            foreach (var f in GetFomodFileList())
                if (!f.ToLowerInvariant().StartsWith("fomod/")) InstallFileFromFomod(f);
            return true;
        }

        public static bool InstallFileFromFomod(string file) { return InstallFileFromFomod(file, file); }

        public static bool InstallFileFromFomod(string from, string to)
        {
            string src = Resolve(Root, from);
            if (src == null || !File.Exists(src)) { Log("missing in archive: " + from); return false; }
            File.Copy(src, StagingPath(to), true);
            Installed.Add(Norm(to));
            return true;
        }

        public static bool InstallFolderFromFomod(string folder) { return InstallFolderFromFomod(folder, folder, true); }
        public static bool InstallFolderFromFomod(string folder, bool recurse) { return InstallFolderFromFomod(folder, folder, recurse); }
        public static bool InstallFolderFromFomod(string from, string to, bool recurse)
        {
            string src = Resolve(Root, from);
            if (src == null || !Directory.Exists(src)) { Log("missing folder in archive: " + from); return false; }
            foreach (var f in Directory.GetFiles(src, "*", recurse ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly))
            {
                string rel = f.Substring(src.Length).TrimStart(Path.DirectorySeparatorChar).Replace(Path.DirectorySeparatorChar, '/');
                InstallFileFromFomod(Norm(from) + "/" + rel, Norm(to) + "/" + rel);
            }
            return true;
        }

        // FOMM scripts use this both for copying a data file and for copying a file out of the mod's own
        // archive (e.g. BOG: CopyDataFile("CALI.nif", "meshes/.../femaleupperbody.nif")). Look in this
        // install first, then the archive, then the game.
        public static bool CopyDataFile(string from, string to)
        {
            string src = new[] { Resolve(Staging, from), Resolve(Root, from), Resolve(View, from) }
                .FirstOrDefault(x => x != null && File.Exists(x));
            if (src == null) return false;
            File.Copy(src, StagingPath(to), true);
            Installed.Add(Norm(to));
            return true;
        }

        public static bool GenerateDataFile(string path, byte[] data)
        {
            File.WriteAllBytes(StagingPath(path), data ?? new byte[0]);
            Installed.Add(Norm(path));
            return true;
        }

        public static string[] GetFomodFileList()
        {
            if (!Directory.Exists(Root)) return new string[0];
            return Directory.GetFiles(Root, "*", SearchOption.AllDirectories)
                .Select(f => f.Substring(Root.Length).TrimStart(Path.DirectorySeparatorChar).Replace(Path.DirectorySeparatorChar, '/'))
                .ToArray();
        }

        public static byte[] GetFileFromFomod(string file)
        {
            string src = Resolve(Root, file);
            return src != null && File.Exists(src) ? File.ReadAllBytes(src) : null;
        }

        // ---------------------------------------------------------- reading the player's game
        public static bool DataFileExists(string path)
        {
            string p = Resolve(View, path);
            return p != null && File.Exists(p);
        }

        public static byte[] GetExistingDataFile(string path)
        {
            // a file this install already generated wins over the game's copy
            string staged = Resolve(Staging, path);
            if (staged != null && File.Exists(staged)) return File.ReadAllBytes(staged);
            string p = Resolve(View, path);
            return p != null && File.Exists(p) ? File.ReadAllBytes(p) : null;
        }

        public static string[] GetExistingDataFileList(string path, string pattern, bool allFolders)
        {
            string dir = Resolve(View, path);
            if (dir == null || !Directory.Exists(dir)) return new string[0];
            return Directory.GetFiles(dir, string.IsNullOrEmpty(pattern) ? "*" : pattern,
                    allFolders ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly)
                .Select(f => f.Substring(View.Length).TrimStart(Path.DirectorySeparatorChar).Replace(Path.DirectorySeparatorChar, '/'))
                .ToArray();
        }

        public static string[] GetActivePlugins()
        {
            if (activeCache == null)
            {
                string f = Env("FOLM_ACTIVE_PLUGINS");
                activeCache = File.Exists(f) ? File.ReadAllLines(f).Where(l => l.Trim().Length > 0).ToArray() : new string[0];
            }
            return activeCache;
        }
        public static string[] GetAllPlugins() { return GetActivePlugins(); }
        public static bool IsPluginActive(string plugin)
        {
            return GetActivePlugins().Any(p => string.Equals(p, plugin, StringComparison.OrdinalIgnoreCase));
        }

        public static void SetPluginActivation(string plugin, bool activate)
        {
            Record("{\"op\":\"plugin\",\"name\":" + J(plugin) + ",\"active\":" + (activate ? "true" : "false") + "}");
        }

        // ---------------------------------------------------------- INI files (recorded, never written here)
        public static bool EditINI(string file, string section, string key, string value)
        {
            Record("{\"op\":\"ini\",\"file\":" + J(file) + ",\"section\":" + J(section) + ",\"key\":" + J(key) + ",\"value\":" + J(value) + "}");
            return true;
        }
        public static bool EditFalloutINI(string section, string key, string value, bool saveOld) { return EditINI("Fallout.ini", section, key, value); }
        public static bool EditFalloutINI(string section, string key, string value) { return EditINI("Fallout.ini", section, key, value); }
        public static bool EditPrefsINI(string section, string key, string value, bool saveOld) { return EditINI("FalloutPrefs.ini", section, key, value); }
        public static bool EditPrefsINI(string section, string key, string value) { return EditINI("FalloutPrefs.ini", section, key, value); }

        static string IniRead(string file, string section, string key)
        {
            string p = Resolve(IniDir, file);
            if (p == null) return null;
            string cur = "";
            foreach (var raw in File.ReadAllLines(p))
            {
                string l = raw.Trim();
                if (l.StartsWith("[") && l.EndsWith("]")) { cur = l.Substring(1, l.Length - 2); continue; }
                int eq = l.IndexOf('=');
                if (eq > 0 && string.Equals(cur, section, StringComparison.OrdinalIgnoreCase)
                    && string.Equals(l.Substring(0, eq).Trim(), key, StringComparison.OrdinalIgnoreCase))
                    return l.Substring(eq + 1).Trim();
            }
            return null;
        }
        static int ToInt(string s) { int v; return int.TryParse(s, out v) ? v : 0; }
        public static string GetFalloutIniString(string section, string key) { return IniRead("Fallout.ini", section, key); }
        public static int GetFalloutIniInt(string section, string key) { return ToInt(GetFalloutIniString(section, key)); }
        public static string GetPrefsIniString(string section, string key) { return IniRead("FalloutPrefs.ini", section, key); }
        public static int GetPrefsIniInt(string section, string key) { return ToInt(GetPrefsIniString(section, key)); }

        // ---------------------------------------------------------- versions
        public static Version GetFommVersion() { return new Version(0, 14, 11, 12); }
        public static Version GetFalloutVersion() { return new Version(1, 4, 0, 525); }
        public static bool ScriptExtenderPresent() { return File.Exists(Path.Combine(View, "..", "nvse_loader.exe")) || File.Exists(Path.Combine(View, "..", "fose_loader.exe")) || Env("FOLM_HAS_SE") == "1"; }
        public static Version GetNvseVersion() { return ScriptExtenderPresent() ? new Version(6, 4, 9, 0) : null; }
        public static Version GetFoseVersion() { return GetNvseVersion(); }
        public static Version GetScriptExtenderVersion() { return GetNvseVersion(); }

        // ---------------------------------------------------------- dialogs (real Windows Forms, drawn by Mono)
        public static DialogResult MessageBox(string message) { return System.Windows.Forms.MessageBox.Show(message, "Installer"); }
        public static DialogResult MessageBox(string message, string title) { return System.Windows.Forms.MessageBox.Show(message, title); }
        public static DialogResult MessageBox(string message, string title, MessageBoxButtons buttons) { return System.Windows.Forms.MessageBox.Show(message, title, buttons); }
        /// FOMM gave scripts an empty window to build their own installer UI on.
        /// Old installers were laid out for Windows' default UI font and ask for AutoScaleMode.Font
        /// against 6x13. Linux fonts measure bigger, which stretched the layout off the window. So FOLM
        /// picks a font size that measures like Windows' (scale factor 1): the author's layout, exactly.
        public static Form CreateCustomForm()
        {
            var f = new Form { StartPosition = FormStartPosition.CenterScreen, AutoScaleMode = AutoScaleMode.Font };
            var family = f.Font.FontFamily;
            for (float size = f.Font.Size; size > 4f; size -= 0.25f)
            {
                f.Font = new System.Drawing.Font(family, size);
                var d = f.CurrentAutoScaleDimensions;
                if (d.Height <= 13.5f && d.Width <= 6.5f) break;
            }
            return f;
        }
        public static void DisplayText(string text) { MessageBox(text); }
        public static void DisplayText(string text, string title) { MessageBox(text, title); }

        public static int[] Select(string[] items, string[] previews, string[] descriptions, string title, bool selectMany)
        {
            using (var f = new Form { Text = title ?? "Select", Width = 520, Height = 420, StartPosition = FormStartPosition.CenterScreen })
            {
                var list = new CheckedListBox { Dock = DockStyle.Fill, CheckOnClick = true };
                foreach (var it in items) list.Items.Add(it);
                if (!selectMany) list.ItemCheck += (s, e) => { if (e.NewValue == CheckState.Checked) for (int i = 0; i < list.Items.Count; i++) if (i != e.Index) list.SetItemChecked(i, false); };
                var ok = new Button { Text = "OK", Dock = DockStyle.Bottom, DialogResult = DialogResult.OK };
                f.Controls.Add(list); f.Controls.Add(ok); f.AcceptButton = ok;
                f.ShowDialog();
                return list.CheckedIndices.Cast<int>().ToArray();
            }
        }
    }

    public class FalloutBaseScript : BaseScript { }
    public class FalloutNewVegasBaseScript : FalloutBaseScript { }
    public class Fallout3BaseScript : FalloutBaseScript { }

    /// Entry point FOLM compiles next to the mod's script: runs Script.OnActivate()
    /// and writes the plan file.
    public static class FolmHost
    {
        public static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            bool ok = false;
            string error = null;
            try
            {
                var t = Type.GetType("Script") ?? AppDomain.CurrentDomain.GetAssemblies()
                    .SelectMany(a => a.GetTypes()).First(x => x.Name == "Script");
                var m = t.GetMethod("OnActivate", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static);
                object r = m.Invoke(null, null);
                ok = r is bool ? (bool)r : true;
            }
            catch (Exception e) { error = (e.InnerException ?? e).ToString(); }
            var sb = new StringBuilder("{\"result\":" + (ok ? "true" : "false") + ",\"error\":");
            sb.Append(error == null ? "null" : "\"" + error.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "") + "\"");
            sb.Append(",\"installed\":" + BaseScript.Installed.Count + ",\"actions\":[" + string.Join(",", BaseScript.Plan) + "]}");
            File.WriteAllText(Environment.GetEnvironmentVariable("FOLM_PLAN") ?? "plan.json", sb.ToString());
            return ok ? 0 : 1;
        }
    }
}
