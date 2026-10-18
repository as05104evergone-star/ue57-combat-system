#Requires -Version 5.1
<#
  export_datatables.ps1
  ---------------------------------------------------------------------------
  把《数值配置表-界域律令.xlsx》的 9 张业务子表（01/02/03/04/05/06/07/09/10）
  导出成 UE DataTable 可直接导入的 CSV + JSON。

  行结构 = 排期表 §8 的 S_GameParam { Key: Name; Value: float; Unit: Name; Note: Text }
  取值列 = 各子表的「基准数值」（06 表叫「目标数值」）
  Note   = 各子表的「设计意图与机制说明」/「设计意图」/「说明」/「阶段机制」/「计分规则与权重」
  Key    = 各子表的「程序参数键 (Key)」，同时作为 DataTable 的 RowName

  本脚本只读 xlsx，只写 <OutDir>\csv 与 <OutDir>\json，不碰 UE 工程资产。
  用法:  pwsh -NoProfile -File export_datatables.ps1 [-Xlsx <路径>] [-OutDir <目录>]
#>
[CmdletBinding()]
param(
    [string] $Xlsx   = '',
    [string] $OutDir = ''   # 注意：这里不能写 $PSScriptRoot（见下方说明）
)

$ErrorActionPreference = 'Stop'

# [!] 坑：用 powershell -File 调用本脚本（run_pipeline.cmd 就是这么调的）且带 [CmdletBinding()] 时，
#     参数默认值求值阶段 $PSScriptRoot 还是空的 —— 写 $OutDir = $PSScriptRoot 会得到空串，
#     紧接着 Join-Path $OutDir 'csv' 就报 "Cannot bind argument to parameter 'Path'"。
#     所以默认值必须留空，在脚本体（此处）里补，并对三种取法做兜底。
if ([string]::IsNullOrEmpty($OutDir)) {
    if ($PSScriptRoot)      { $OutDir = $PSScriptRoot }
    elseif ($PSCommandPath) { $OutDir = Split-Path -Parent $PSCommandPath }
    else                     { $OutDir = (Get-Location).Path }
}
$inv = [System.Globalization.CultureInfo]::InvariantCulture

# ---- 子表序号 → DataTable 资产名（排期表 §8）-------------------------------
# 键用两位字符串：OrderedDictionary 的整数索引器是按位置的，用 int 会错位
$SheetMap = [ordered]@{
    '01' = 'DT_Karma'
    '02' = 'DT_Combat'
    '03' = 'DT_Skill'
    '04' = 'DT_Enemy'
    '05' = 'DT_Boss'
    '06' = 'DT_Level'
    '07' = 'DT_Rating'
    '09' = 'DT_Gun'
    '10' = 'DT_Prop'
}

function Find-Xlsx([string] $explicit) {
    if ($explicit) {
        if (-not (Test-Path -LiteralPath $explicit)) { throw "找不到数值表: $explicit" }
        return (Resolve-Path -LiteralPath $explicit).Path
    }
    $cands = @(
        'C:\Users\123\Desktop\游戏架构设计\数值配置表-界域律令\数值配置表-界域律令.xlsx'
        (Join-Path $PSScriptRoot '..\..\Docs\数值配置表-界域律令.xlsx')
        (Join-Path $PSScriptRoot '数值配置表-界域律令.xlsx')
    )
    foreach ($c in $cands) { if (Test-Path -LiteralPath $c) { return (Resolve-Path -LiteralPath $c).Path } }
    $desktop = [Environment]::GetFolderPath('Desktop')
    if ($desktop -and (Test-Path -LiteralPath $desktop)) {
        $hit = Get-ChildItem -LiteralPath $desktop -Recurse -Depth 3 -Filter '*数值配置表*.xlsx' -File -ErrorAction SilentlyContinue |
               Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    throw '未找到《数值配置表-界域律令.xlsx》，请用 -Xlsx 显式指定路径。'
}

function Get-SharedStrings([string] $dir) {
    $out = New-Object System.Collections.Generic.List[string]
    $p = Join-Path $dir 'xl\sharedStrings.xml'
    if (-not (Test-Path -LiteralPath $p)) { return $out }
    $doc = New-Object System.Xml.XmlDocument
    $doc.Load($p)
    foreach ($si in $doc.SelectNodes('//*[local-name()="si"]')) {
        $txt = ($si.SelectNodes('.//*[local-name()="t"]') | ForEach-Object { $_.InnerText }) -join ''
        $out.Add($txt)
    }
    return $out
}

function Read-SheetRows([string] $path, $shared) {
    $doc = New-Object System.Xml.XmlDocument
    $doc.Load($path)
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($row in $doc.SelectNodes('//*[local-name()="row"]')) {
        $cells = @{}
        foreach ($c in $row.SelectNodes('./*[local-name()="c"]')) {
            $ref = [string] $c.GetAttribute('r')
            if (-not $ref) { continue }
            $col = ($ref -replace '\d', '')
            $t   = [string] $c.GetAttribute('t')
            $vn  = $c.SelectSingleNode('./*[local-name()="v"]')
            $val = ''
            if ($t -eq 's' -and $vn) {
                $idx = [int] $vn.InnerText
                if ($idx -ge 0 -and $idx -lt $shared.Count) { $val = $shared[$idx] }
            }
            elseif ($t -eq 'inlineStr') {
                $val = ($c.SelectNodes('.//*[local-name()="t"]') | ForEach-Object { $_.InnerText }) -join ''
            }
            elseif ($vn) { $val = $vn.InnerText }
            if ($val -ne '') { $cells[$col] = $val }
        }
        $rows.Add([pscustomobject]@{ Row = [int] $row.GetAttribute('r'); Cells = $cells })
    }
    return $rows
}

function Find-Col($cells, [string[]] $patterns) {
    foreach ($p in $patterns) {
        foreach ($k in ($cells.Keys | Sort-Object)) {
            if ($cells[$k] -like $p) { return $k }
        }
    }
    return $null
}

function Clean-Text([string] $s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace "`r`n", ' ' -replace "`n", ' ' -replace "`t", ' '
    return ($s -replace '\s{2,}', ' ').Trim()
}

function Csv-Field([string] $s) {
    if ($null -eq $s) { $s = '' }
    return '"' + ($s -replace '"', '""') + '"'
}

function Json-String([string] $s) {
    if ($null -eq $s) { $s = '' }
    $sb = New-Object System.Text.StringBuilder
    [void] $sb.Append('"')
    foreach ($ch in $s.ToCharArray()) {
        switch ($ch) {
            '"'  { [void] $sb.Append('\"') }
            '\'  { [void] $sb.Append('\\') }
            "`b" { [void] $sb.Append('\b') }
            "`f" { [void] $sb.Append('\f') }
            "`n" { [void] $sb.Append('\n') }
            "`r" { [void] $sb.Append('\r') }
            "`t" { [void] $sb.Append('\t') }
            default {
                if ([int] $ch -lt 32) { [void] $sb.Append(('\u{0:x4}' -f [int] $ch)) }
                else { [void] $sb.Append($ch) }
            }
        }
    }
    [void] $sb.Append('"')
    return $sb.ToString()
}

function Fmt-Num([double] $v) {
    return $v.ToString('0.############', $inv)
}

# ===========================================================================
$Xlsx = Find-Xlsx $Xlsx
Write-Host "[数值表] $Xlsx"
Write-Host ("[数值表] 修改时间 {0}" -f (Get-Item -LiteralPath $Xlsx).LastWriteTime)

$csvDir  = Join-Path $OutDir 'csv'
$jsonDir = Join-Path $OutDir 'json'
New-Item -ItemType Directory -Path $csvDir, $jsonDir -Force | Out-Null

$tmp = Join-Path ([IO.Path]::GetTempPath()) ('dt_export_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
$report = [ordered]@{ xlsx = $Xlsx; exported_at = (Get-Date).ToString('s'); tables = [ordered]@{} }
$rowMap = New-Object System.Collections.Generic.List[string]
$rowMap.Add('DataTable,RowName,编号,参数名称,基准数值,单位,建议调优区间')

try {
    # 复制一份再解包：WPS/Excel 打开着也能读
    $copy = Join-Path $tmp 'book.xlsx'
    $src  = [IO.File]::Open($Xlsx, 'Open', 'Read', 'ReadWrite')
    try { $dst = [IO.File]::Create($copy); $src.CopyTo($dst); $dst.Dispose() } finally { $src.Dispose() }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $x = Join-Path $tmp 'x'
    [IO.Compression.ZipFile]::ExtractToDirectory($copy, $x)

    $shared = Get-SharedStrings $x
    $wb = New-Object System.Xml.XmlDocument
    $wb.Load((Join-Path $x 'xl\workbook.xml'))
    $rels = New-Object System.Xml.XmlDocument
    $rels.Load((Join-Path $x 'xl\_rels\workbook.xml.rels'))

    foreach ($sheet in $wb.SelectNodes('//*[local-name()="sheet"]')) {
        $name = [string] $sheet.GetAttribute('name')
        $rid  = [string] $sheet.GetAttribute('id')
        if (-not $rid) { $rid = [string] $sheet.GetAttribute('r:id') }
        if (-not $name -or $name -notmatch '^(\d+)\s') { continue }
        $no = [int] $Matches[1]
        $skey = '{0:d2}' -f $no
        if (-not $SheetMap.Contains($skey)) { continue }
        $dtName = $SheetMap[$skey]

        $target = $null
        foreach ($r in $rels.SelectNodes('//*[local-name()="Relationship"]')) {
            if ($r.GetAttribute('Id') -eq $rid) { $target = $r.GetAttribute('Target'); break }
        }
        if (-not $target) { Write-Warning "子表 $name 找不到 worksheet 路径"; continue }
        $target = ($target -replace '^/xl/', '') -replace '^/', ''
        $sp = Join-Path $x ('xl\' + ($target -replace '/', '\'))
        if (-not (Test-Path -LiteralPath $sp)) { Write-Warning "子表 $name 文件不存在: $sp"; continue }

        $rows = Read-SheetRows $sp $shared

        # 表头行 = 含「程序参数键」的那一行（各表行号不一致，靠内容定位）
        $head = $null
        foreach ($r in $rows) {
            $hitv = $r.Cells.Values | Where-Object { $_ -like '*程序参数键*' }
            if ($hitv) { $head = $r; break }
        }
        if (-not $head) { Write-Warning "子表 $name 没找到「程序参数键」表头行，跳过"; continue }

        $cKey  = Find-Col $head.Cells @('*程序参数键*')
        $cVal  = Find-Col $head.Cells @('*基准数值*', '*目标数值*')
        $cUnit = Find-Col $head.Cells @('*单位*')
        $cNote = Find-Col $head.Cells @('*设计意图*', '*阶段机制*', '*计分规则*', '*说明*')
        $cId   = Find-Col $head.Cells @('*编号*')
        $cName = Find-Col $head.Cells @('*参数名称*', '*指标名称*', '*档位名称*', '*物件与参数名称*', '*关卡指标名称*', '*名称*')
        $cHint = Find-Col $head.Cells @('*建议调优区间*', '*冷却时间*')

        foreach ($k in @($cKey, $cVal, $cUnit)) {
            if (-not $k) { throw "子表 $name 表头缺列（Key/基准数值/单位）：$($cKey)/$($cVal)/$($cUnit)" }
        }

        $recs   = New-Object System.Collections.Generic.List[object]
        $skips  = New-Object System.Collections.Generic.List[string]
        foreach ($r in $rows) {
            if ($r.Row -le $head.Row) { continue }
            $key = Clean-Text $r.Cells[$cKey]
            if (-not $key) { continue }
            if ($key -notmatch '^[a-z][a-z0-9._]*$') {
                $skips.Add("row $($r.Row): 键名不符合 ^[a-z][a-z0-9._]*$ → `"$key`"")
                continue
            }
            $rawVal = Clean-Text $r.Cells[$cVal]
            $num = 0.0
            if (-not [double]::TryParse($rawVal, [Globalization.NumberStyles]::Float, $inv, [ref] $num)) {
                $skips.Add("row $($r.Row) [$key]: 基准数值不是纯数字 → `"$rawVal`"")
                continue
            }
            $unit = Clean-Text $r.Cells[$cUnit]
            $note = Clean-Text $(if ($cNote) { $r.Cells[$cNote] } else { '' })
            $id   = Clean-Text $(if ($cId)   { $r.Cells[$cId]   } else { '' })
            $pn   = Clean-Text $(if ($cName) { $r.Cells[$cName] } else { '' })
            $hint = Clean-Text $(if ($cHint) { $r.Cells[$cHint] } else { '' })
            $recs.Add([pscustomobject]@{
                Key = $key; Value = $num; Unit = $unit; Note = $note
                Id = $id; ParamName = $pn; Hint = $hint; Row = $r.Row
            })
            $rowMap.Add((@($dtName, $key, $id, $pn, (Fmt-Num $num), $unit, $hint) | ForEach-Object { Csv-Field $_ }) -join ',')
        }

        # ---- CSV（UTF-8 无 BOM；首列 Name = DataTable 的 RowName，与 Key 同值）----
        $csvPath = Join-Path $csvDir "$dtName.csv"
        $lines = New-Object System.Collections.Generic.List[string]
        $lines.Add('Name,Key,Value,Unit,Note')
        foreach ($rec in $recs) {
            $lines.Add((@($rec.Key, $rec.Key, (Fmt-Num $rec.Value), $rec.Unit, $rec.Note) | ForEach-Object { Csv-Field $_ }) -join ',')
        }
        [IO.File]::WriteAllLines($csvPath, $lines, (New-Object System.Text.UTF8Encoding($false)))

        # ---- JSON（DataTable FillFromJSONString 直接吃的形状）----
        # 实测（见 _probe_json.json）：必须是**数组**、每项带 "Name"（= RowName）；
        # 字典形状 {"行名":{...}} 会让 FillFromJSONString 返回 True 却静默导入 0 行；
        # 带 BOM 同样静默失败，所以这里固定写 UTF-8 无 BOM。
        # 列名用「导出名」（= 结构体成员的友好名，如 Key/Value/Unit/Note），
        # 不是 get_column_names() 返回的内部改名（形如 Key_15_ABCD…）。
        $jsonPath = Join-Path $jsonDir "$dtName.json"
        $jb = New-Object System.Text.StringBuilder
        [void] $jb.AppendLine('[')
        for ($i = 0; $i -lt $recs.Count; $i++) {
            $rec = $recs[$i]
            $comma = if ($i -lt $recs.Count - 1) { ',' } else { '' }
            [void] $jb.Append('  {"Name": ' + (Json-String $rec.Key) + ', ')
            [void] $jb.Append('"Key": '    + (Json-String $rec.Key) + ', ')
            [void] $jb.Append('"Value": '  + (Fmt-Num $rec.Value)   + ', ')
            [void] $jb.Append('"Unit": '   + (Json-String $rec.Unit) + ', ')
            [void] $jb.Append('"Note": '   + (Json-String $rec.Note) + '}')
            [void] $jb.AppendLine($comma)
        }
        [void] $jb.AppendLine(']')
        [IO.File]::WriteAllText($jsonPath, $jb.ToString(), (New-Object System.Text.UTF8Encoding($false)))

        $report.tables[$dtName] = [ordered]@{
            sheet         = $name
            header_row    = $head.Row
            columns       = [ordered]@{ key = $cKey; value = $cVal; unit = $cUnit; note = $cNote; id = $cId; name = $cName }
            rows          = $recs.Count
            skipped       = @($skips)
            csv           = "csv/$dtName.csv"
            json          = "json/$dtName.json"
        }
        Write-Host ("[{0}] 子表 {1} 表头行 {2} → {3} 行" -f $dtName, $name, $head.Row, $recs.Count)
        foreach ($s in $skips) { Write-Warning "  $dtName $s" }
    }

    [IO.File]::WriteAllLines((Join-Path $OutDir '_rowmap.csv'), $rowMap, (New-Object System.Text.UTF8Encoding($true)))
    [IO.File]::WriteAllText((Join-Path $OutDir '_export_report.json'),
        ([pscustomobject] $report | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))

    $total = 0
    foreach ($k in $report.tables.Keys) { $total += $report.tables[$k].rows }
    Write-Host ""
    Write-Host ("导出完成：{0} 张表 / 共 {1} 行 → {2}" -f $report.tables.Count, $total, $OutDir)
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
