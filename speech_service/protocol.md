# English prosody analysis protocol · 1.1

Each measurement follows this code-enforced order:
audio.decode → audio.quality → praat.extract → text.align → prosody.features → prosody.assess → chart.validate.
The CET gateway then performs reference.compare → memory.update.

audio.decode: Decode actual bytes with FFmpeg to mono 16 kHz PCM. Limit 12 MB, 30 seconds and decoder time. Never trust a file extension.
audio.quality: Validate finite selection and pitch parameters, then reject silence and severe clipping. Unvoiced English consonants are normal and are not a global F0 coverage failure.
praat.extract: Parselmouth 0.4.7 / Praat raw autocorrelation, 10 ms, configurable 60–600 Hz baseline. Keep real frame times, null unvoiced frames, algorithm version and octave-jump warnings. A jump prevents target judgements.
text.align: PocketSphinx 5.1.1 en-US approximate forced alignment of the selected fixed script. Use word alignment for sentences and a second phone alignment for word-stress exercises. Missing word alignment is a warning, not loss of already measured acoustics: retain charts, omit word boundaries and word rate, and leave all text-dependent judgements uncertain. Missing phone alignment retains trustworthy word boundaries but no invented nuclei. Never report recognition, omissions or phoneme correctness from forced alignment.
prosody.features: Preserve measured vowel duration, relative digital RMS energy, real word boundaries and median-relative semitones. Never normalize away actual pitch range or duration in reported features.
prosody.assess: Produce explicit, versioned heuristic observations for the stated context. No global pronunciation score, official exam grade or probability. Word prominence, sentence energy, terminal pitch and phrase timing are practice cues, not validated classifiers.
chart.validate: Validate matching finite time/value lengths and monotonic frame times. Null F0 must remain disconnected. Normalized-time visual overlays never replace real-time rhythm measurements.
reference.compare: Only compare the same exercise and exact algorithm configuration. Keep reference ID/hash. Label synthesized examples and learner-selected references; neither is a certified gold standard.
memory.update: Save session-owned results, trace and configurable learning summaries. Disabled memory is not passed to the coach; clearing memory establishes a new cutoff. Deleted practices are excluded from summaries and their audio/coaching records are removed.

All step entries record real start/end timestamps, state and the SHA-256 version of this loaded protocol. Fatal failures stop downstream work. A text.align warning permits measured charts and uncertain findings, not text-dependent claims or contour reference comparisons. The teacher agent separately loads skill/speaking-coach.md, checks measured numbers and saves its actual trace.
