# 把 Markdown 计划书转换为真正的 OOXML .docx（无需 Word/Pandoc/Node/Python）
# 用法: pwsh -File _build_docx.ps1
param(
  [string]$Md  = (Join-Path $PSScriptRoot '阶段一Demo排期与执行计划.md'),
  [string]$Out = (Join-Path $PSScriptRoot '阶段一Demo排期与执行计划.docx')
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null

$utf8 = New-Object System.Text.UTF8Encoding($false)
function WriteFile([string]$p,[string]$c){ [System.IO.File]::WriteAllText($p,$c,$utf8) }

# ---------- 内联/段落/表格 XML 构件 ----------
function RRun([string]$t,[bool]$bold=$false,[bool]$mono=$false){
  $rpr=''
  if($bold -or $mono){
    $rpr='<w:rPr>'
    if($bold){ $rpr+='<w:b/><w:bCs/>' }
    if($mono){ $rpr+='<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="微软雅黑"/><w:sz w:val="19"/><w:szCs w:val="19"/>' }
    $rpr+='</w:rPr>'
  }
  '<w:r>'+$rpr+'<w:t xml:space="preserve">'+[System.Security.SecurityElement]::Escape($t)+'</w:t></w:r>'
}
function Inline([string]$txt,[bool]$bold=$false){
  $sb=New-Object System.Text.StringBuilder
  foreach($seg in [regex]::Split($txt,'(\*\*[^*]+\*\*)')){
    if($seg -eq ''){ continue }
    $b=$bold; $s=$seg
    if($seg -match '^\*\*(?<c>[^*]+)\*\*$'){ $b=$true; $s=$Matches['c'] }
    foreach($p in [regex]::Split($s,'(`[^`]+`)')){
      if($p -eq ''){ continue }
      $mono=$false; $q=$p
      if($p -match '^`(?<c>[^`]+)`$'){ $mono=$true; $q=$Matches['c'] }
      [void]$sb.Append((RRun $q $b $mono))
    }
  }
  $sb.ToString()
}
function Para([string]$runs,[string]$extra=''){ '<w:p><w:pPr>'+$extra+'</w:pPr>'+$runs+'</w:p>' }
function Heading([int]$lvl,[string]$text){
  $style = switch($lvl){ 1 {'Title'} 2 {'Heading1'} default {'Heading2'} }
  '<w:p><w:pPr><w:pStyle w:val="'+$style+'"/></w:pPr>'+(Inline $text)+'</w:p>'
}
function Bullet([string]$text,[int]$indent=0){
  $l = 360 + $indent*360
  $extra = '<w:ind w:left="'+$l+'" w:hanging="240"/>'
  '<w:p><w:pPr>'+$extra+'</w:pPr>'+(RRun '• ')+(Inline $text)+'</w:p>'
}
function CodeLine([string]$text){
  $extra = '<w:pStyle w:val="Code"/><w:shd w:val="clear" w:color="auto" w:fill="F2F4F7"/>'
  Para (RRun $text $false $true) $extra
}
function Rule(){ Para '' '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="C9D3DE"/></w:pBdr>' }
function SplitRow([string]$line){
  $s=$line.Trim()
  if($s.StartsWith('|')){ $s=$s.Substring(1) }
  if($s.EndsWith('|')){ $s=$s.Substring(0,$s.Length-1) }
  return ($s -split '\|') | ForEach-Object { $_.Trim() }
}
function Cell([string]$text,[bool]$head){
  $tcpr='<w:tcPr><w:tcW w:w="0" w:type="auto"/><w:vAlign w:val="center"/>'
  if($head){ $tcpr+='<w:shd w:val="clear" w:color="auto" w:fill="E4EAF2"/>' }
  $tcpr+='</w:tcPr>'
  $ppr='<w:spacing w:before="30" w:after="30" w:line="240" w:lineRule="auto"/>'
  if($head){ $ppr='<w:spacing w:before="40" w:after="40" w:line="240" w:lineRule="auto"/>' }
  '<w:tc>'+$tcpr+(Para ((Inline $text $head)) $ppr)+'</w:tc>'
}
function Table([object[]]$rows){
  $bp=@('top','left','bottom','right','insideH','insideV') | ForEach-Object { '<w:'+$_+' w:val="single" w:sz="4" w:space="0" w:color="AEBACB"/>' }
  $borders='<w:tblBorders>' + ($bp -join '') + '</w:tblBorders>'
  $sb=New-Object System.Text.StringBuilder
  [void]$sb.Append('<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblLayout w:type="autofit"/>')
  [void]$sb.Append('<w:tblCellMar><w:top w:w="60" w:type="dxa"/><w:left w:w="90" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tblCellMar>')
  [void]$sb.Append($borders+'</w:tblPr>')
  $n=($rows[0].Count)
  if($n -lt 1){ $n=1 }
  [void]$sb.Append('<w:tblGrid>')
  for($c=0;$c -lt $n;$c++){ [void]$sb.Append('<w:gridCol w:w="'+[int](9638/$n)+'"/>') }
  [void]$sb.Append('</w:tblGrid>')
  $r=0
  foreach($row in $rows){
    $trpr='<w:trPr><w:cantSplit/>'
    if($r -eq 0){ $trpr+='<w:tblHeader/>' }
    $trpr+='</w:trPr>'
    [void]$sb.Append('<w:tr>'+$trpr)
    for($c=0;$c -lt $n;$c++){
      $txt = if($c -lt $row.Count){ $row[$c] } else { '' }
      [void]$sb.Append((Cell $txt ($r -eq 0)))
    }
    [void]$sb.Append('</w:tr>')
    $r++
  }
  [void]$sb.Append('</w:tbl>')
  # 表格后补一个空段落，避免连续表格粘连
  [void]$sb.Append((Para '' '<w:spacing w:after="80" w:line="240" w:lineRule="auto"/>'))
  $sb.ToString()
}

# ---------- 解析 Markdown ----------
$lines = @(Get-Content -LiteralPath $Md -Encoding UTF8)
$body  = New-Object System.Text.StringBuilder
$i = 0
while($i -lt $lines.Count){
  $raw = $lines[$i].TrimEnd()
  $t   = $raw.Trim()

  if($t -match '^```'){                                   # 代码块
    $i++
    $buf=@()
    while($i -lt $lines.Count -and $lines[$i].TrimEnd() -notmatch '^```'){ $buf += $lines[$i].TrimEnd(); $i++ }
    $i++
    foreach($c in $buf){ [void]$body.Append((CodeLine $c)) }
    continue
  }
  if($t -match '^\|'){                                    # 表格
    $rows=@()
    while($i -lt $lines.Count -and $lines[$i].TrimEnd() -match '^\s*\|'){
      $cells = SplitRow $lines[$i]
      $isSep = $true
      foreach($c in $cells){ if($c -notmatch '^:?-{2,}:?$'){ $isSep=$false } }
      if(-not $isSep){ $rows += ,$cells }
      $i++
    }
    if($rows.Count -gt 0){ [void]$body.Append((Table $rows)) }
    continue
  }
  if($t -match '^(#{1,6})\s+(.*)$'){                      # 标题
    [void]$body.Append((Heading $Matches[1].Length $Matches[2])); $i++; continue
  }
  if($t -match '^\s*[-*]\s+(.*)$'){                        # 无序列表
    [void]$body.Append((Bullet $Matches[1])); $i++; continue
  }
  if($t -match '^\s*(\d+)[.)]\s+(.*)$'){                   # 有序列表
    $num=$Matches[1]; $otext=$Matches[2]
    $lvl=0
    if($raw -match '^(\s+)'){ $lvl=[int]($Matches[1].Length/2) }
    [void]$body.Append((Bullet ($num+'. '+$otext) $lvl)); $i++; continue
  }
  if($t -match '^>\s?(.*)$'){                              # 引用
    $extra='<w:pStyle w:val="Quote"/><w:shd w:val="clear" w:color="auto" w:fill="F7F9FC"/><w:ind w:left="240" w:right="120"/><w:pBdr><w:left w:val="single" w:sz="18" w:space="6" w:color="8FAADC"/></w:pBdr>'
    [void]$body.Append((Para (Inline $Matches[1]) $extra)); $i++; continue
  }
  if($t -match '^\s*-{3,}\s*$'){ [void]$body.Append((Rule)); $i++; continue }
  if($t -eq ''){ $i++; continue }
  [void]$body.Append((Para (Inline $t))); $i++            # 普通段落
}

# ---------- 组装 docx 包 ----------
$sectPr = '<w:sectPr><w:footerReference w:type="default" r:id="rId2"/><w:pgSz w:w="11906" w:h="16838"/>' +
          '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="851" w:footer="992" w:gutter="0"/>' +
          '<w:cols w:space="425"/></w:sectPr>'

$documentXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
  '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' +
  'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
  '<w:body>' + $body.ToString() + $sectPr + '</w:body></w:document>'

$stylesXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
'<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Segoe UI" w:hAnsi="Segoe UI" w:eastAsia="微软雅黑" w:cs="Segoe UI"/>' +
'<w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:rPrDefault>' +
'<w:pPrDefault><w:pPr><w:spacing w:before="60" w:after="60" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>' +
'<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>' +
'<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
'<w:pPr><w:spacing w:before="0" w:after="120" w:line="300" w:lineRule="auto"/><w:jc w:val="center"/>' +
'<w:pBdr><w:bottom w:val="single" w:sz="12" w:space="6" w:color="1F3864"/></w:pBdr></w:pPr>' +
'<w:rPr><w:b/><w:color w:val="1F3864"/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>' +
'<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
'<w:pPr><w:keepNext/><w:spacing w:before="320" w:after="140"/><w:outlineLvl w:val="0"/>' +
'<w:pBdr><w:bottom w:val="single" w:sz="8" w:space="3" w:color="B4C2D8"/></w:pBdr></w:pPr>' +
'<w:rPr><w:b/><w:color w:val="1F3864"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>' +
'<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
'<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr>' +
'<w:rPr><w:b/><w:color w:val="2E5496"/><w:sz w:val="25"/><w:szCs w:val="25"/></w:rPr></w:style>' +
'<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/>' +
'<w:pPr><w:spacing w:before="100" w:after="100"/></w:pPr><w:rPr><w:i/><w:color w:val="44546A"/></w:rPr></w:style>' +
'<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/>' +
'<w:pPr><w:keepLines/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>' +
'<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="微软雅黑"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>' +
'</w:styles>'

$footerXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
'<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
'<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="0" w:after="0"/></w:pPr>' +
'<w:r><w:rPr><w:color w:val="8A94A6"/><w:sz w:val="17"/></w:rPr><w:t xml:space="preserve">《界域律令》阶段一（课程 Demo）排期与执行计划　·　第 </w:t></w:r>' +
'<w:fldSimple w:instr=" PAGE "><w:r><w:rPr><w:color w:val="8A94A6"/><w:sz w:val="17"/></w:rPr><w:t>1</w:t></w:r></w:fldSimple>' +
'<w:r><w:rPr><w:color w:val="8A94A6"/><w:sz w:val="17"/></w:rPr><w:t xml:space="preserve"> 页</w:t></w:r>' +
'</w:p></w:ftr>'

$contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
'<Default Extension="xml" ContentType="application/xml"/>' +
'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
'<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
'<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>' +
'<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
'</Types>'

$rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>' +
'</Relationships>'

$docRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>' +
'</Relationships>'

$now = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$core = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" ' +
'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" ' +
'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
'<dc:title>《界域律令》阶段一（课程 Demo）排期与执行计划</dc:title>' +
'<dc:creator>钱宥州</dc:creator><cp:lastModifiedBy>钱宥州</cp:lastModifiedBy>' +
'<dcterms:created xsi:type="dcterms:W3CDTF">'+$now+'</dcterms:created>' +
'<dcterms:modified xsi:type="dcterms:W3CDTF">'+$now+'</dcterms:modified>' +
'</cp:coreProperties>'

$tmp = Join-Path $env:TEMP ('docxbuild_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
New-Item -ItemType Directory -Path (Join-Path $tmp '_rels') | Out-Null
New-Item -ItemType Directory -Path (Join-Path $tmp 'word') | Out-Null
New-Item -ItemType Directory -Path (Join-Path $tmp 'word\_rels') | Out-Null
New-Item -ItemType Directory -Path (Join-Path $tmp 'docProps') | Out-Null

WriteFile (Join-Path $tmp '[Content_Types].xml')      $contentTypes
WriteFile (Join-Path $tmp '_rels\.rels')              $rels
WriteFile (Join-Path $tmp 'docProps\core.xml')        $core
WriteFile (Join-Path $tmp 'word\document.xml')        $documentXml
WriteFile (Join-Path $tmp 'word\styles.xml')          $stylesXml
WriteFile (Join-Path $tmp 'word\footer1.xml')         $footerXml
WriteFile (Join-Path $tmp 'word\_rels\document.xml.rels') $docRels

# XML 合法性自检
foreach($f in @('[Content_Types].xml','_rels\.rels','docProps\core.xml','word\document.xml','word\styles.xml','word\footer1.xml','word\_rels\document.xml.rels')){
  $p = Join-Path $tmp $f
  try { [void][xml](Get-Content -LiteralPath $p -Raw -Encoding UTF8) } catch { throw "XML 非法: $f -> $($_.Exception.Message)" }
}

if(Test-Path -LiteralPath $Out){ Remove-Item -LiteralPath $Out -Force }
# 手工打包：强制使用 '/' 分隔的条目名（OOXML 要求），避免 .NET Framework 写入反斜杠
$zip=[System.IO.Compression.ZipFile]::Open($Out,[System.IO.Compression.ZipArchiveMode]::Create)
foreach($f in (Get-ChildItem -LiteralPath $tmp -Recurse -File)){
  $rel = $f.FullName.Substring($tmp.Length+1).Replace('\','/')
  $entry = $zip.CreateEntry($rel,[System.IO.Compression.CompressionLevel]::Optimal)
  $es = $entry.Open()
  $fs = [System.IO.File]::OpenRead($f.FullName)
  $fs.CopyTo($es); $fs.Dispose(); $es.Dispose()
}
$zip.Dispose()
Remove-Item -LiteralPath $tmp -Recurse -Force

# 回读校验
$zip=[System.IO.Compression.ZipFile]::OpenRead($Out)
"输出: $Out"
"大小: {0:N0} bytes" -f (Get-Item -LiteralPath $Out).Length
"条目:"
$zip.Entries | ForEach-Object { '  {0,-38} {1,8:N0} bytes' -f $_.FullName,$_.Length }
$zip.Dispose()
