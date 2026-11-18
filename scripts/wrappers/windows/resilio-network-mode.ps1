param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("lan", "internet")]
    [string]$Mode,
    [Parameter(Mandatory = $true)]
    [string]$ProgramPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$rulePrefix = "LANLauncherNG Resilio LAN"
$nonLanRanges = @(
    "0.0.0.0-9.255.255.255",
    "11.0.0.0-126.255.255.255",
    "128.0.0.0-169.253.255.255",
    "169.255.0.0-172.15.255.255",
    "172.32.0.0-192.167.255.255",
    "192.169.0.0-223.255.255.255",
    "224.0.0.0-255.255.255.255",
    "2000::/3"
)

function Remove-LanRules {
    $rules = Get-NetFirewallRule -DisplayName "$rulePrefix*" -ErrorAction SilentlyContinue
    if ($null -ne $rules) {
        $rules | Remove-NetFirewallRule | Out-Null
    }
}

if ($Mode -eq "internet") {
    Remove-LanRules
    Write-Output "internet_mode_rules_removed"
    exit 0
}

if (-not (Test-Path $ProgramPath)) {
    Write-Error "sync_binary_not_found"
    exit 1
}

# To keep the rule set deterministic and idempotent, always clear the previous mode first.
Remove-LanRules

foreach ($direction in @("Inbound", "Outbound")) {
    New-NetFirewallRule `
        -DisplayName "$rulePrefix $direction Block Non-LAN" `
        -Direction $direction `
        -Enabled True `
        -Action Block `
        -Program $ProgramPath `
        -Protocol Any `
        -Profile Any `
        -RemoteAddress $nonLanRanges | Out-Null
}

Write-Output "lan_mode_rules_applied"
