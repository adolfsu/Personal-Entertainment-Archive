param([switch]$NoAutoStart)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing, System.Net.Http
[Windows.Forms.Application]::EnableVisualStyles()
$project = [IO.Path]::GetFullPath($PSScriptRoot)
$control = Join-Path $project '.pea-control'
$logs = Join-Path $project 'logs'
$updateFile = Join-Path $project '.pea-updates\state.json'
$serverScript = Join-Path $project 'server.py'
$sha = [Security.Cryptography.SHA256]::Create()
$key = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($project.ToUpperInvariant()))).Replace('-', '')
$sha.Dispose()
$first = $false
$mutex = [Threading.Mutex]::new($true, "Local\PEA-Console-$key", [ref]$first)
$activate = [Threading.EventWaitHandle]::new($false, [Threading.EventResetMode]::AutoReset, "Local\PEA-Show-$key")
if (!$first) { $null = $activate.Set(); $activate.Dispose(); $mutex.Dispose(); exit }

$handler = [Net.Http.HttpClientHandler]::new()
$handler.UseProxy = $false
$handler.AllowAutoRedirect = $false
$http = [Net.Http.HttpClient]::new($handler)
$session = @{
    Service = $null; Launch = $null; Probe = $null; Network = $null
    Release = $null; ReleaseFor = ''; StopAt = $null; AfterStop = ''
    OpenWhenReady = !$NoAutoStart; MayClose = $false; Live = $false
    Issue = ''; UpdateNote = ''; LastUpdate = ''; LegacyBlocked = $false
}

function Read-LocalJson($path) {
    try {
        if ([IO.File]::Exists($path)) {
            [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json
        }
    } catch { }
}

function Get-DiskVersion {
    try { [IO.File]::ReadAllText((Join-Path $project 'VERSION')).Trim().TrimStart('v', 'V') }
    catch { '暂未读取' }
}

function Get-Address($port) { "http://127.0.0.1:$port" }

function Send-Local($port, $path, $body = $null, $timeout = 45000) {
    $address = Get-Address $port
    $method = if ($null -eq $body) { [Net.Http.HttpMethod]::Get } else { [Net.Http.HttpMethod]::Post }
    $request = [Net.Http.HttpRequestMessage]::new($method, "$address$path")
    if ($null -ne $body) {
        $request.Content = [Net.Http.StringContent]::new(($body | ConvertTo-Json -Compress), [Text.Encoding]::UTF8, 'application/json')
        $null = $request.Headers.TryAddWithoutValidation('Origin', $address)
    }
    $cancel = [Threading.CancellationTokenSource]::new($timeout)
    @{ Request = $request; Cancel = $cancel; Task = $http.SendAsync($request, $cancel.Token) }
}

function Receive-Local($pending) {
    try {
        $response = $pending.Task.GetAwaiter().GetResult()
        try { $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json }
        finally { $response.Dispose() }
    } finally {
        $pending.Request.Dispose()
        $pending.Cancel.Dispose()
    }
}

function Get-ServerProcess($processId) {
    $process = $null
    try {
        $process = [Diagnostics.Process]::GetProcessById([int]$processId)
        # Keep the original OS handle, including after PID reuse.
        $null = $process.Handle
        if (!$process.HasExited -and $process.ProcessName -match '^python(?:w|3(?:\.\d+)?)?$') { return $process }
    } catch { }
    if ($process) { $process.Dispose() }
}

function Find-LegacyService {
    $session.LegacyBlocked = $false
    $expected = [regex]::Escape($serverScript)
    $bundled = Join-Path $project 'runtime\python\python.exe'
    $previousUpdate = Read-LocalJson $updateFile
    $listeners = @{}
    foreach ($line in (& "$env:SystemRoot\System32\netstat.exe" -ano -p tcp)) {
        if ($line -match '^\s*TCP\s+127\.0\.0\.1:(\d+)\s+0\.0\.0\.0:0\s+\S+\s+(\d+)\s*$') {
            $listeners[[int]$Matches[2]] = [int]$Matches[1]
        }
    }
    if (!$listeners.Count) { return }
    foreach ($row in (Get-CimInstance Win32_Process -Filter "Name LIKE 'python%.exe'" -ErrorAction SilentlyContinue)) {
        $port = $listeners[[int]$row.ProcessId]
        if (!$port) { continue }
        $exact = $row.CommandLine -match ('^\s*(?:"[^"]+"|\S+)\s+(?:-B\s+)?(?:"' + $expected + '"|' + $expected + ')\s*$')
        $relative = $row.CommandLine -match '\s+"?(?:\.\\)?server\.py"?\s*$'
        $process = Get-ServerProcess $row.ProcessId
        if (!$process) { continue }
        $accepted = $false
        try { $answer = Receive-Local (Send-Local $port '/api/update/health' $null 450) }
        catch { $answer = $null }
        try {
            if (!$answer.version -or $null -eq $answer.instance -or $process.HasExited -or
                [Math]::Abs(($process.StartTime.ToUniversalTime() - $row.CreationDate.ToUniversalTime()).TotalSeconds) -ge 1) { continue }
            # An update can start a hidden process whose command line is unavailable.
            $updatedHere = $process.Path -ieq $bundled -and $answer.instance -cmatch '^[a-f0-9]{16}$' -and
                           $answer.instance -ceq $previousUpdate.job
            if ($exact -or $updatedHere) {
                $accepted = $true
                return @{ Process = $process; Port = $port; Version = $answer.version; Instance = $answer.instance; Stop = ''; Verified = $true }
            }
            if (($relative -and $port -eq 8777) -or $process.Path -ieq $bundled) {
                $session.LegacyBlocked = $true
            }
        } finally {
            if (!$accepted) { $process.Dispose() }
        }
    }
}

function Get-UpdateStatus {
    $state = Read-LocalJson $updateFile
    $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$state.updatedAt
    if ($state -and !$state.updatedAt) {
        try { $age = ([DateTime]::UtcNow - [IO.File]::GetLastWriteTimeUtc($updateFile)).TotalSeconds } catch { }
    }
    $active = ($state.phase -eq 'restarting' -and $age -ge 0 -and $age -lt 210) -or
              ($state.phase -eq 'downloading' -and $age -ge 0 -and $age -lt 600 -and $session.Service -and !$session.Service.Process.HasExited)
    @{ Active = $active; State = $state }
}

function Open-Archive {
    if ($session.Live) { Start-Process -FilePath (Get-Address $session.Service.Port) }
}

function Start-Archive {
    if ($session.Service -or $session.Launch -or (Get-UpdateStatus).Active) { return }
    if ($session.LegacyBlocked) {
        $session.Service = Find-LegacyService
        if ($session.Service) { return }
        if ($session.LegacyBlocked) {
            $session.Issue = '检测到旧版服务。请先关闭原来的命令窗口，再点“启动”。'
            return
        }
    }
    $session.Issue = ''
    $exe = Join-Path $project 'runtime\python\python.exe'
    if (![IO.File]::Exists($exe)) {
        $installed = Get-Command python.exe -ErrorAction SilentlyContinue
        if (!$installed -or $installed.Source -like '*\WindowsApps\*') {
            $session.Issue = '找不到 Python。请将便携 Python 放回项目目录，或安装 Python 3。'
            return
        }
        $exe = $installed.Source
    }
    $port = 8777
    if ([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners().Port -contains $port) { $port = 0 }
    $null = [IO.Directory]::CreateDirectory($logs)
    $saved = @{}
    $values = @{ GRDAG_BASE_DIR = $project; GRDAG_PORT = [string]$port; GRDAG_NO_BROWSER = '1'; PEA_UPDATE_INSTANCE = $null }
    foreach ($name in $values.Keys) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
    }
    try {
        $options = @{
            FilePath = $exe; ArgumentList = @('-B', ('"' + $serverScript + '"'))
            WorkingDirectory = $project; WindowStyle = 'Hidden'; PassThru = $true
            RedirectStandardOutput = (Join-Path $logs 'desktop-service.log')
            RedirectStandardError = (Join-Path $logs 'desktop-service-error.log')
        }
        $session.Launch = Start-Process @options
    } catch { $session.Issue = '无法启动服务。' + $_.Exception.Message }
    finally {
        foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    }
}

function Ask($message) {
    [Windows.Forms.MessageBox]::Show($form, $message, $form.Text, 'OKCancel', 'Warning', 'Button2') -eq [Windows.Forms.DialogResult]::OK
}

function Stop-Archive($after = '', [switch]$Force) {
    if ((Get-UpdateStatus).Active -or $session.Network -or !$session.Service.Verified) { return }
    $target = $session.Service
    if ($Force -or !$session.Service.Stop) {
        $warning = if ($session.Service.Stop) { '强制结束可能中断操作。确认结束后台吗？' }
                   else { '旧版后台只能通过结束进程关闭。请先保存网页内容、等当前操作完成，再确认结束。' }
        if (!(Ask $warning)) { return }
        if ((Get-UpdateStatus).Active -or ![object]::ReferenceEquals($target, $session.Service)) { return }
        if (!$target.Process.HasExited) { $target.Process.Kill() }
    } else {
        if ($session.StopAt -or !(Ask '请先保存网页中正在编辑的内容。确认继续吗？')) { return }
        if ((Get-UpdateStatus).Active -or ![object]::ReferenceEquals($target, $session.Service)) { return }
        [IO.File]::WriteAllBytes((Join-Path $control ('stop-' + $target.Stop)), [byte[]]@())
    }
    $session.AfterStop = $after
    $session.StopAt = [DateTime]::UtcNow
}

function Refresh-Service {
    if ($session.Probe -and $session.Probe.Task.IsCompleted) {
        $pending = $session.Probe
        $session.Probe = $null
        try { $reply = Receive-Local $pending } catch { $reply = $null }
        if ([object]::ReferenceEquals($session.Service, $pending.Service)) {
            $session.Live = [bool]($reply -and $reply.instance -ceq $session.Service.Instance -and
                                   $reply.version -ceq $session.Service.Version -and !$session.Service.Process.HasExited)
            if ($session.Live) { $session.Service.Verified = $true }
        }
    }
    if ($session.Service -and $session.Service.Process.HasExited) {
        $session.Service.Process.Dispose()
        $session.Service = $null
        $session.Live = $false
    }
    if (!$session.Service) {
        $record = Read-LocalJson (Join-Path $control 'service.json')
        if ($record.stop -cmatch '^[a-f0-9]{32}$' -and $record.instance -cmatch '^[a-f0-9]{16,32}$' -and
            $record.pid -is [ValueType] -and $record.port -is [ValueType] -and $record.port -ge 1 -and $record.port -le 65535) {
            $process = Get-ServerProcess $record.pid
            if ($process) {
                $session.Service = @{ Process = $process; Port = $record.port; Version = $record.version
                                      Instance = $record.instance; Stop = $record.stop; Verified = $false }
            }
        }
    }
    if ($session.Service -and !$session.Probe -and !$session.StopAt) {
        $session.Probe = Send-Local $session.Service.Port '/api/update/health' $null 900
        $session.Probe.Service = $session.Service
    }
}

function Receive-Update {
    if (!$session.Network -or !$session.Network.Task.IsCompleted) { return }
    $pending = $session.Network
    $session.Network = $null
    try {
        $reply = Receive-Local $pending
        if (!$reply.ok) { throw $reply.error }
        if ($pending.Action -eq 'install') {
            $session.UpdateNote = '正在下载并校验更新包…'
        } elseif ($reply.status -eq 'available') {
            $session.Release = $reply.release
            $session.ReleaseFor = $pending.Instance
            $session.UpdateNote = "可更新至 $($reply.release.version)（$($reply.release.source)）"
        } elseif ($reply.status -eq 'incompatible') {
            $session.UpdateNote = "版本 $($reply.release.version) 需要手动安装。"
        } elseif ($reply.status -eq 'unreleased') {
            $session.UpdateNote = '暂无可自动安装的正式版。'
        } else { $session.UpdateNote = '当前已是最新正式版。' }
    } catch { $session.UpdateNote = '更新操作失败。' + $_.Exception.Message }
}

function Open-Folder($path) {
    $null = [IO.Directory]::CreateDirectory($path)
    Start-Process -FilePath explorer.exe -ArgumentList ('"' + $path + '"')
}

$form = [Windows.Forms.Form]::new()
$form.Text = '娱乐档案控制台'
$form.ClientSize = [Drawing.Size]::new(600, 478)
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.StartPosition = 'CenterScreen'
$form.Font = [Drawing.Font]::new('Microsoft YaHei UI', 10)
$form.AutoScaleMode = 'Dpi'
$form.BackColor = [Drawing.Color]::FromArgb(249, 250, 252)
$form.ForeColor = [Drawing.Color]::FromArgb(27, 35, 46)

function Add-Label($caption, $x, $y, $width, $height, $size = 10, $bold = $false) {
    $item = [Windows.Forms.Label]::new()
    $item.Text = $caption
    $style = if ($bold) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }
    $item.Font = [Drawing.Font]::new($form.Font.FontFamily, [single]$size, $style)
    $item.SetBounds($x, $y, $width, $height)
    $form.Controls.Add($item)
    $item
}

function Add-Button($caption, $x, $y, $width, $action) {
    $item = [Windows.Forms.Button]::new()
    $item.Text = $caption
    $item.SetBounds($x, $y, $width, 36)
    $item.FlatStyle = 'Flat'
    $item.FlatAppearance.BorderColor = [Drawing.Color]::FromArgb(209, 217, 229)
    $item.BackColor = [Drawing.Color]::White
    $item.UseVisualStyleBackColor = $false
    $state = $session
    $item.Add_Click({
        try { & $action } catch { $state.Issue = $_.Exception.Message }
    }.GetNewClosure())
    $form.Controls.Add($item)
    $item
}

function Add-Divider($y) {
    $line = [Windows.Forms.Panel]::new()
    $line.BackColor = [Drawing.Color]::FromArgb(220, 226, 235)
    $line.SetBounds(24, $y, 552, 1)
    $form.Controls.Add($line)
}

$null = Add-Label '娱乐档案' 24 20 220 36 19 $true
$versionText = Add-Label '' 302 24 274 36 9
$versionText.TextAlign = 'TopRight'
$statusText = Add-Label '正在检查服务…' 24 73 552 28 15 $true
$messageText = Add-Label '' 24 108 552 43
$start = Add-Button '启动' 24 153 100 { $session.OpenWhenReady = $true; Start-Archive }
$open = Add-Button '打开档案网页' 136 153 134 { Open-Archive }
$open.BackColor = [Drawing.Color]::FromArgb(28, 92, 180)
$open.ForeColor = [Drawing.Color]::White
$restart = Add-Button '重启' 282 153 88 { Stop-Archive 'restart' }
$stop = Add-Button '停止' 382 153 88 { Stop-Archive }
Add-Divider 208
$null = Add-Label '程序更新' 24 224 170 26 12 $true
$updateText = Add-Label '' 24 257 552 44
$check = Add-Button '检查更新' 24 304 112 {
    $session.Release = $null
    $session.UpdateNote = '正在检查正式版…'
    $session.Network = Send-Local $session.Service.Port '/api/update/check'
    $session.Network.Action = 'check'
    $session.Network.Instance = $session.Service.Instance
}
$install = Add-Button '安装更新' 148 304 112 {
    if (!(Ask "安装 $($session.Release.version) 并重启？请先保存网页中的编辑。")) { return }
    $body = @{ version = $session.Release.version; sha256 = $session.Release.sha256 }
    $session.Release = $null
    $session.UpdateNote = '正在准备更新…'
    $session.Network = Send-Local $session.Service.Port '/api/update/install' $body
    $session.Network.Action = 'install'
}
$notes = Add-Button '查看更新说明' 272 304 134 {
    $details = [string]$session.Release.notes
    if (!$details.Trim()) { $details = '该版本没有附带更新说明。' }
    $null = [Windows.Forms.MessageBox]::Show($form, $details, '更新说明')
}
Add-Divider 360
$null = Add-Button '项目目录' 24 376 112 { Open-Folder $project }
$null = Add-Button '备份目录' 148 376 112 { Open-Folder (Join-Path $project 'backups') }
$null = Add-Button '日志目录' 272 376 112 { Open-Folder $logs }
$null = Add-Button '复制诊断' 396 376 112 {
    $report = @($statusText.Text, $messageText.Text, $versionText.Text, $updateText.Text, "项目目录  $project")
    if ($session.Service) { $report += "地址  $(Get-Address $session.Service.Port)    进程  $($session.Service.Process.Id)" }
    [Windows.Forms.Clipboard]::SetText(($report -join [Environment]::NewLine))
}
$force = Add-Button '强制结束后台' 24 428 142 { Stop-Archive $session.AfterStop -Force }
$force.Visible = $false
$closeLabel = Add-Label '关闭窗口时停止服务' 330 438 246 24 9
$closeLabel.TextAlign = 'TopRight'
$form.AcceptButton = $open

function Update-Window {
    if ($activate.WaitOne(0)) {
        if ($form.WindowState -eq 'Minimized') { $form.WindowState = 'Normal' }
        $form.Activate()
    }
    Refresh-Service
    Receive-Update
    $update = Get-UpdateStatus
    $state = $update.State
    if ($session.Launch -and $session.Launch.HasExited) {
        if (!$session.Service -and !$update.Active -and !$session.StopAt) {
            $session.Issue = "服务未能启动（退出代码 $($session.Launch.ExitCode)）。请查看日志或重试。"
            $session.OpenWhenReady = $false
        }
        $session.Launch.Dispose()
        $session.Launch = $null
    }
    if ($session.StopAt -and !$session.Service -and !$session.Launch -and !$update.Active) {
        $after = $session.AfterStop
        $session.StopAt = $null
        $session.AfterStop = ''
        $session.Issue = ''
        if ($after -eq 'exit') { $session.MayClose = $true; $form.Close(); return }
        if ($after -eq 'restart') { Start-Archive }
    }
    if ($session.Live -and $session.OpenWhenReady -and !$update.Active -and !$session.StopAt) {
        $session.OpenWhenReady = $false
        Open-Archive
    }
    $disk = Get-DiskVersion
    $running = if ($session.Service.Verified) { $session.Service.Version } else { '' }
    $versionText.Text = if ($running -and $running -ne $disk) { "运行 $running  ·  磁盘 $disk" } else { "版本 $disk" }
    $messageText.Text = if ($session.Issue) { $session.Issue } elseif ($running -and $running -ne $disk) { '程序文件已更新。重启服务以加载新版本。' } else { '' }
    $statusText.ForeColor = [Drawing.Color]::FromArgb(27, 35, 46)
    $timedOut = $session.StopAt -and ([DateTime]::UtcNow - $session.StopAt).TotalSeconds -gt 12
    if ($update.Active) { $statusText.Text = '正在更新' }
    elseif ($timedOut) { $statusText.Text = '仍在等待服务停止'; $messageText.Text = '后台长时间无响应时，可强制结束。' }
    elseif ($session.StopAt) { $statusText.Text = '正在停止服务' }
    elseif ($session.Live) {
        $statusText.Text = if ($session.Service.Stop) { '服务正在运行' } else { '旧版后台正在运行' }
        $statusText.ForeColor = [Drawing.Color]::FromArgb(17, 112, 77)
    } elseif ($session.Service.Verified) { $statusText.Text = '后台暂未响应' }
    elseif ($session.Service -or $session.Launch) { $statusText.Text = '正在启动服务' }
    elseif ($session.Issue) { $statusText.Text = '需要处理'; $statusText.ForeColor = [Drawing.Color]::FromArgb(165, 52, 44) }
    else { $statusText.Text = '服务已停止' }
    if ($state.job -and $state.phase -in @('installed', 'rolled-back', 'failed')) {
        $updateKey = "$($state.job)/$($state.phase)"
        if ($session.LastUpdate -ne $updateKey) {
            $session.LastUpdate = $updateKey
            if (!$session.Network) { $session.UpdateNote = $state.message }
        }
    }
    $updateText.Text = if ($update.Active) { [string]$state.message } else { $session.UpdateNote }
    $busy = $update.Active -or $session.Network -or $session.StopAt
    $start.Enabled = !$busy -and !$session.Service -and !$session.Launch
    $open.Enabled = $session.Live -and !$update.Active -and !$session.StopAt
    $stop.Enabled = !$busy -and [bool]$session.Service.Verified
    $restart.Enabled = $stop.Enabled
    $check.Enabled = $session.Live -and !$busy -and $running -eq $disk -and [bool]$session.Service.Stop
    $install.Enabled = $check.Enabled -and [bool]$session.Release -and $session.ReleaseFor -eq $session.Service.Instance
    $notes.Enabled = $install.Enabled
    $force.Visible = !$update.Active -and !$session.Network -and [bool]$session.Service.Verified -and
                     ($timedOut -or (!$session.Live -and !$session.StopAt))
}

$timer = [Windows.Forms.Timer]::new()
$timer.Interval = 420
$timer.Add_Tick({
    $timer.Stop()
    try { Update-Window } catch { $session.Issue = $_.Exception.Message; $messageText.Text = $session.Issue }
    finally { if (!$session.MayClose) { $timer.Start() } }
})
$form.Add_Shown({
    try {
        Refresh-Service
        if (!$session.Service) {
            $session.Service = Find-LegacyService
            $session.Live = [bool]$session.Service
        }
        if (!$NoAutoStart -and !$session.Service) { Start-Archive }
        Update-Window
    } catch { $session.Issue = $_.Exception.Message; $messageText.Text = $session.Issue }
    finally { $timer.Start() }
})
$form.Add_FormClosing({
    param($sender, $eventArgs)
    if ($session.MayClose) { return }
    if ((Get-UpdateStatus).Active -or $session.Network) {
        $eventArgs.Cancel = $true
        $messageText.Text = '正在完成更新操作，请稍候。'
    } elseif ($session.StopAt -or $session.Launch -or $session.Service) {
        $eventArgs.Cancel = $true
        if ($session.Service.Verified) { Stop-Archive 'exit' }
        elseif (!$session.StopAt) { $messageText.Text = '正在确认后台状态，请稍候。' }
    }
})
try { [Windows.Forms.Application]::Run($form) }
finally {
    $timer.Dispose()
    $http.Dispose()
    if ($session.Service) { $session.Service.Process.Dispose() }
    if ($session.Launch) { $session.Launch.Dispose() }
    $activate.Dispose()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
    $form.Dispose()
}
