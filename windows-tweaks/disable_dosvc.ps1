# Run as Administrator: disable Delivery Optimization (DoSvc) service
# Handles Win11 ACL protection on the DoSvc registry key (take ownership if needed)
$ErrorActionPreference = 'Continue'
$key = 'HKLM:\SYSTEM\CurrentControlSet\Services\DoSvc'

"=== Disable DoSvc script $(Get-Date) ==="
"Current user: $(whoami /user)"

# ---- Step 1: set Start=4 (disabled) directly ----
try {
    Set-ItemProperty -Path $key -Name Start -Value 4 -ErrorAction Stop
    "Step 1 OK: Start=4 written directly"
} catch {
    "Step 1 failed ($($_.Exception.Message)), entering ownership takeover..."
    # ---- Step 2: enable SeTakeOwnershipPrivilege and take ownership ----
    $def = @'
using System;
using System.Runtime.InteropServices;
public class Priv {
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool OpenProcessToken(IntPtr h, uint acc, out IntPtr tok);
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool LookupPrivilegeValue(string sys, string name, out long luid);
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool AdjustTokenPrivileges(IntPtr tok, bool dis, ref TOKPRIV1LUID newst, int len, IntPtr prev, IntPtr ret);
    [StructLayout(LayoutKind.Sequential, Pack=1)]
    struct TOKPRIV1LUID { public int Count; public long Luid; public int Attr; }
    public static void Enable(string priv) {
        IntPtr tok;
        OpenProcessToken(System.Diagnostics.Process.GetCurrentProcess().Handle, 0x28, out tok);
        TOKPRIV1LUID tp; tp.Count = 1; tp.Attr = 2;
        LookupPrivilegeValue(null, priv, out tp.Luid);
        AdjustTokenPrivileges(tok, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero);
    }
}
'@
    Add-Type -TypeDefinition $def
    [Priv]::Enable('SeTakeOwnershipPrivilege')
    [Priv]::Enable('SeRestorePrivilege')

    $admins = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $acl = Get-Acl $key
    $acl.SetOwner($admins)
    (Get-Item $key).SetAccessControl($acl)   # set owner first

    $acl = Get-Acl $key                      # re-read, then grant access
    $rule = New-Object System.Security.AccessControl.RegistryAccessRule(
        $admins, 'FullControl', 'Allow')
    $acl.SetAccessRule($rule)
    (Get-Item $key).SetAccessControl($acl)
    "Step 2 OK: ownership moved to Administrators"

    # ---- Step 3: write again ----
    Set-ItemProperty -Path $key -Name Start -Value 4
    "Step 3 OK: Start=4 written"
}

# ---- Stop the service ----
"--- Stop service ---"
sc.exe stop DoSvc

# ---- Clear delayed autostart flag ----
Set-ItemProperty -Path $key -Name DelayedAutostart -Value 0 -ErrorAction SilentlyContinue

# ---- Final status ----
"--- Final status ---"
Get-Service DoSvc | Format-List Name, Status, StartType
reg query 'HKLM\SYSTEM\CurrentControlSet\Services\DoSvc' /v Start
"=== Done, you can close this window ==="
Read-Host 'Press Enter to exit'
