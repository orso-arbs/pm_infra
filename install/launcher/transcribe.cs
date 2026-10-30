// transcribe.exe: the launcher that sits in every space's pm_infra\ folder.
// Double-click: processes this space's Audio Inbox now, and registers the space if this
// laptop's pm_infra does not know it yet. Compiled on each laptop at install time with the
// C# compiler that ships with Windows (.NET Framework 4), so it is never downloaded as a binary.

using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static int Main(string[] args)
    {
        string exeDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string space = Path.GetFullPath(Path.Combine(exeDir, ".."));
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "pm_infra");
        string python = Path.Combine(root, @"env\Scripts\python.exe");

        if (!File.Exists(python))
        {
            MessageBox.Show(
                "pm_infra is not installed on this laptop.\n\nRun install_pm_infra.cmd in this folder first.",
                "pm_infra", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }

        var psi = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "-m pm_infra run-now --pause always --space \"" + space + "\"",
            WorkingDirectory = root,
            UseShellExecute = false
        };
        try
        {
            Process.Start(psi);
        }
        catch (Exception e)
        {
            MessageBox.Show("Could not start pm_infra:\n\n" + e.Message, "pm_infra", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        return 0;
    }
}
