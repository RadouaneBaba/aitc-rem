<#
    Generates tests/fixtures/narration.wav -- the spoken narration the
    end-to-end suite feeds to Chrome as a fake microphone.

    PLAN.md said this milestone "cannot be verified the way everything else here
    has been -- Playwright needs a fake audio file, not a microphone." This is
    the fake audio file. Windows' own speech synthesiser writes it, so producing
    it needs no network, no model download and nobody's voice.

    The output is COMMITTED. Run this once; do not wire it into check.sh. Which
    voices are installed differs per machine, so regenerating on CI would change
    the fixture's audio -- and therefore its transcript, and therefore the
    narration in narrated.recording.json -- for reasons that have nothing to do
    with the code under test.

    Two things about the shape of the file, both learned the hard way:

    * Chrome LOOPS --use-file-for-fake-audio-capture. A short clip repeats, and
      the same sentence then lands on three different steps, each of which
      becomes `narrated` on the strength of something the tester said once.
      So the file is longer than the test run.

    * The lead silence is what places the sentence. Playwright drives faster
      than a person, so the whole flow is over in about twenty seconds; the
      sentence has to fall inside the step it is about. Tune LEAD_SECONDS,
      re-run the e2e suite, check where it landed, then commit.

    Usage:  powershell -ExecutionPolicy Bypass -File scripts/make_narration_wav.ps1
#>

param(
    # What the tester says. The expected result of the approval step, phrased
    # the way somebody actually talks -- a sentence written to be transcribed
    # cleanly would not be evidence of anything.
    [string] $Text = "Now I'm checking that an order this size needs manager approval.",

    # Where the sentence starts. See the note above about placement.
    [double] $LeadSeconds = 6.0,

    # Total length. Must exceed the e2e run, or Chrome loops the clip and one
    # sentence is attributed to several steps. A recorded flow takes about
    # twenty seconds; 45 is comfortably clear of it without committing a file
    # measured in megabytes.
    [double] $TotalSeconds = 45.0,

    [string] $Out = "tests/fixtures/narration.wav"
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root $Out
$dir = Split-Path -Parent $target
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }

# 16 kHz mono 16-bit. Whisper resamples to 16 kHz anyway, and Chrome's fake
# capture device is happiest with a plain PCM file.
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SetOutputToWaveFile($target, $format)

    # Silence is emitted as a break rather than as padding bytes, so the whole
    # file comes out of one synthesiser and the header is written once.
    $builder = New-Object System.Speech.Synthesis.PromptBuilder
    $builder.AppendBreak([TimeSpan]::FromSeconds($LeadSeconds))
    $builder.AppendText($Text)
    $tail = [Math]::Max(1.0, $TotalSeconds - $LeadSeconds - 4.0)
    $builder.AppendBreak([TimeSpan]::FromSeconds($tail))

    $synth.Speak($builder)
}
finally {
    $synth.SetOutputToNull()
    $synth.Dispose()
}

$size = (Get-Item $target).Length
Write-Host "Wrote $target ($([Math]::Round($size / 1KB)) KB)"
Write-Host "Said at ~$LeadSeconds s: `"$Text`""
Write-Host ""
Write-Host "Commit it. Regenerating on another machine changes the voice, and"
Write-Host "therefore the transcript the fixture is built from."
