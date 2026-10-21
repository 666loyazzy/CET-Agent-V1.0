# Synthetic practice examples

The twelve WAV files contain only original, fixed English exercise sentences from
`speech_service/catalog.py`. They were generated locally using Windows System.Speech,
Microsoft Zira Desktop (en-US), at rate -1, with SSML emphasis or IPA for the specified
word-stress variants. No learner recording, account data or API key is included.

These are synthesized listening examples, not human recordings or teacher-validated
pronunciation gold labels. Their actual audio is analyzed to draw reference curves;
the exercise targets describe a specific context and are not universally correct
intonation patterns. The waveform itself may not realize every target perfectly.

Rebuild on a Windows machine with an installed English System.Speech voice:
`powershell.exe -NoProfile -File scripts/generate_pronunciation_samples.ps1`.
Change the `-Voice` argument to use another installed English voice.
