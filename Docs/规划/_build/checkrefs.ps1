# 文档一致性校验：两册的 § 小节号 / 附录字母 / K 编号引用是否都能落到目标位置
# 用法：pwsh -File checkrefs.ps1
$plan = Split-Path -Parent $PSScriptRoot
$manPath = Join-Path $plan '角色闪避与招架反击教学手册.md'
$pitPath = Join-Path $plan '角色闪避与招架反击-踩坑与错误归档.md'
$man = [System.IO.File]::ReadAllLines($manPath, [System.Text.Encoding]::UTF8)
$pit = [System.IO.File]::ReadAllLines($pitPath, [System.Text.Encoding]::UTF8)

$headSet = New-Object System.Collections.Generic.HashSet[string]
foreach ($l in $man) { if ($l -match '^(###|##) (\d+\.\d+)') { [void]$headSet.Add($Matches[2]) } }
$appSet = New-Object System.Collections.Generic.HashSet[string]
foreach ($l in $man) { if ($l -match '^## 附录 ([A-E])') { [void]$appSet.Add($Matches[1]) } }
$kSet = New-Object System.Collections.Generic.HashSet[string]
foreach ($l in $pit) { if ($l -match '^### (K\d{3})') { [void]$kSet.Add($Matches[1]) } }

$badSec = @(); $badApp = @(); $badK = @()
foreach ($pair in @(@('手册', $man), @('踩坑册', $pit))) {
    $name = $pair[0]; $lines = $pair[1]
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        $isArchive = ($line -match '源手册|归档|规划 §|README')
        foreach ($m in [regex]::Matches($line, '§(\d+\.\d+)')) {
            if ($isArchive) { continue }
            if (-not $headSet.Contains($m.Groups[1].Value)) { $badSec += ('{0}:{1} -> §{2}' -f $name, ($i+1), $m.Groups[1].Value) }
        }
        foreach ($m in [regex]::Matches($line, '附录 ([A-G])')) {
            if ($isArchive) { continue }
            if (-not $appSet.Contains($m.Groups[1].Value)) { $badApp += ('{0}:{1} -> 附录 {2}' -f $name, ($i+1), $m.Groups[1].Value) }
        }
        foreach ($m in [regex]::Matches($line, 'K(\d{3})')) {
            $k = 'K' + $m.Groups[1].Value
            if (-not $kSet.Contains($k)) { $badK += ('{0}:{1} -> {2}' -f $name, ($i+1), $k) }
        }
    }
}
"手册行数=$($man.Count) 小节=$($headSet.Count) 附录=$($appSet.Count)；踩坑册行数=$($pit.Count) K 条=$($kSet.Count)"
"悬空 § 引用=$($badSec.Count)"; $badSec | Select-Object -First 10
"悬空 附录 引用=$($badApp.Count)"; $badApp | Select-Object -First 10
"悬空 K 引用=$($badK.Count)"; $badK | Select-Object -First 10
if (($badSec.Count + $badApp.Count + $badK.Count) -eq 0) { 'RESULT: OK' } else { 'RESULT: FAIL'; exit 1 }
