/**
 * ErrorReporter — Titan in-app issue recorder (admin-only).
 *
 * Floating launcher → panel → Start Recording:
 *   • Screen video + mic audio (getDisplayMedia + getUserMedia → MediaRecorder → .webm)
 *   • Live voice transcript (Web Speech API)
 *   • Click events + pages visited
 * Done → POST metadata → upload video → "Report #N saved".
 * A "Reports" tab lists prior issues with their status (open → resolved).
 *
 * CHROME MICROPHONE OVERRIDES (hard lessons from the interview app):
 *   - Secure-context guard: getUserMedia / Web Speech silently die on non-HTTPS.
 *   - Visible mic-status pill: every SpeechRecognition error code is surfaced,
 *     never console-only.
 *   - Permission precheck + explicit getUserMedia so the prompt appears up front.
 *   - Auto-restart on Chrome's spurious onend, guarded by an isStopping flag.
 *   - Graceful degradation: if the mic/transcript fails, video still records and
 *     the report still saves — a report is never lost to a mic problem.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

type RecState = 'idle' | 'recording' | 'paused' | 'saving' | 'saved'
type View = 'record' | 'list'

interface SpeechSegment { text: string; timestamp_ms: number; confidence: number }
interface ClickEvent { timestamp_ms: number; tag: string; text: string; selector: string; url: string }
interface MicError { when_ms: number; code: string; message: string }
interface ReportRow {
  id: number; title: string; status: string; severity: string; route: string
  reported_by: string | null
  reported_at: string; resolved_at: string | null; video_path: string | null
  speech_segment_count: number; click_event_count: number
}

const api = (path: string, init?: RequestInit) =>
  fetch(path, { credentials: 'include', ...init })

function pickMime(): string {
  const prefs = [
    'video/webm;codecs=vp9,opus',
    'video/webm;codecs=vp8,opus',
    'video/webm;codecs=vp8',
    'video/webm',
  ]
  for (const m of prefs) {
    try { if ((window as any).MediaRecorder?.isTypeSupported?.(m)) return m } catch { /* ignore */ }
  }
  return 'video/webm'
}

const SpeechRecognition: any =
  (typeof window !== 'undefined') &&
  ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)

// Live mic VU meter — segmented bars that light green→yellow→red with input
// level. RMS ~0 = silence, ~0.05–0.2 = normal speech; a sqrt scale lights
// several segments even at quiet speech so it reads as clearly "alive".
const VU_SEGMENTS = 18
function LevelMeter({ level, active }: { level: number; active: boolean }) {
  const lit = active ? Math.round(Math.min(1, Math.sqrt(level) * 1.45) * VU_SEGMENTS) : 0
  return (
    <div className="flex items-end gap-[2px] h-6 w-full" role="meter"
      aria-label="Microphone input level" aria-valuenow={Math.round(Math.min(1, level) * 100)}
      aria-valuemin={0} aria-valuemax={100} title={`mic level ${(level * 100).toFixed(0)}`}>
      {Array.from({ length: VU_SEGMENTS }).map((_, i) => {
        const on = i < lit
        const color = i < VU_SEGMENTS * 0.6 ? 'bg-green-400'
          : i < VU_SEGMENTS * 0.85 ? 'bg-yellow-400' : 'bg-red-500'
        return (
          <div key={i}
            className={`flex-1 rounded-sm transition-all duration-75 ${on ? color : 'bg-slate-700'}`}
            style={{ height: `${35 + (i / VU_SEGMENTS) * 65}%` }} />
        )
      })}
    </div>
  )
}

export default function ErrorReporter({ canViewList = true }: { canViewList?: boolean }) {
  // canViewList=false for Cloudflare-Access testers: they can record + file
  // reports, but the admin-only "Reports" queue (GET /api/error-reports) is hidden.
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<View>('record')
  const [state, setState] = useState<RecState>('idle')
  const [severity, setSeverity] = useState<'low' | 'normal' | 'high' | 'critical'>('normal')

  const [speech, setSpeech] = useState<SpeechSegment[]>([])
  const [clicks, setClicks] = useState<ClickEvent[]>([])
  const [pages, setPages] = useState<string[]>([])
  const [interim, setInterim] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [savedId, setSavedId] = useState<number | null>(null)
  const [saveNote, setSaveNote] = useState<string>('')

  // Mic device selection + live input level. A getUserMedia track can succeed
  // yet carry pure silence (muted device, or a wrong default like "Stereo Mix").
  // Letting the user pick the mic and SEE the level is what actually fixes that.
  const [audioDevices, setAudioDevices] = useState<MediaDeviceInfo[]>([])
  const [selectedMicId, setSelectedMicId] = useState('')   // '' = system default
  const [micLevel, setMicLevel] = useState(0)              // live RMS 0..~1
  const [testing, setTesting] = useState(false)            // idle "Test mic" preview active
  const [micConfirmed, setMicConfirmed] = useState(false)  // a real signal has been heard

  // Mic / permission diagnostics — the "overrides" surface.
  const [micStatus, setMicStatus] = useState<{ tone: 'ok' | 'warn' | 'err'; text: string }>({
    tone: 'ok', text: '',
  })
  const micDiagRef = useRef<any>({ errors: [] as MicError[], recognition_restarts: 0 })

  const [reports, setReports] = useState<ReportRow[]>([])
  const [reportsLoading, setReportsLoading] = useState(false)
  const [resolvingId, setResolvingId] = useState<number | null>(null)
  const [movingId, setMovingId] = useState<number | null>(null)

  // Refs for live recording machinery
  const recognitionRef = useRef<any>(null)
  const isStoppingRef = useRef(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<BlobPart[]>([])
  const screenStreamRef = useRef<MediaStream | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const startTimeRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const clickHandlerRef = useRef<((e: MouseEvent) => void) | null>(null)
  const lastRouteRef = useRef(location.pathname)

  // Mic-level meter machinery
  const audioCtxRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const levelTimerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const testStreamRef = useRef<MediaStream | null>(null)
  const isRecordingRef = useRef(false)
  const peakLevelRef = useRef(0)
  const silenceWarnedRef = useRef(false)

  // Drag-to-move
  const [pos, setPos] = useState({ x: 0, y: 0 })
  useEffect(() => {
    setPos({ x: window.innerWidth - 380, y: window.innerHeight - 460 })
  }, [])
  const dragRef = useRef({ dragging: false, offX: 0, offY: 0 })
  const onDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button, select, a')) return
    dragRef.current = { dragging: true, offX: e.clientX - pos.x, offY: e.clientY - pos.y }
    const move = (ev: MouseEvent) => {
      if (!dragRef.current.dragging) return
      setPos({ x: ev.clientX - dragRef.current.offX, y: ev.clientY - dragRef.current.offY })
    }
    const up = () => {
      dragRef.current.dragging = false
      document.removeEventListener('mousemove', move)
      document.removeEventListener('mouseup', up)
    }
    document.addEventListener('mousemove', move)
    document.addEventListener('mouseup', up)
  }, [pos])

  const logMic = (code: string, message: string) => {
    micDiagRef.current.errors.push({ when_ms: Date.now() - startTimeRef.current, code, message })
  }

  // ── Live mic-level meter + silent-mic watchdog ──────────────────────────
  // The #1 wasted report: getUserMedia succeeded but the chosen device fed pure
  // silence, so we showed a cheerful "Recording — speak…" while capturing 49s of
  // dead air. We now read the actual signal and tell the user when it's silent.
  const stopLevelMeter = () => {
    if (levelTimerRef.current) { clearInterval(levelTimerRef.current); levelTimerRef.current = undefined }
    try { analyserRef.current?.disconnect() } catch { /* ignore */ }
    analyserRef.current = null
    try { audioCtxRef.current?.close() } catch { /* ignore */ }
    audioCtxRef.current = null
    setMicLevel(0)
  }

  const attachLevelMeter = (stream: MediaStream) => {
    stopLevelMeter()
    setMicConfirmed(false)
    try {
      const Ctx = (window.AudioContext || (window as any).webkitAudioContext)
      const ctx = new Ctx()
      // Chrome's autoplay policy can start the context "suspended" on origins
      // with no media-engagement history (e.g. titan-prod) — the analyser then
      // reads pure silence and the meter never moves even with a live mic.
      // Resume it (and again on the interval if it slips back to suspended).
      ctx.resume?.().catch(() => { /* best-effort */ })
      const source = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      source.connect(analyser) // NOT to destination — avoids echo/feedback
      audioCtxRef.current = ctx
      analyserRef.current = analyser
      peakLevelRef.current = 0
      silenceWarnedRef.current = false
      const data = new Uint8Array(analyser.fftSize)
      levelTimerRef.current = setInterval(() => {
        const a = analyserRef.current
        if (!a) return
        const c = audioCtxRef.current
        if (c && c.state === 'suspended') { c.resume?.().catch(() => {}) }
        a.getByteTimeDomainData(data)
        let sum = 0
        for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v }
        const rms = Math.sqrt(sum / data.length)
        setMicLevel(rms)
        if (rms > peakLevelRef.current) peakLevelRef.current = rms
        if (rms > 0.05) {
          setMicConfirmed(true) // clearly audible → mic proven working
          // If the early-silence watchdog fired before the user spoke, retract it.
          if (silenceWarnedRef.current) {
            silenceWarnedRef.current = false
            micDiagRef.current.mic_silent = false
            if (isRecordingRef.current) setMicStatus({ tone: 'ok', text: 'Recording — mic is live.' })
          }
        }
        // Watchdog: 5s of recording with no audible peak → warn once (non-fatal).
        if (isRecordingRef.current && !silenceWarnedRef.current
            && (Date.now() - startTimeRef.current) > 5000 && peakLevelRef.current < 0.012) {
          silenceWarnedRef.current = true
          micDiagRef.current.mic_silent = true
          setMicStatus({ tone: 'err', text: 'Mic is silent — we’re not hearing your voice (video still records). Click Done, then use “Test mic” to pick a working microphone before recording again.' })
        }
      }, 120)
    } catch { /* WebAudio unavailable — meter is best-effort */ }
  }

  const enumerateMics = useCallback(async () => {
    try {
      const devs = await navigator.mediaDevices.enumerateDevices()
      setAudioDevices(devs.filter(d => d.kind === 'audioinput'))
    } catch { /* ignore */ }
  }, [])

  // Idle "Test mic": open the chosen device and show the level bar so the user
  // confirms their voice registers BEFORE wasting a recording on a dead mic.
  const startTestMic = async () => {
    try {
      const audio: any = selectedMicId ? { deviceId: { exact: selectedMicId } } : true
      const s = await navigator.mediaDevices.getUserMedia({ audio })
      testStreamRef.current = s
      attachLevelMeter(s)
      setTesting(true)
      enumerateMics() // device labels populate once permission is granted
      setMicStatus({ tone: 'ok', text: 'Speak now — the bar should move. If it stays flat, choose another mic.' })
    } catch (err: any) {
      setMicStatus({ tone: 'err', text: `Can’t open the mic (${err?.name || 'error'}). Allow mic access or pick another device.` })
    }
  }

  const stopTestMic = () => {
    stopLevelMeter()
    testStreamRef.current?.getTracks().forEach(t => t.stop())
    testStreamRef.current = null
    setTesting(false)
    setMicConfirmed(false)
  }

  // ── Track page visits while recording ──
  useEffect(() => {
    if (state === 'recording' && location.pathname !== lastRouteRef.current) {
      setPages(prev => (prev.includes(location.pathname) ? prev : [...prev, location.pathname]))
      lastRouteRef.current = location.pathname
    }
  }, [location.pathname, state])

  // ── Speech recognition (with robust restart + visible errors) ──
  const startRecognition = useCallback(() => {
    if (!SpeechRecognition) {
      setMicStatus({ tone: 'warn', text: 'Live transcript unsupported in this browser (use Chrome). Video + audio still recording.' })
      return
    }
    const rec = new SpeechRecognition()
    rec.continuous = true
    rec.interimResults = true
    rec.lang = 'en-US'

    rec.onresult = (event: any) => {
      let finalText = ''
      let interimText = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) finalText += event.results[i][0].transcript
        else interimText = event.results[i][0].transcript
      }
      if (finalText.trim()) {
        setSpeech(prev => [...prev, {
          text: finalText.trim(),
          timestamp_ms: Date.now() - startTimeRef.current,
          confidence: event.results[event.results.length - 1][0].confidence || 0,
        }])
        setMicStatus({ tone: 'ok', text: 'Listening — transcript captured' })
      }
      setInterim(interimText)
    }

    rec.onerror = (e: any) => {
      const code = e?.error || 'unknown'
      switch (code) {
        case 'no-speech':
          return // normal silence — keep going
        case 'aborted':
          return // we stopped it
        case 'not-allowed':
        case 'service-not-allowed':
          logMic(code, 'mic permission blocked')
          setMicStatus({ tone: 'err', text: 'Mic blocked — click the camera/lock icon in the address bar → Allow microphone, then Pause/Resume.' })
          return
        case 'audio-capture':
          logMic(code, 'no microphone')
          setMicStatus({ tone: 'err', text: 'No microphone detected. Plug one in (video still records).' })
          return
        case 'network':
          logMic(code, 'speech network error')
          setMicStatus({ tone: 'warn', text: 'Speech service unreachable (network). Keep talking — it retries; video/audio still record.' })
          return
        default:
          logMic(code, 'speech error')
          setMicStatus({ tone: 'warn', text: `Transcript hiccup (${code}) — retrying.` })
      }
    }

    rec.onend = () => {
      // Chrome stops recognition on its own; restart unless we're tearing down.
      if (isStoppingRef.current || recognitionRef.current !== rec) return
      const n = (micDiagRef.current.recognition_restarts || 0) + 1
      micDiagRef.current.recognition_restarts = n
      // When Web Speech can't hold the mic alongside the recorder it ends
      // instantly and would hot-loop thousands of times (saw 3,653). Back off,
      // and after a cap give up on the live transcript — the recorded audio
      // still captures the voice, so the report isn't lost.
      if (n > 60) {
        setMicStatus({ tone: 'warn', text: 'Live transcript unavailable here, but your voice is recorded in the video — keep talking.' })
        return
      }
      setTimeout(() => {
        if (!isStoppingRef.current && recognitionRef.current === rec) {
          try { rec.start() } catch { /* ignore double-start */ }
        }
      }, 300)
    }

    try {
      rec.start()
      recognitionRef.current = rec
    } catch {
      setMicStatus({ tone: 'warn', text: 'Could not start live transcript — video + audio still recording.' })
    }
  }, [])

  // ── Start recording (screen video + mic audio + transcript + clicks) ──
  const startRecording = useCallback(async () => {
    setSaveNote('')
    // Secure-context guard — the #1 silent-failure we keep hitting.
    if (!window.isSecureContext) {
      setMicStatus({ tone: 'err', text: 'Recording needs a secure (HTTPS) page. Open the site via its https:// address, not a raw IP.' })
      return
    }
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setMicStatus({ tone: 'err', text: 'Screen recording not supported in this browser. Use desktop Chrome/Edge.' })
      return
    }

    // 1) Screen share (required). User picks tab/window/screen.
    let screen: MediaStream
    try {
      screen = await navigator.mediaDevices.getDisplayMedia({
        // cursor:'always' renders the mouse pointer into the video. IMPORTANT:
        // Chrome OMITS the cursor from browser-TAB captures, so the user must
        // share a Window or the Entire Screen to get cursor movement. That's why
        // preferCurrentTab (tab capture) dropped the cursor — removed. Matches the
        // Nelson ERP recorder, which shares window/screen and captures the pointer.
        video: { frameRate: 15, cursor: 'always' },
        // Do NOT capture system/tab audio: on Windows Chrome, sharing audio here
        // races the mic capture and silences the getUserMedia track (reports #1/#2
        // recorded -91 dB dead air). Audio comes ONLY from the mic below.
        audio: false,
      } as any)
    } catch (err: any) {
      setMicStatus({ tone: 'err', text: 'Screen share canceled or blocked — nothing recorded. Click Start Recording and choose a screen/tab to share.' })
      logMic('display-denied', String(err?.name || err))
      return
    }
    screenStreamRef.current = screen

    // 2) Mic (best-effort). Explicit getUserMedia so the prompt shows up front
    //    and a denial is caught *visibly* rather than dying silently.
    let mic: MediaStream | null = null
    let micPermission = 'unknown'
    try {
      const p = await (navigator as any).permissions?.query?.({ name: 'microphone' as any })
      if (p?.state) micPermission = p.state
    } catch { /* permissions API not available — ignore */ }

    // Reuse a live "Test mic" stream so we don't prompt for the mic a 2nd time.
    const testMic = testStreamRef.current
    if (testMic && testMic.getAudioTracks().some(t => t.readyState === 'live')) {
      mic = testMic
      testStreamRef.current = null // ownership transfers to micStreamRef
      micStreamRef.current = mic
      setTesting(false)
    }

    if (!mic) {
      try {
        const audio: any = selectedMicId ? { deviceId: { exact: selectedMicId } } : true
        try {
          mic = await navigator.mediaDevices.getUserMedia({ audio })
        } catch (e: any) {
          // Chosen device vanished/unavailable → fall back to the system default.
          if (selectedMicId && (e?.name === 'OverconstrainedError' || e?.name === 'NotFoundError')) {
            mic = await navigator.mediaDevices.getUserMedia({ audio: true })
          } else { throw e }
        }
        micStreamRef.current = mic
      } catch (err: any) {
        const name = err?.name || 'error'
        if (name === 'NotAllowedError') {
          setMicStatus({ tone: 'err', text: 'Mic blocked — allow the microphone in the address-bar prompt. Recording your screen WITHOUT voice; you can still type details after.' })
        } else if (name === 'NotFoundError') {
          setMicStatus({ tone: 'err', text: 'No microphone found — recording screen only.' })
        } else {
          setMicStatus({ tone: 'warn', text: `Mic unavailable (${name}) — recording screen only.` })
        }
        logMic('getusermedia-' + name, String(err?.message || ''))
      }
    }
    if (mic) {
      attachLevelMeter(mic) // live level + silent-mic watchdog
      enumerateMics()
    }

    // 3) Combine tracks → MediaRecorder
    const tracks: MediaStreamTrack[] = [...screen.getVideoTracks()]
    if (mic) tracks.push(...mic.getAudioTracks())
    else tracks.push(...screen.getAudioTracks()) // fall back to system audio
    const combined = new MediaStream(tracks)

    chunksRef.current = []
    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(combined, { mimeType: pickMime() })
    } catch {
      recorder = new MediaRecorder(combined)
    }
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunksRef.current.push(e.data) }
    recorder.start(1000) // 1s timeslices so we never lose a long recording
    recorderRef.current = recorder

    // If the user clicks the browser's native "Stop sharing", finalize + save.
    screen.getVideoTracks()[0].addEventListener('ended', () => {
      if (!isStoppingRef.current) stopAndSave()
    })

    // 4) State + transcript + clicks
    const micTrack = mic?.getAudioTracks?.()[0]
    micDiagRef.current = {
      secure_context: window.isSecureContext,
      speech_supported: !!SpeechRecognition,
      mic_permission: micPermission,
      mic_obtained: !!mic,
      mic_device_label: micTrack?.label || '',
      mic_device_id: micTrack?.getSettings?.().deviceId || selectedMicId || 'default',
      mic_track_muted: micTrack?.muted ?? null,
      mic_silent: false,
      display_audio: screen.getAudioTracks().length > 0,
      errors: [],
      recognition_restarts: 0,
    }
    isRecordingRef.current = true
    isStoppingRef.current = false
    startTimeRef.current = Date.now()
    setSpeech([]); setClicks([]); setPages([location.pathname]); setInterim('')
    setState('recording')
    setMicStatus(mic
      ? { tone: 'ok', text: 'Recording — speak to describe the issue.' }
      : micStatus.tone === 'err' ? micStatus : { tone: 'warn', text: 'Recording screen (no mic).' })

    timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000)), 1000)
    lastRouteRef.current = location.pathname
    startRecognition()

    const clickHandler = (e: MouseEvent) => {
      const t = e.target as HTMLElement
      const el = t.closest('button, a, [role="button"], input, select, [data-tour]') || t
      if (el.closest('#titan-error-reporter')) return
      setClicks(prev => [...prev, {
        timestamp_ms: Date.now() - startTimeRef.current,
        tag: el.tagName,
        text: (el.textContent || el.getAttribute('placeholder') || '').trim().slice(0, 80),
        selector: el.id ? `#${el.id}`
          : el.getAttribute('data-tour') ? `[data-tour="${el.getAttribute('data-tour')}"]` : '',
        url: window.location.pathname,
      }])
    }
    document.addEventListener('click', clickHandler, true)
    clickHandlerRef.current = clickHandler
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, startRecognition, selectedMicId])

  const togglePause = useCallback(() => {
    if (state === 'recording') {
      setState('paused')
      isStoppingRef.current = true
      isRecordingRef.current = false
      try { recognitionRef.current?.stop() } catch { /* ignore */ }
      recognitionRef.current = null
      try { recorderRef.current?.pause() } catch { /* ignore */ }
      if (timerRef.current) clearInterval(timerRef.current)
      setMicStatus({ tone: 'warn', text: 'Paused' })
    } else if (state === 'paused') {
      setState('recording')
      isStoppingRef.current = false
      isRecordingRef.current = true
      try { recorderRef.current?.resume() } catch { /* ignore */ }
      startTimeRef.current = Date.now() - elapsed * 1000
      timerRef.current = setInterval(() => setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000)), 1000)
      startRecognition()
      setMicStatus({ tone: 'ok', text: 'Recording…' })
    }
  }, [state, elapsed, startRecognition])

  const teardown = () => {
    isStoppingRef.current = true
    isRecordingRef.current = false
    try { recognitionRef.current?.stop() } catch { /* ignore */ }
    recognitionRef.current = null
    if (clickHandlerRef.current) {
      document.removeEventListener('click', clickHandlerRef.current, true)
      clickHandlerRef.current = null
    }
    if (timerRef.current) clearInterval(timerRef.current)
    stopLevelMeter()
    testStreamRef.current?.getTracks().forEach(t => t.stop())
    testStreamRef.current = null
    screenStreamRef.current?.getTracks().forEach(t => t.stop())
    micStreamRef.current?.getTracks().forEach(t => t.stop())
  }

  const stopAndSave = useCallback(async () => {
    if (state === 'saving' || state === 'saved') return
    setState('saving')

    // Finalize the recorder and wait for the last chunk.
    const recorder = recorderRef.current
    const blob: Blob | null = await new Promise((resolve) => {
      if (!recorder || recorder.state === 'inactive') return resolve(
        chunksRef.current.length ? new Blob(chunksRef.current, { type: 'video/webm' }) : null)
      recorder.onstop = () => resolve(new Blob(chunksRef.current, { type: 'video/webm' }))
      try { recorder.stop() } catch { resolve(chunksRef.current.length ? new Blob(chunksRef.current, { type: 'video/webm' }) : null) }
    })

    teardown()
    // Final truth from the actual signal, not the early watchdog (which can fire
    // before the user starts talking).
    micDiagRef.current.mic_peak_level = Number(peakLevelRef.current.toFixed(4))
    micDiagRef.current.mic_silent = peakLevelRef.current < 0.012

    const description = speech.map(s => s.text).join(' ').slice(0, 4000)
    let id: number | null = null
    try {
      const res = await api('/api/error-reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          route: location.pathname,
          severity,
          speech_segments: speech,
          click_events: clicks,
          pages_visited: pages,
          description,
          mic_diagnostics: micDiagRef.current,
          dom_state: { title: document.title, viewport: { w: window.innerWidth, h: window.innerHeight } },
          browser_info: navigator.userAgent,
        }),
      })
      const data = await res.json()
      id = data.id
      setSavedId(id)
    } catch (err) {
      console.error('save metadata failed', err)
      setSaveNote('Could not save the report. Check your connection and try again.')
      setState('saved')
      return
    }

    // Upload the video (best-effort; report already exists if this fails).
    if (id && blob && blob.size > 0) {
      try {
        const fd = new FormData()
        fd.append('file', blob, `report-${id}.webm`)
        const up = await api(`/api/error-reports/${id}/video`, { method: 'POST', body: fd })
        if (!up.ok) setSaveNote('Report saved, but the video upload failed.')
      } catch (err) {
        console.error('video upload failed', err)
        setSaveNote('Report saved, but the video upload failed.')
      }
    } else if (!blob || blob.size === 0) {
      setSaveNote('Report saved (no video captured).')
    }
    setState('saved')
    // Nudge the header alert badge to re-count (a new open report just landed).
    window.dispatchEvent(new CustomEvent('titan:reports-changed'))
  }, [state, speech, clicks, pages, severity, location.pathname])

  const resetForNew = () => {
    stopTestMic()
    setState('idle'); setSpeech([]); setClicks([]); setPages([]); setInterim('')
    setElapsed(0); setSavedId(null); setSaveNote(''); setMicStatus({ tone: 'ok', text: '' })
    chunksRef.current = []
  }

  const loadReports = useCallback(async () => {
    setReportsLoading(true)
    try {
      const res = await api('/api/error-reports')
      setReports(res.ok ? await res.json() : [])
    } catch { setReports([]) }
    setReportsLoading(false)
  }, [])

  // Mark a report resolved (or reopen it) straight from the queue. Optimistically
  // updates the row, then re-syncs from the server, and nudges the header badge
  // so its unresolved count drops immediately.
  const setReportStatus = useCallback(async (id: number, status: 'resolved' | 'open') => {
    setResolvingId(id)
    setReports(prev => prev.map(r => (r.id === id ? { ...r, status } : r)))
    try {
      await api(`/api/error-reports/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      window.dispatchEvent(new CustomEvent('titan:reports-changed'))
      await loadReports()
    } catch {
      await loadReports()  // revert optimistic change to server truth on failure
    } finally {
      setResolvingId(null)
    }
  }, [loadReports])

  // Promote a report into the admin Build Ideas backlog (and resolve it). For
  // reports that are really "future feature" requests, not bugs to fix now.
  const moveToIdeas = useCallback(async (id: number) => {
    if (!window.confirm('Move this report to the Build Ideas backlog (admin) and mark it resolved?')) return
    setMovingId(id)
    try {
      const res = await api(`/api/admin/build-ideas/from-report/${id}?resolve=true`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      window.dispatchEvent(new CustomEvent('titan:reports-changed'))
      await loadReports()
    } catch {
      await loadReports()
    } finally {
      setMovingId(null)
    }
  }, [loadReports])

  useEffect(() => { if (open && view === 'list') loadReports() }, [open, view, loadReports])

  // The header alert badge opens this panel on Record, not on the queue.
  //
  // It used to jump straight to Reports, which is why opening the panel from
  // the header landed on an empty "No reports yet" list instead of the thing
  // the panel is for. Recording is the common case; the Reports tab is one
  // click away for an admin who wants it.
  useEffect(() => {
    const openPanel = () => { setOpen(true); setView('record') }
    window.addEventListener('titan:open-reports', openPanel)
    return () => window.removeEventListener('titan:open-reports', openPanel)
  }, [])

  // Cleanup on unmount
  useEffect(() => () => teardown(), [])

  // Enumerate mics when the panel opens; refresh on device hot-plug; release the
  // test stream when it closes.
  useEffect(() => {
    if (!open) { stopTestMic(); return }
    enumerateMics()
    const onChange = () => enumerateMics()
    navigator.mediaDevices?.addEventListener?.('devicechange', onChange)
    return () => navigator.mediaDevices?.removeEventListener?.('devicechange', onChange)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, enumerateMics])

  const fmt = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`
  const statusColor: Record<string, string> = {
    open: 'bg-red-500/20 text-red-300', in_progress: 'bg-yellow-500/20 text-yellow-300',
    resolved: 'bg-green-500/20 text-green-300', closed: 'bg-slate-500/20 text-slate-300',
  }

  // ── Floating launcher (closed state) ──
  if (!open) {
    return (
      <button
        id="titan-error-reporter"
        onClick={() => { setOpen(true); setView('record') }}
        title="Report an issue"
        className="fixed bottom-5 right-5 z-[99999] flex items-center gap-2 px-4 py-2.5 bg-red-600 hover:bg-red-700 text-white font-bold text-sm rounded-full shadow-2xl"
      >
        <span className="text-lg leading-none">&#9888;</span> Report Issue
      </button>
    )
  }

  const micPillColor = micStatus.tone === 'err' ? 'bg-red-500/20 text-red-300 border-red-500/40'
    : micStatus.tone === 'warn' ? 'bg-yellow-500/20 text-yellow-200 border-yellow-500/40'
    : 'bg-green-500/15 text-green-300 border-green-500/30'

  return (
    <div
      id="titan-error-reporter"
      className="fixed z-[99999] w-[360px] bg-slate-900 border-2 border-red-500 rounded-2xl shadow-2xl text-white"
      style={{ left: pos.x, top: pos.y, userSelect: 'none', fontFamily: 'system-ui, sans-serif' }}
    >
      <div className="p-4">
        {/* Header / drag handle */}
        <div className="flex items-center justify-between mb-3 cursor-grab active:cursor-grabbing" onMouseDown={onDragStart}>
          <div className="flex items-center gap-2">
            <span className="text-red-500 text-lg">&#9888;</span>
            <span className="font-bold text-sm text-red-400">Issue Recorder</span>
            {state === 'recording' && (
              <span className="flex items-center gap-1 text-[10px] bg-red-500/20 text-red-300 px-2 py-0.5 rounded-full">
                <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" /> REC {fmt(elapsed)}
              </span>
            )}
          </div>
          <button onClick={() => { if (state === 'recording' || state === 'paused') return; setOpen(false) }}
            className={`text-lg leading-none ${state === 'recording' || state === 'paused' ? 'text-slate-700 cursor-not-allowed' : 'text-slate-500 hover:text-slate-200'}`}>&times;</button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-3 text-xs">
          <button onClick={() => { setView('record'); if (state === 'saved') resetForNew() }}
            className={`flex-1 py-1.5 rounded-lg font-semibold ${view === 'record' ? 'bg-red-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'}`}>Record</button>
          {canViewList && (
            <button onClick={() => setView('list')} disabled={state === 'recording' || state === 'paused'}
              className={`flex-1 py-1.5 rounded-lg font-semibold ${view === 'list' ? 'bg-red-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white disabled:opacity-40'}`}>Reports</button>
          )}
        </div>

        {view === 'record' ? (
          <>
            {state === 'idle' && (
              <div className="bg-slate-800 border-l-4 border-red-500 rounded-lg p-3 mb-3 text-xs text-slate-300 leading-relaxed">
                Navigate to the problem, click <b>Start Recording</b>, and choose <b>Window</b> or <b>Entire Screen</b> to share (so your mouse pointer is captured — a Chrome <i>Tab</i> share hides the cursor). Then describe what's wrong (expected vs actual). Your screen, cursor, voice, and clicks are all recorded.
              </div>
            )}

            {state === 'idle' && (
              <div className="flex items-center gap-2 mb-3 text-xs">
                <span className="text-slate-400">Severity</span>
                <select value={severity} onChange={e => setSeverity(e.target.value as any)}
                  className="flex-1 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white">
                  <option value="low">Low</option>
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            )}

            {/* Mic picker + Test — confirm the right device works BEFORE recording */}
            {state === 'idle' && (
              <div className="mb-3 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-slate-400">Mic</span>
                  <select value={selectedMicId}
                    onChange={e => { setSelectedMicId(e.target.value); if (testing) stopTestMic() }}
                    className="flex-1 min-w-0 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white">
                    <option value="">System default</option>
                    {audioDevices.map(d => (
                      <option key={d.deviceId} value={d.deviceId}>
                        {d.label || `Microphone ${d.deviceId.slice(0, 6)}`}
                      </option>
                    ))}
                  </select>
                  <button onClick={testing ? stopTestMic : startTestMic}
                    className={`px-2.5 py-1 rounded font-semibold whitespace-nowrap ${testing ? 'bg-slate-600 text-white hover:bg-slate-500' : 'bg-slate-700 text-slate-200 hover:bg-slate-600'}`}>
                    {testing ? 'Stop' : 'Test mic'}
                  </button>
                </div>
                {testing && (
                  <div className="mt-2 bg-slate-800/60 border border-slate-700 rounded-lg p-2.5">
                    <LevelMeter level={micLevel} active={testing} />
                    <div className={`mt-1.5 text-[11px] font-semibold flex items-center gap-1.5 ${micConfirmed ? 'text-green-400' : 'text-slate-400'}`}>
                      {micConfirmed
                        ? <><span>✓</span> Microphone is working</>
                        : <><span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" /> Speak now — the bars should jump</>}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Controls */}
            <div className="flex gap-2 mb-3">
              {state === 'idle' && (
                <button onClick={startRecording}
                  className="flex-1 py-2.5 bg-red-500 hover:bg-red-600 text-white font-bold text-sm rounded-lg">Start Recording</button>
              )}
              {state === 'recording' && (
                <>
                  <button onClick={togglePause} className="flex-1 py-2.5 bg-yellow-500 hover:bg-yellow-600 text-black font-bold text-sm rounded-lg">Pause</button>
                  <button onClick={stopAndSave} className="py-2.5 px-4 bg-green-500 hover:bg-green-600 text-white font-bold text-sm rounded-lg">Done</button>
                </>
              )}
              {state === 'paused' && (
                <>
                  <button onClick={togglePause} className="flex-1 py-2.5 bg-red-500 hover:bg-red-600 text-white font-bold text-sm rounded-lg">Resume</button>
                  <button onClick={stopAndSave} className="py-2.5 px-4 bg-green-500 hover:bg-green-600 text-white font-bold text-sm rounded-lg">Done</button>
                </>
              )}
              {state === 'saving' && <div className="flex-1 py-2.5 text-center text-sm text-slate-400">Saving…</div>}
              {state === 'saved' && (
                <div className="flex-1 text-center py-1">
                  <div className="mx-auto mb-2 w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center text-green-400 text-2xl leading-none">&#10003;</div>
                  <div className="text-green-400 font-bold text-sm">Thank you — your issue has been sent in!</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">
                    {savedId ? <>Saved as report #{savedId}. The team can review your recording.</> : 'Your report was saved.'}
                  </div>
                  {saveNote && <div className="text-[11px] text-yellow-300 mt-1">{saveNote}</div>}
                  <div className="flex flex-wrap gap-2 justify-center mt-3">
                    <button onClick={resetForNew} className="text-xs px-3 py-1.5 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-lg">Report another issue</button>
                    {canViewList && (
                      <button onClick={() => { setView('list') }} className="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg">View reports</button>
                    )}
                    <button onClick={() => { resetForNew(); setOpen(false) }} className="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg">Close</button>
                  </div>
                </div>
              )}
            </div>

            {/* Mic-status pill — always visible while recording/paused */}
            {(state === 'recording' || state === 'paused') && micStatus.text && (
              <div className={`text-[11px] border rounded-lg px-2.5 py-1.5 mb-2 leading-snug ${micPillColor}`}>
                {micStatus.text}
              </div>
            )}

            {/* Live mic level — so silence is visible instead of falsely "ok" */}
            {state === 'recording' && (
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] text-slate-500 whitespace-nowrap">mic</span>
                <div className="flex-1"><LevelMeter level={micLevel} active={true} /></div>
              </div>
            )}
            {state === 'idle' && micStatus.tone === 'err' && micStatus.text && (
              <div className="text-[11px] border rounded-lg px-2.5 py-1.5 mb-2 leading-snug bg-red-500/20 text-red-300 border-red-500/40">
                {micStatus.text}
              </div>
            )}

            {/* Interim transcript */}
            {(state === 'recording' || state === 'paused') && interim && (
              <div className="text-xs text-green-400/60 truncate mb-1">…{interim}</div>
            )}

            {/* Stats */}
            {state !== 'idle' && (
              <div className="flex justify-between text-[11px] text-slate-500 mt-1">
                <span>Speech {speech.length} · Clicks {clicks.length} · Pages {pages.length}</span>
                <span>{fmt(elapsed)}</span>
              </div>
            )}
          </>
        ) : (
          // ── Reports list ──
          <div className="max-h-[320px] overflow-y-auto -mx-1 px-1">
            {reportsLoading ? (
              <div className="text-center text-slate-500 text-xs py-6">Loading…</div>
            ) : reports.length === 0 ? (
              <div className="text-center text-slate-500 text-xs py-6">No reports yet.</div>
            ) : reports.map(r => (
              <div key={r.id} className="bg-slate-800 rounded-lg p-2.5 mb-2 text-xs">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="font-bold text-slate-200">#{r.id}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wide ${statusColor[r.status] || 'bg-slate-600 text-white'}`}>{r.status.replace('_', ' ')}</span>
                </div>
                <div className="text-slate-300 leading-snug mb-1 line-clamp-2">{r.title}</div>
                <div className="flex items-center justify-between text-[10px] text-slate-500 mb-2">
                  <span>👤 {r.reported_by || 'unknown'} · {new Date(r.reported_at).toLocaleString()}</span>
                  {r.video_path && <a href={r.video_path} target="_blank" rel="noreferrer" className="text-red-400 hover:underline">video ▶</a>}
                </div>
                {r.status === 'resolved' || r.status === 'closed' ? (
                  <button
                    onClick={() => setReportStatus(r.id, 'open')}
                    disabled={resolvingId === r.id}
                    className="w-full py-1 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-200 font-semibold disabled:opacity-50"
                  >
                    {resolvingId === r.id ? 'Saving…' : '↩ Reopen'}
                  </button>
                ) : (
                  <button
                    onClick={() => setReportStatus(r.id, 'resolved')}
                    disabled={resolvingId === r.id}
                    className="w-full py-1 rounded-md bg-green-600 hover:bg-green-500 text-white font-semibold disabled:opacity-50"
                  >
                    {resolvingId === r.id ? 'Saving…' : '✓ Mark resolved'}
                  </button>
                )}
                <button
                  onClick={() => moveToIdeas(r.id)}
                  disabled={movingId === r.id}
                  title="Park this as a future build idea (admin backlog) and resolve it"
                  className="mt-1 w-full py-1 rounded-md bg-slate-700/60 hover:bg-indigo-600 text-slate-200 hover:text-white text-[11px] font-semibold disabled:opacity-50"
                >
                  {movingId === r.id ? 'Moving…' : '💡 Move to Build Ideas'}
                </button>
              </div>
            ))}
            <button onClick={loadReports} className="w-full text-[11px] text-slate-400 hover:text-white py-1">↻ Refresh</button>
          </div>
        )}
      </div>
    </div>
  )
}
