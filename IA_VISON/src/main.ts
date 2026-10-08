import { YoloV8Detector, type PersonDetection } from './yoloDetector'
import './style.css'

const app = document.querySelector<HTMLDivElement>('#app')!

app.innerHTML = `
  <main class="console">
    <header class="topbar">
      <a class="brand" href="#" aria-label="Présence, accueil">
        <span class="brand-mark" aria-hidden="true">P</span>
        <span>SENTINEL-X <span class="brand-divider">/</span> EDGE</span>
      </a>
      <nav class="app-nav" aria-label="Vues de l’application">
        <button class="app-nav-button is-active" type="button" data-view="presence" aria-current="page">Vision</button>
        <button class="app-nav-button" type="button" data-view="sentinel">Capteurs MQTT</button>
      </nav>
      <div class="topbar-note"><span class="privacy-dot"></span> Analyse locale · aucune vidéo envoyée</div>
    </header>

    <section class="workspace" id="presence-view" aria-labelledby="page-title">
      <div class="intro">
        <div>
          <p class="eyebrow">VISION PAR ORDINATEUR <span>·</span> YOLOV8N ONNX</p>
          <h1 id="page-title">Détection de<br /><em>personnes.</em></h1>
        </div>
        <div class="session-state" aria-live="polite">
          <span class="state-light" id="state-light"></span>
          <span id="status-text">Prêt à démarrer</span>
        </div>
      </div>

      <div class="layout">
        <section class="view-column" aria-label="Vue caméra">
          <div class="view-head">
            <span class="view-label"><span class="view-dot"></span> FLUX CAMÉRA</span>
            <span class="view-resolution" id="resolution-label">EN ATTENTE</span>
          </div>
          <div class="camera-stage" id="camera-stage">
            <video id="camera" autoplay muted playsinline></video>
            <canvas id="overlay" aria-hidden="true"></canvas>
            <div class="empty-state" id="empty-state">
              <div class="target-icon" aria-hidden="true"><span></span></div>
              <p id="empty-title">Aucun flux actif</p>
              <span id="empty-description">Démarrez la caméra pour lancer l’analyse.</span>
            </div>
            <div class="stage-corner corner-tl"></div>
            <div class="stage-corner corner-tr"></div>
            <div class="stage-corner corner-bl"></div>
            <div class="stage-corner corner-br"></div>
            <div class="stage-counter" id="stage-counter" hidden><span id="stage-count">0</span> PERSONNE(S)</div>
          </div>
            <div class="presence-alert" id="presence-alert" role="alert" aria-live="assertive" hidden>
              <p id="presence-alert-message"></p>
              <img id="presence-alert-image" alt="Capture de la personne détectée" hidden />
            </div>
          <div class="view-foot">
            <span><span class="privacy-dot"></span> Traitement dans le navigateur</span>
            <span id="last-scan">Aucune analyse</span>
          </div>
        </section>

        <aside class="control-panel" aria-label="Commandes et résultats">
          <div class="mode-readout" aria-live="polite">
            <span class="mode-indicator" id="mode-indicator"></span>
            <span>MODE <strong id="mode-label">SURVEILLANCE</strong></span>
          </div>
          <form class="mode-code-form" id="mode-code-form">
            <label for="mode-code">Code de changement de mode</label>
            <div class="mode-code-row">
              <input id="mode-code" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="4" autocomplete="off" aria-describedby="mode-code-feedback" />
              <button type="submit">Valider</button>
            </div>
            <p id="mode-code-feedback" role="status" aria-live="polite"></p>
          </form>
          <button class="mode-code-toggle" id="mode-code-toggle" type="button" hidden>Changer le mode</button>
          <button class="start-button" id="start-button" type="button"><span>Démarrer la caméra</span><span class="button-arrow" aria-hidden="true">↗</span></button>
          <p class="error-message" id="error-message" role="alert" hidden></p>

          <div class="count-block">
            <p class="eyebrow">PERSONNES DÉTECTÉES</p>
            <div class="count-line"><strong id="person-count">0</strong><span>dans le champ</span></div>
            <div class="count-rule"><span id="count-rule-fill"></span></div>
          </div>

          <div class="control-group">
            <label for="camera-select">Source vidéo</label>
            <select id="camera-select" disabled>
              <option value="">Caméra par défaut</option>
            </select>
          </div>

          <div class="control-group">
            <div class="label-row"><label for="confidence">Seuil de confiance</label><output id="confidence-value" for="confidence">45 %</output></div>
            <input id="confidence" type="range" min="25" max="85" step="5" value="45" />
            <div class="range-ends"><span>Plus sensible</span><span>Plus strict</span></div>
          </div>

          <div class="control-group">
            <label for="scan-rate">Fréquence d’analyse</label>
            <select id="scan-rate">
              <option value="400">Rapide · 2,5 fois/s</option>
              <option value="700" selected>Équilibrée · 1,4 fois/s</option>
              <option value="1200">Économie CPU · 0,8 fois/s</option>
            </select>
          </div>

          <div class="model-note">
            <span class="model-indicator"></span>
            <div><strong>YOLOv8n · ONNX Runtime Web</strong><span>Détection locale dans le navigateur.</span></div>
          </div>
        </aside>
      </div>
    </section>

    <section id="sentinel-view" hidden aria-label="Supervision Sentinel-X"></section>

    <footer class="footer"><span>PRÉSENCE <span>·</span> PROTOTYPE WEBCAM</span><span>INFÉRENCE CÔTÉ CLIENT</span></footer>
  </main>
`

const viewButtons = [...document.querySelectorAll<HTMLButtonElement>('.app-nav-button')]
const presenceView = document.querySelector<HTMLElement>('#presence-view')!
const sentinelView = document.querySelector<HTMLElement>('#sentinel-view')!
let sentinelDashboardMounted = false
viewButtons.forEach((button) => {
  button.addEventListener('click', () => {
    const showSentinel = button.dataset.view === 'sentinel'
    presenceView.hidden = showSentinel
    sentinelView.hidden = !showSentinel
    viewButtons.forEach((item) => {
      const active = item === button
      item.classList.toggle('is-active', active)
      if (active) item.setAttribute('aria-current', 'page')
      else item.removeAttribute('aria-current')
    })
    if (showSentinel && !sentinelDashboardMounted) {
      sentinelView.textContent = 'Chargement du tableau MQTT…'
      void import('./sentinelDashboard').then(({ mountSentinelDashboard }) => {
        mountSentinelDashboard(sentinelView)
        sentinelDashboardMounted = true
      }).catch(() => {
        sentinelView.textContent = 'Impossible de charger le tableau MQTT. Recharge la page pour réessayer.'
      })
    }
  })
})

const video = document.querySelector<HTMLVideoElement>('#camera')!
const canvas = document.querySelector<HTMLCanvasElement>('#overlay')!
const context = canvas.getContext('2d')!
const cameraSelect = document.querySelector<HTMLSelectElement>('#camera-select')!
const startButton = document.querySelector<HTMLButtonElement>('#start-button')!
const confidenceInput = document.querySelector<HTMLInputElement>('#confidence')!
const scanRateSelect = document.querySelector<HTMLSelectElement>('#scan-rate')!
const statusText = document.querySelector<HTMLSpanElement>('#status-text')!
const stateLight = document.querySelector<HTMLSpanElement>('#state-light')!
const errorMessage = document.querySelector<HTMLParagraphElement>('#error-message')!
const emptyState = document.querySelector<HTMLDivElement>('#empty-state')!
const stageCounter = document.querySelector<HTMLDivElement>('#stage-counter')!
const presenceAlert = document.querySelector<HTMLDivElement>('#presence-alert')!
const presenceAlertMessage = document.querySelector<HTMLParagraphElement>('#presence-alert-message')!
const presenceAlertImage = document.querySelector<HTMLImageElement>('#presence-alert-image')!
const modeLabel = document.querySelector<HTMLElement>('#mode-label')!
const modeIndicator = document.querySelector<HTMLElement>('#mode-indicator')!
const modeCodeForm = document.querySelector<HTMLFormElement>('#mode-code-form')!
const modeCodeInput = document.querySelector<HTMLInputElement>('#mode-code')!
const modeCodeFeedback = document.querySelector<HTMLParagraphElement>('#mode-code-feedback')!
const modeCodeToggle = document.querySelector<HTMLButtonElement>('#mode-code-toggle')!

type Mode = 'neutral' | 'surveillance'
type PersonPrediction = PersonDetection

declare global {
  interface Window {
    presenceAlarm: {
      switchMode: (code: string) => boolean
      getMode: () => Mode
    }
  }
}

const MODE_ACCESS_CODE = '0000'
const ALERT_CONFIDENCE = 0.75
const ALERT_REPEAT_MS = 15_000
const ALARM_ESCALATION_MS = 120_000

let model: YoloV8Detector | null = null
let stream: MediaStream | null = null
let active = false
let mode: Mode = 'surveillance'
let latestPerson: PersonPrediction | null = null
let lastAlarmImage: Blob | null = null
let alarmStartedAt = 0
let sessionId = 0
let scanTimeout = 0
let repeatAlertInterval = 0
let escalationTimeout = 0
let previewUrl = ''

function setStatus(message: string, state: 'ready' | 'busy' | 'live' | 'error') {
  statusText.textContent = message
  stateLight.dataset.state = state
}

function setCount(count: number) {
  document.querySelector('#person-count')!.textContent = String(count)
  document.querySelector('#stage-count')!.textContent = String(count)
  document.querySelector('#count-rule-fill')!.setAttribute('style', `--count-width: ${Math.min(count * 14, 100)}%`)
  stageCounter.hidden = count === 0
}

function clearDetections() {
  context.clearRect(0, 0, canvas.width, canvas.height)
  setCount(0)
  clearAlarm()
}

function updateModeReadout() {
  modeLabel.textContent = mode === 'surveillance' ? 'SURVEILLANCE' : 'NEUTRE'
  modeIndicator.dataset.mode = mode
}

function clearAlarm() {
  window.clearInterval(repeatAlertInterval)
  window.clearTimeout(escalationTimeout)
  repeatAlertInterval = 0
  escalationTimeout = 0
  alarmStartedAt = 0
  latestPerson = null
  lastAlarmImage = null
  presenceAlert.hidden = true
  presenceAlertMessage.textContent = ''
  presenceAlertImage.hidden = true
  presenceAlertImage.removeAttribute('src')
  if (previewUrl) URL.revokeObjectURL(previewUrl)
  previewUrl = ''
}

function setMode(nextMode: Mode) {
  if (mode === nextMode) return
  mode = nextMode
  updateModeReadout()

  if (mode === 'neutral') {
    clearAlarm()
    return
  }

  if (active && latestPerson) startAlarm(latestPerson)
}

function switchModeWithCode(code: string): boolean {
  if (code !== MODE_ACCESS_CODE) return false
  setMode(mode === 'surveillance' ? 'neutral' : 'surveillance')
  return true
}

function capturePerson(person: PersonPrediction): Promise<Blob | null> {
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return Promise.resolve(null)

  const [x, y, width, height] = person.bbox
  const padding = Math.max(width, height) * 0.12
  const left = Math.max(0, x - padding)
  const top = Math.max(0, y - padding)
  const right = Math.min(video.videoWidth, x + width + padding)
  const bottom = Math.min(video.videoHeight, y + height + padding)
  const snapshot = document.createElement('canvas')
  snapshot.width = Math.max(1, Math.round(right - left))
  snapshot.height = Math.max(1, Math.round(bottom - top))
  snapshot.getContext('2d')!.drawImage(video, left, top, right - left, bottom - top, 0, 0, snapshot.width, snapshot.height)
  return new Promise((resolve) => snapshot.toBlob(resolve, 'image/jpeg', 0.88))
}

async function sendAlarmMessage(escalated = false) {
  if (!alarmStartedAt || mode !== 'surveillance') return

  const alarmId = alarmStartedAt
  const captured = latestPerson ? await capturePerson(latestPerson) : null
  if (!alarmStartedAt || alarmStartedAt !== alarmId || mode !== 'surveillance') return
  if (captured) lastAlarmImage = captured
  const image = captured ?? lastAlarmImage
  const message = escalated
    ? 'Alarme non neutralisée après 2 minutes. La personne détectée est considérée comme non autorisée.'
    : 'Présence détectée avec une confiance supérieure à 75 %. Neutralisez l’alarme via le code si la personne est autorisée.'

  presenceAlertMessage.textContent = message
  presenceAlert.hidden = false

  if (image) {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    previewUrl = URL.createObjectURL(image)
    presenceAlertImage.src = previewUrl
    presenceAlertImage.hidden = false
  }

  if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    const notificationUrl = image ? URL.createObjectURL(image) : undefined
    const notification = new Notification(escalated ? 'Alarme non neutralisée' : 'Présence détectée', {
      body: message,
      icon: notificationUrl,
    })
    notification.addEventListener('close', () => {
      if (notificationUrl) URL.revokeObjectURL(notificationUrl)
    }, { once: true })
  }
}

function startAlarm(person: PersonPrediction) {
  if (mode !== 'surveillance' || alarmStartedAt) return

  latestPerson = person
  alarmStartedAt = Date.now()
  void sendAlarmMessage()
  repeatAlertInterval = window.setInterval(() => {
    if (latestPerson) void sendAlarmMessage()
  }, ALERT_REPEAT_MS)
  escalationTimeout = window.setTimeout(() => void sendAlarmMessage(true), ALARM_ESCALATION_MS)
}

async function refreshCameraList() {
  const selectedId = cameraSelect.value
  const devices = await navigator.mediaDevices.enumerateDevices()
  const cameras = devices.filter((device) => device.kind === 'videoinput')
  cameraSelect.replaceChildren(new Option('Caméra par défaut', ''))

  cameras.forEach((camera, index) => {
    cameraSelect.add(new Option(camera.label || `Caméra ${index + 1}`, camera.deviceId))
  })

  cameraSelect.disabled = cameras.length < 2
  if (cameras.some((camera) => camera.deviceId === selectedId)) cameraSelect.value = selectedId
}

function drawDetections(detections: PersonDetection[]) {
  context.clearRect(0, 0, canvas.width, canvas.height)
  const people = detections.filter((detection) => detection.class === 'person')
  context.lineWidth = Math.max(2, canvas.width / 360)
  context.font = `600 ${Math.max(13, canvas.width / 42)}px ui-sans-serif, sans-serif`
  context.textBaseline = 'top'

  people.forEach((person, index) => {
    const [x, y, width, height] = person.bbox
    const hue = index % 2 === 0 ? '#d9f36a' : '#ff805c'
    context.strokeStyle = hue
    context.fillStyle = hue
    context.strokeRect(x, y, width, height)
    const caption = `PERSONNE ${Math.round(person.score * 100)}%`
    const captionWidth = context.measureText(caption).width + 16
    const captionY = Math.max(0, y - 29)
    context.fillRect(x, captionY, captionWidth, 25)
    context.fillStyle = '#171914'
    context.fillText(caption, x + 8, captionY + 5)
  })

  setCount(people.length)
  latestPerson = people
    .filter((person) => person.score > ALERT_CONFIDENCE)
    .sort((first, second) => second.score - first.score)[0] ?? null
  if (mode === 'surveillance' && latestPerson && !alarmStartedAt) startAlarm(latestPerson)
  document.querySelector('#last-scan')!.textContent = `Dernière analyse · ${new Date().toLocaleTimeString('fr-FR')}`
}

async function scan(session: number) {
  if (!active || !model || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return

  try {
    const predictions = await model.detect(video, Number(confidenceInput.value) / 100)
    if (!active || session !== sessionId) return
    drawDetections(predictions)
    scanTimeout = window.setTimeout(() => void scan(session), Number(scanRateSelect.value))
  } catch (error) {
    if (session === sessionId) {
      errorMessage.textContent = error instanceof Error ? error.message : 'L’analyse de l’image a échoué.'
      errorMessage.hidden = false
      stopCamera()
    }
  }
}

async function startCamera() {
  if (active) return
  if (!navigator.mediaDevices?.getUserMedia) {
    errorMessage.textContent = 'Cette page doit être ouverte sur localhost ou en HTTPS pour accéder à la caméra.'
    errorMessage.hidden = false
    setStatus('Caméra indisponible', 'error')
    return
  }

  const session = ++sessionId
  active = true
  modeCodeForm.hidden = true
  modeCodeToggle.hidden = false
  modeCodeToggle.textContent = mode === 'neutral' ? 'Reprendre la surveillance' : 'Changer le mode'
  startButton.disabled = true
  startButton.innerHTML = '<span>Connexion à la caméra…</span><span class="button-arrow" aria-hidden="true">…</span>'
  errorMessage.hidden = true
  setStatus('Connexion à la caméra', 'busy')
  document.querySelector('#empty-title')!.textContent = 'Connexion en cours'
  document.querySelector('#empty-description')!.textContent = 'Autorisez l’accès à la caméra dans votre navigateur.'
  emptyState.hidden = false

  try {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      await Notification.requestPermission()
    }

    const deviceId = cameraSelect.value
    const nextStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: deviceId ? { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } } : {
        facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 },
      },
    })
    if (session !== sessionId) {
      nextStream.getTracks().forEach((track) => track.stop())
      return
    }

    stream = nextStream
    video.srcObject = stream
    await video.play()
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    document.querySelector('#resolution-label')!.textContent = `${video.videoWidth} × ${video.videoHeight}`
    emptyState.hidden = true
    await refreshCameraList()

    setStatus(model ? 'Analyse en direct' : 'Chargement du modèle', 'busy')
    if (!model) {
      startButton.innerHTML = '<span>Chargement du modèle…</span><span class="button-arrow" aria-hidden="true">…</span>'
      document.querySelector('#empty-title')!.textContent = 'Préparation de l’analyse'
      document.querySelector('#empty-description')!.textContent = 'Premier lancement : téléchargement du modèle de détection.'
      model = await YoloV8Detector.load(`${import.meta.env.BASE_URL}models/yolov8n.onnx`)
    }
    if (!active || session !== sessionId) return

    startButton.disabled = false
    startButton.innerHTML = '<span>Arrêter la détection</span><span class="button-arrow" aria-hidden="true">■</span>'
    startButton.classList.add('is-live')
    setStatus('Analyse en direct', 'live')
    void scan(session)
  } catch (error) {
    if (session !== sessionId) return
    const message = error instanceof DOMException && error.name === 'NotAllowedError'
      ? 'Accès refusé. Autorisez la caméra dans les réglages du navigateur puis réessayez.'
      : error instanceof DOMException && error.name === 'NotFoundError'
        ? 'Aucune webcam détectée. Branchez une caméra puis réessayez.'
        : error instanceof Error ? error.message : 'Impossible de démarrer la caméra.'
    errorMessage.textContent = message
    errorMessage.hidden = false
    stopCamera()
    setStatus('Démarrage impossible', 'error')
  }
}

function stopCamera() {
  sessionId += 1
  active = false
  modeCodeForm.hidden = false
  modeCodeToggle.hidden = true
  window.clearTimeout(scanTimeout)
  stream?.getTracks().forEach((track) => track.stop())
  stream = null
  video.srcObject = null
  clearDetections()
  emptyState.hidden = false
  document.querySelector('#empty-title')!.textContent = 'Aucun flux actif'
  document.querySelector('#empty-description')!.textContent = 'Démarrez la caméra pour lancer l’analyse.'
  document.querySelector('#resolution-label')!.textContent = 'EN ATTENTE'
  document.querySelector('#last-scan')!.textContent = 'Aucune analyse'
  startButton.disabled = false
  startButton.classList.remove('is-live')
  startButton.innerHTML = '<span>Démarrer la caméra</span><span class="button-arrow" aria-hidden="true">↗</span>'
  setStatus('Prêt à démarrer', 'ready')
  void refreshCameraList()
}

window.presenceAlarm = {
  switchMode: switchModeWithCode,
  getMode: () => mode,
}
updateModeReadout()

modeCodeForm.addEventListener('submit', (event) => {
  event.preventDefault()
  const switched = switchModeWithCode(modeCodeInput.value)
  modeCodeFeedback.textContent = switched
    ? `Mode ${mode === 'neutral' ? 'neutre' : 'surveillance'} activé.`
    : 'Code incorrect.'
  modeCodeInput.value = ''
  if (switched && active) {
    modeCodeForm.hidden = true
    modeCodeToggle.hidden = false
    modeCodeToggle.textContent = mode === 'neutral' ? 'Reprendre la surveillance' : 'Changer le mode'
  }
})

modeCodeToggle.addEventListener('click', () => {
  modeCodeForm.hidden = false
  modeCodeToggle.hidden = true
  modeCodeInput.focus()
})

startButton.addEventListener('click', () => {
  if (active) stopCamera()
  else void startCamera()
})

cameraSelect.addEventListener('change', () => {
  if (active) {
    stopCamera()
    void startCamera()
  }
})

confidenceInput.addEventListener('input', () => {
  document.querySelector('#confidence-value')!.textContent = `${confidenceInput.value} %`
})

void refreshCameraList()
