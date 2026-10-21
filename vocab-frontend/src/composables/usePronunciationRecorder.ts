import { onBeforeUnmount, ref } from 'vue'

export function usePronunciationRecorder(onRecording: (blob: Blob) => void) {
  const state = ref<'idle' | 'requesting' | 'recording' | 'stopping'>('idle')
  const elapsed = ref(0)
  const level = ref(0)
  const error = ref('')
  let ticket = 0
  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let context: AudioContext | null = null
  let timer: ReturnType<typeof setInterval> | undefined
  let disposed = false

  function release() {
    clearInterval(timer)
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    context?.close().catch(() => {})
    context = null
    level.value = 0
  }

  function cancel() {
    ticket++
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    release()
    state.value = 'idle'
  }

  function stop() {
    if (recorder?.state === 'recording') {
      state.value = 'stopping'
      recorder.stop()
    }
  }

  async function start() {
    if (state.value !== 'idle') return
    error.value = ''
    if (
      !globalThis.isSecureContext ||
      !navigator.mediaDevices?.getUserMedia ||
      !globalThis.MediaRecorder
    ) {
      error.value = '录音需要 HTTPS 或 localhost，并使用支持麦克风的浏览器。你也可以上传录音。'
      return
    }
    state.value = 'requesting'
    const current = ++ticket
    const permissionTimer = setTimeout(() => {
      if (current === ticket && state.value === 'requesting') {
        cancel()
        error.value = '尚未获得麦克风授权，请检查浏览器提示后再试。'
      }
    }, 20000)
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: { ideal: 1 },
          echoCancellation: { ideal: false },
          noiseSuppression: { ideal: false },
          autoGainControl: { ideal: false }
        }
      })
      if (disposed || current !== ticket) {
        acquired.getTracks().forEach((track) => track.stop())
        return
      }
      clearTimeout(permissionTimer)
      stream = acquired
      const mimeType = [
        'audio/webm;codecs=opus',
        'audio/mp4',
        'audio/ogg;codecs=opus',
        'audio/webm'
      ].find((type) => MediaRecorder.isTypeSupported(type))
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      const chunks: Blob[] = []
      const activeRecorder = recorder
      let failed = false
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data)
      }
      recorder.onerror = () => {
        failed = true
        error.value = '录音被设备中断，请重录或上传音频。'
        stop()
      }
      recorder.onstop = () => {
        release()
        state.value = 'idle'
        if (!disposed && current === ticket && !failed) {
          const blob = new Blob(chunks, { type: activeRecorder.mimeType })
          if (blob.size && elapsed.value >= 0.25) onRecording(blob)
          else error.value = '录音太短，请完整读出题目。'
        }
      }
      stream.getAudioTracks().forEach((track) => {
        track.onended = stop
      })
      const started = performance.now()
      elapsed.value = 0
      try {
        context = new AudioContext()
        await context.resume()
      } catch {
        context = null
      }
      const analyser = context?.createAnalyser()
      if (analyser && context) context.createMediaStreamSource(stream).connect(analyser)
      const samples = new Float32Array(analyser?.fftSize || 2048)
      recorder.start(200)
      state.value = 'recording'
      timer = setInterval(() => {
        elapsed.value = (performance.now() - started) / 1000
        if (analyser) {
          analyser.getFloatTimeDomainData(samples)
          level.value = Math.min(
            1,
            Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length) * 6
          )
        }
        if (elapsed.value >= 30) stop()
      }, 100)
    } catch (caught) {
      if (current !== ticket || disposed) return
      release()
      state.value = 'idle'
      const name = caught instanceof DOMException ? caught.name : ''
      error.value =
        name === 'NotAllowedError'
          ? '麦克风权限未开启，请允许麦克风或上传已有音频。'
          : name === 'NotFoundError'
            ? '未找到麦克风，请连接设备或上传已有音频。'
            : '无法开始录音，请检查设备后重试。'
    } finally {
      clearTimeout(permissionTimer)
    }
  }

  onBeforeUnmount(() => {
    disposed = true
    cancel()
  })
  return { state, elapsed, level, error, start, stop, cancel }
}
