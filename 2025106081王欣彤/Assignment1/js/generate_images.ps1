param(
    [Parameter(Mandatory = $true)]
    [string]$ApiKey,
    [string]$Model  = 'doubao-seedream-4-0-250828',
    [string]$Size   = '720x1280',
    [int]$MaxRetry  = 2,
    [string]$BookDir = ''    # 书的项目根目录; 留空时默认取 $PSScriptRoot 的父目录
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Net.Http

$ApiUrl = 'https://ark.cn-beijing.volces.com/api/v3/images/generations'

# 推算根目录（全程 UTF-16 字符串操作，绕开控制台编码问题）
if ([string]::IsNullOrWhiteSpace($BookDir)) {
    $Root = Split-Path -Parent $PSScriptRoot
} else {
    $Root = $BookDir
}
$OutDir  = Join-Path $Root '图片'
$Prompts = Join-Path $Root '脚本\prompts.txt'
if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

Write-Host ("Root    : {0}" -f $Root)
Write-Host ("OutDir  : {0}" -f $OutDir)
Write-Host ("Prompts : {0}" -f $Prompts)
Write-Host ("Prompts Exists: {0}" -f (Test-Path -LiteralPath $Prompts))

$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromSeconds(300)

# 读取分镜提示词：每行 s编号|提示词
$items = New-Object System.Collections.ArrayList
foreach ($line in [System.IO.File]::ReadAllLines($Prompts, [System.Text.Encoding]::UTF8)) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $idx = $line.IndexOf('|')
    if ($idx -lt 1) { continue }
    $id     = $line.Substring(0, $idx).Trim()
    $prompt = $line.Substring($idx + 1)
    [void]$items.Add([pscustomobject]@{ Id = $id; Prompt = $prompt })
}
Write-Host ("Loaded {0} prompts" -f $items.Count)

function Send-ImageRequest([string]$prompt) {
    $body = @{
        model                       = $Model
        prompt                      = $prompt
        size                        = $Size
        response_format             = 'url'
        watermark                   = $false
        sequential_image_generation = 'disabled'
    } | ConvertTo-Json -Depth 5
    $content = New-Object System.Net.Http.StringContent($body, [System.Text.Encoding]::UTF8, 'application/json')
    $msg = New-Object System.Net.Http.HttpRequestMessage('Post', $ApiUrl)
    $msg.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $ApiKey)
    $msg.Content = $content
    return $client.SendAsync($msg)
}

$results = @{}
$pending = @($items)

for ($round = 1; $round -le ($MaxRetry + 1); $round++) {
    if ($pending.Count -eq 0) { break }
    Write-Host ("--- Round {0}: {1} pending ---" -f $round, $pending.Count)

    $tasks = @{}
    foreach ($it in $pending) {
        $tasks[$it.Id] = Send-ImageRequest $it.Prompt
    }
    [System.Threading.Tasks.Task]::WaitAll(@($tasks.Values))

    $next = New-Object System.Collections.ArrayList
    foreach ($it in $pending) {
        $id = $it.Id
        try {
            $resp = $tasks[$id].Result
            $text = $resp.Content.ReadAsStringAsync().Result
        } catch {
            Write-Host ("[{0}] attempt {1} exception: {2}" -f $id, $round, $_.Exception.Message)
            [void]$next.Add($it)
            continue
        }
        if (-not $resp.IsSuccessStatusCode) {
            Write-Host ("[{0}] attempt {1} HTTP {2}: {3}" -f $id, $round, [int]$resp.StatusCode, $text)
            [void]$next.Add($it)
            continue
        }
        $json = $text | ConvertFrom-Json
        if ($json.error) {
            Write-Host ("[{0}] attempt {1} error {2} - {3}" -f $id, $round, $json.error.code, $json.error.message)
            $results[$id] = @{ Ok = $false; Url = $null; Size = $null; Attempts = $round; Error = ("{0}: {1}" -f $json.error.code, $json.error.message) }
            [void]$next.Add($it)
            continue
        }
        if ($json.data.Count -gt 0 -and $json.data[0].url) {
            $ext = if ($json.data[0].output_format) { $json.data[0].output_format } else { 'jpeg' }
            $results[$id] = @{ Ok = $true; Url = $json.data[0].url; Size = $json.data[0].size; Ext = $ext; Attempts = $round; Error = '' }
            Write-Host ("[{0}] OK {1} ({2}, attempt {3})" -f $id, $json.data[0].size, $ext, $round)
        } else {
            Write-Host ("[{0}] attempt {1} empty data" -f $id, $round)
            $results[$id] = @{ Ok = $false; Url = $null; Size = $null; Attempts = $round; Error = 'empty data' }
            [void]$next.Add($it)
        }
    }
    $pending = @($next)
    if ($pending.Count -gt 0) { Start-Sleep -Seconds (2 * $round) }
}

# 并行下载
$dl = @{}
foreach ($id in @($results.Keys)) {
    if ($results[$id].Ok) {
        $ext = $results[$id].Ext
        $dl[$id] = @{ Task = $client.GetByteArrayAsync($results[$id].Url); File = (Join-Path $OutDir ("{0}.{1}" -f $id, $ext)) }
    }
}
if ($dl.Count -gt 0) {
    [System.Threading.Tasks.Task]::WaitAll(@($dl.Values | ForEach-Object { $_.Task }))
}

$report = New-Object System.Collections.ArrayList
foreach ($it in $items) {
    $id = $it.Id
    $r = $results[$id]
    if ($null -eq $r -or -not $r.Ok) {
        $attempts = if ($r) { $r.Attempts } else { 0 }
        $err      = if ($r) { $r.Error  } else { 'not attempted' }
        [void]$report.Add([pscustomobject]@{ Id = $id; Status = 'FAILED'; Path = ''; Size = ''; Attempts = $attempts; Error = $err })
        continue
    }
    $file = $dl[$id].File
    try {
        [System.IO.File]::WriteAllBytes($file, $dl[$id].Task.Result)
        [void]$report.Add([pscustomobject]@{ Id = $id; Status = 'OK'; Path = $file; Size = $r.Size; Attempts = $r.Attempts; Error = '' })
    } catch {
        [void]$report.Add([pscustomobject]@{ Id = $id; Status = 'DOWNLOAD_FAILED'; Path = $file; Size = $r.Size; Attempts = $r.Attempts; Error = $_.Exception.Message })
    }
}

Write-Host ''
Write-Host '===== REPORT ====='
$report | ForEach-Object { Write-Host ("{0}`t{1}`t{2}`t{3}`t{4}" -f $_.Id, $_.Status, $_.Size, $_.Path, $_.Error) }
$report | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $OutDir 'generate_report.json') -Encoding UTF8

$failedCount = @($report | Where-Object { $_.Status -ne 'OK' }).Count
if ($failedCount -gt 0) { Write-Host ("FAILED: {0}" -f $failedCount); exit 1 }
Write-Host 'ALL DONE'