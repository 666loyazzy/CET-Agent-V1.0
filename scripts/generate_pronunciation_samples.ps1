param([string]$Voice = 'Microsoft Zira Desktop')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.speech-venv\Scripts\python.exe'
$catalog = & $python -c 'import json; from speech_service.catalog import EXERCISES; print(json.dumps(EXERCISES))'
if ($LASTEXITCODE -ne 0) { throw 'Could not load the exercise catalog' }
$items = $catalog | ConvertFrom-Json
$destination = Join-Path $project 'speech_service\samples'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.SelectVoice($Voice)
$speaker.Rate = -1
$ipa = @{
  'present-noun' = ([char]0x02C8) + 'p' + ([char]0x0279) + ([char]0x025B) + 'z' + ([char]0x0259) + 'nt'
  'present-verb' = 'p' + ([char]0x0279) + ([char]0x026A) + ([char]0x02C8) + 'z' + ([char]0x025B) + 'nt'
  'record-noun' = ([char]0x02C8) + ([char]0x0279) + ([char]0x025B) + 'k' + ([char]0x025A) + 'd'
  'record-verb' = ([char]0x0279) + ([char]0x026A) + ([char]0x02C8) + 'k' + ([char]0x0254) + ([char]0x0279) + 'd'
}
try {
  foreach ($item in $items) {
    $path = Join-Path $destination ($item.id + '.wav')
    $speaker.SetOutputToWaveFile($path)
    $text = [System.Security.SecurityElement]::Escape($item.text)
    if ($ipa.ContainsKey($item.id)) {
      $text = '<phoneme alphabet="ipa" ph="' + $ipa[$item.id] + '">' + $text + '</phoneme>'
    } elseif ($item.kind -eq 'sentence_stress') {
      $words = $text.Split(' ')
      $words[$item.target_index] = '<emphasis level="strong">' + $words[$item.target_index] + '</emphasis>'
      $text = $words -join ' '
    }
    $ssml = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US"><break time="250ms"/>' + $text + '<break time="250ms"/></speak>'
    $speaker.SpeakSsml($ssml)
    $speaker.SetOutputToNull()
    Write-Output ('Generated fixed exercise: ' + $item.id)
  }
} finally { $speaker.Dispose() }
