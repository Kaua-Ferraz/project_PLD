param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("status", "enable", "disable", "remove")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$TaskNames = @(
    "PLD - Coleta prospectiva - 1145",
    "PLD - Coleta prospectiva - 2030"
)

switch ($Action) {
    "enable" {
        $TaskNames | ForEach-Object { Enable-ScheduledTask -TaskName $_ | Out-Null }
    }
    "disable" {
        $TaskNames | ForEach-Object { Disable-ScheduledTask -TaskName $_ | Out-Null }
    }
    "remove" {
        $TaskNames | ForEach-Object {
            Unregister-ScheduledTask -TaskName $_ -Confirm:$false
        }
    }
}

if ($Action -ne "remove") {
    $Status = @(
    foreach ($TaskName in $TaskNames) {
        $Task = Get-ScheduledTask -TaskName $TaskName
        $Info = Get-ScheduledTaskInfo -TaskName $TaskName
        [PSCustomObject]@{
            TaskName = $Task.TaskName
            State = $Task.State
            Enabled = $Task.Settings.Enabled
            NextRunTime = $Info.NextRunTime
            LastRunTime = $Info.LastRunTime
            LastTaskResult = $Info.LastTaskResult
            Execute = $Task.Actions.Execute
            Arguments = $Task.Actions.Arguments
            WorkingDirectory = $Task.Actions.WorkingDirectory
            Trigger = $Task.Triggers.StartBoundary
        }
    }
    )
    $Status | Format-List
}
