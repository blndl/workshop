import mqtt, { type MqttClient } from 'mqtt'

type SensorPayload = {
  device_id: string
  timestamp: string
  temperature: number
  humidity: number
  gas: number
  motion: boolean
}

type AlertPayload = {
  device_id: string
  timestamp: string
  event?: 'triggered' | 'updated' | 'resolved'
  active: boolean
  alerts: string[]
  details?: Array<{
    code: string
    sensor: string
    severity: 'warning' | 'critical'
    message: string
    value: number
    condition: string
    threshold: number
  }>
}

type StatusPayload = {
  device_id: string
  timestamp: string
  status: 'online' | 'offline'
  wifi: boolean
  mqtt: boolean
}

type MetricKey = 'temperature' | 'humidity' | 'gas'
type IncomingPayload = SensorPayload | AlertPayload | StatusPayload | Record<string, unknown>

const dashboardMarkup = `
  <div class="sentinel-console">
    <section class="sentinel-workspace" aria-labelledby="sentinel-title">
      <header class="sentinel-intro">
        <div>
          <p class="eyebrow">EDGE / MQTT <span>·</span> TÉLÉMÉTRIE EN DIRECT</p>
          <h1 id="sentinel-title">État des <em>capteurs.</em></h1>
        </div>
        <div class="broker-state" id="broker-state" data-state="offline" aria-live="polite">
          <span class="broker-light"></span>
          <span id="broker-state-label">BROKER DÉCONNECTÉ</span>
        </div>
      </header>

      <section class="incident-banner" id="incident-banner" data-active="false" aria-live="polite" aria-atomic="true">
        <span class="incident-symbol" aria-hidden="true"><span></span></span>
        <div class="incident-copy"><span class="incident-kicker" id="incident-kicker">SURVEILLANCE ACTIVE · ÉTAT STABLE</span><strong id="incident-title">Aucune alerte en cours</strong><span id="incident-detail">Les capteurs transmettent leur état. Les seuils d’alerte sont surveillés en continu.</span></div>
        <div class="incident-side"><span class="incident-count" id="incident-count">0</span><span>ALERTE(S)</span></div>
      </section>

      <section class="connection-bar" aria-label="Connexion au broker MQTT">
        <form id="mqtt-connect-form" class="broker-form">
          <label class="broker-field broker-host"><span>Hôte du broker</span><input id="mqtt-host" value="localhost" autocomplete="url" /></label>
          <label class="broker-field broker-port"><span>Port WebSocket</span><input id="mqtt-port" type="number" min="1" max="65535" value="9001" inputmode="numeric" /></label>
          <label class="broker-field broker-device"><span>Appareil</span><input id="mqtt-device" value="ESP8266-001" /></label>
          <button class="connect-button" id="mqtt-connect-button" type="submit">Connecter <span aria-hidden="true">↗</span></button>
          <p class="connection-feedback" id="mqtt-feedback" role="status" aria-live="polite">Connecte-toi au broker pour recevoir les mesures réelles.</p>
        </form>
        <div class="connection-meta"><span id="device-status">Appareil · état inconnu</span><span id="last-received">Aucune donnée reçue</span></div>
      </section>

      <section class="sensor-section" aria-labelledby="sensor-section-title">
        <div class="section-heading">
          <div><p class="eyebrow">LECTURES COURANTES</p><h2 id="sensor-section-title">Télémétrie</h2></div>
          <span class="sampling-note"><span class="privacy-dot"></span> 1 mesure / seconde par défaut</span>
        </div>

        <div class="sensor-grid">
          <article class="sensor-panel dht-panel">
            <div class="sensor-panel-head"><div><span class="sensor-index">01</span><span class="sensor-kind">DHT22</span></div><span class="sensor-live-tag" id="dht-state">EN ATTENTE</span></div>
            <div class="dht-readings">
              <div class="metric-block"><span class="metric-name">Température</span><div class="metric-value"><strong id="temperature-value">--.-</strong><span>°C</span></div><svg class="sparkline" viewBox="0 0 180 36" preserveAspectRatio="none" aria-label="Historique température"><polyline id="temperature-trend" points=""></polyline></svg></div>
              <div class="metric-block"><span class="metric-name">Humidité</span><div class="metric-value"><strong id="humidity-value">--.-</strong><span>%</span></div><svg class="sparkline sparkline-coral" viewBox="0 0 180 36" preserveAspectRatio="none" aria-label="Historique humidité"><polyline id="humidity-trend" points=""></polyline></svg></div>
            </div>
            <div class="sensor-panel-foot"><span>Température et humidité ambiantes</span><span id="dht-time">--:--:--</span></div>
          </article>

          <article class="sensor-panel gas-panel">
            <div class="sensor-panel-head"><div><span class="sensor-index">02</span><span class="sensor-kind">MQ-2</span></div><span class="sensor-live-tag" id="gas-state">EN ATTENTE</span></div>
            <div class="metric-block gas-metric"><span class="metric-name">Gaz · valeur normalisée</span><div class="metric-value"><strong id="gas-value">0.00</strong><span>/ 1.00</span></div><div class="gas-meter" role="meter" aria-label="Niveau de gaz" aria-valuemin="0" aria-valuemax="1" aria-valuenow="0"><span id="gas-meter-fill"></span><i id="gas-threshold-marker"></i></div><svg class="sparkline" viewBox="0 0 180 36" preserveAspectRatio="none" aria-label="Historique gaz"><polyline id="gas-trend" points=""></polyline></svg></div>
            <div class="sensor-panel-foot"><span>Pré-alerte au seuil configuré</span><span id="gas-time">--:--:--</span></div>
          </article>

          <article class="sensor-panel pir-panel">
            <div class="sensor-panel-head"><div><span class="sensor-index">03</span><span class="sensor-kind">PIR HC-SR501</span></div><span class="sensor-live-tag" id="pir-state">EN ATTENTE</span></div>
            <div class="motion-readout" id="motion-readout" data-motion="unknown"><span class="motion-symbol" aria-hidden="true"><i></i></span><div><strong id="motion-value">--</strong><span>Détection de mouvement</span></div></div>
            <div class="motion-track" aria-hidden="true"><span id="motion-track-fill"></span></div>
            <div class="sensor-panel-foot"><span>Activé par présence détectée</span><span id="pir-time">--:--:--</span></div>
          </article>
        </div>
      </section>

      <div class="sentinel-lower-grid">
        <section class="threshold-panel" aria-labelledby="threshold-title">
          <div class="section-heading compact-heading"><div><p class="eyebrow">RÈGLES D’ÉMISSION</p><h2 id="threshold-title">Quand une alerte part</h2></div><span class="rules-tag">SIMULATEUR C++</span></div>
          <p class="threshold-intro">Un message est envoyé uniquement quand un seuil est franchi ou qu’un mouvement est détecté. Un événement de résolution est envoyé lorsque les mesures reviennent à la normale.</p>
          <div class="threshold-list">
            <div class="threshold-row" id="threshold-gas" data-active="false"><span class="threshold-led"></span><div><strong>Gaz élevé</strong><span>MQ-2 · niveau normalisé</span></div><code>≥ 0.50</code><b class="rule-state">NORMAL</b></div>
            <div class="threshold-row" id="threshold-heat" data-active="false"><span class="threshold-led"></span><div><strong>Surchauffe</strong><span>DHT22 · température</span></div><code>≥ 35 °C</code><b class="rule-state">NORMAL</b></div>
            <div class="threshold-row" id="threshold-humidity-low" data-active="false"><span class="threshold-led"></span><div><strong>Humidité trop basse</strong><span>DHT22 · humidité relative</span></div><code>&lt; 40 %</code><b class="rule-state">NORMAL</b></div>
            <div class="threshold-row" id="threshold-humidity-high" data-active="false"><span class="threshold-led"></span><div><strong>Humidité trop élevée</strong><span>DHT22 · humidité relative</span></div><code>&gt; 60 %</code><b class="rule-state">NORMAL</b></div>
            <div class="threshold-row" id="threshold-motion" data-active="false"><span class="threshold-led"></span><div><strong>Mouvement détecté</strong><span>PIR HC-SR501 · présence</span></div><code>true</code><b class="rule-state">NORMAL</b></div>
          </div>
          <div class="alert-current" id="alert-current" data-active="false" aria-live="polite"><span class="alert-current-mark"></span><span id="alert-current-text">En attente de l’état des alertes</span></div>
        </section>

        <section class="actuator-panel" aria-labelledby="actuator-title">
          <div class="section-heading compact-heading"><div><p class="eyebrow">COMMANDES DISTANTES</p><h2 id="actuator-title">Actionneurs</h2></div><span class="command-topic">/commands</span></div>
          <div class="actuator-state"><div><span class="actuator-label">BUZZER</span><strong id="buzzer-state">INCONNU</strong></div><div><span class="actuator-label">LED</span><strong id="led-state">INCONNUE</strong></div></div>
          <div class="command-grid">
            <button type="button" class="command-button command-alert" data-command="BUZZER_ON" data-duration="5000">Buzzer 5 s <span aria-hidden="true">↗</span></button>
            <button type="button" class="command-button" data-command="BUZZER_OFF">Arrêt buzzer</button>
            <button type="button" class="command-button command-red" data-command="LED_RED">LED rouge</button>
            <button type="button" class="command-button command-green" data-command="LED_GREEN">LED verte</button>
            <button type="button" class="command-button" data-command="LED_OFF">LED éteinte</button>
            <button type="button" class="command-button" data-command="RESET_ALERT">Réinitialiser</button>
          </div>
          <p class="command-feedback" id="command-feedback" role="status" aria-live="polite">Connexion au broker requise pour envoyer une commande.</p>
        </section>
      </div>

      <section class="message-panel" aria-labelledby="message-title">
        <div class="message-panel-head"><div class="section-heading compact-heading"><div><p class="eyebrow">TRAFIC MQTT · JSON BRUT</p><h2 id="message-title">Messages reçus</h2></div><span class="message-count" id="message-count">0</span></div><button class="clear-log-button" id="clear-message-log" type="button" title="Effacer le journal">Effacer</button></div>
        <div class="topic-legend"><span><i class="legend-sensor"></i>/sensors</span><span><i class="legend-status"></i>/status</span><span><i class="legend-alert"></i>/alerts</span><span><i class="legend-command"></i>/commands</span></div>
        <div class="message-log" id="message-log" role="log" aria-live="polite" aria-relevant="additions">
          <div class="log-empty" id="log-empty"><span class="empty-log-mark">{ }</span><span>Les messages MQTT apparaîtront ici après connexion.</span></div>
        </div>
      </section>
    </section>
  </div>
`

const MAX_POINTS = 36
const MAX_MESSAGES = 50

export function mountSentinelDashboard(root: HTMLElement) {
  root.innerHTML = dashboardMarkup

  const $ = <T extends HTMLElement>(selector: string) => root.querySelector<T>(selector)!
  const connectForm = $('#mqtt-connect-form') as HTMLFormElement
  const hostInput = $('#mqtt-host') as HTMLInputElement
  const portInput = $('#mqtt-port') as HTMLInputElement
  const deviceInput = $('#mqtt-device') as HTMLInputElement
  const connectButton = $('#mqtt-connect-button') as HTMLButtonElement
  const state = $('#broker-state')
  const stateLabel = $('#broker-state-label')
  const feedback = $('#mqtt-feedback')
  const messageLog = $('#message-log')
  const logEmpty = $('#log-empty')
  const commandFeedback = $('#command-feedback')
  const samples: Record<MetricKey, number[]> = { temperature: [], humidity: [], gas: [] }
  let client: MqttClient | null = null
  let messageTotal = 0
  let currentDeviceId = deviceInput.value
  let commandTimeout = 0

  const setConnectionState = (next: 'offline' | 'connecting' | 'online', text: string) => {
    state.dataset.state = next
    stateLabel.textContent = text
  }

  const displayTime = (timestamp?: string) => {
    const date = timestamp ? new Date(timestamp) : new Date()
    return Number.isNaN(date.getTime()) ? new Date().toLocaleTimeString('fr-FR') : date.toLocaleTimeString('fr-FR')
  }

  const setSensorTime = (sensor: 'dht' | 'gas' | 'pir', timestamp: string) => {
    const time = displayTime(timestamp)
    $(`#${sensor}-time`).textContent = time
    $('#last-received').textContent = `Dernière mesure · ${time}`
  }

  const updateSparkline = (key: MetricKey, value: number) => {
    const history = samples[key]
    history.push(value)
    if (history.length > MAX_POINTS) history.shift()
    const min = Math.min(...history)
    const max = Math.max(...history)
    const span = max - min || 1
    const points = history.map((point, index) => {
      const x = history.length === 1 ? 180 : index * 180 / (history.length - 1)
      const y = 32 - (point - min) / span * 26
      return `${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
    $(`#${key}-trend`).setAttribute('points', points)
  }

  const appendMessage = (topic: string, payload: IncomingPayload, kind: string) => {
    logEmpty.hidden = true
    messageTotal += 1
    $('#message-count').textContent = String(messageTotal)
    const row = document.createElement('article')
    row.className = `message-entry message-${kind}`
    if (kind === 'alert') {
      const severity = (payload as AlertPayload).details?.some((detail) => detail.severity === 'critical') ? 'critical' : 'warning'
      row.dataset.severity = severity
    }
    const header = document.createElement('div')
    header.className = 'message-entry-head'
    const topicLabel = document.createElement('code')
    topicLabel.textContent = topic
    const timeLabel = document.createElement('time')
    timeLabel.textContent = displayTime(typeof payload.timestamp === 'string' ? payload.timestamp : undefined)
    header.append(topicLabel, timeLabel)
    const body = document.createElement('pre')
    if (kind === 'alert') {
      const alertPayload = payload as AlertPayload
      const details = Array.isArray(alertPayload.details) ? alertPayload.details : []
      const summary = document.createElement('strong')
      summary.className = 'alert-event-summary'
      summary.textContent = alertPayload.event === 'resolved'
        ? 'Résolu · toutes les mesures sont revenues dans les limites.'
        : `${alertPayload.event === 'updated' ? 'Mise à jour' : 'Anomalie détectée'} · ${details.map((detail) => alertLabel(detail.code)).join(' · ')}`
      body.className = 'alert-event-body'
      body.append(summary)
      if (details.length) {
        const detailList = document.createElement('ul')
        detailList.className = 'alert-detail-list'
        details.forEach((detail) => {
          const item = document.createElement('li')
          item.textContent = `${detail.sensor} — ${detail.message}`
          detailList.append(item)
        })
        body.append(detailList)
      }
    } else {
      body.textContent = JSON.stringify(payload, null, 2)
    }
    row.append(header, body)
    messageLog.prepend(row)
    while (messageLog.children.length > MAX_MESSAGES + 1) messageLog.lastElementChild?.remove()
  }

  const updateSensor = (payload: SensorPayload) => {
    if (typeof payload.temperature !== 'number' || typeof payload.humidity !== 'number' ||
        typeof payload.gas !== 'number' || typeof payload.motion !== 'boolean') return

    $('#temperature-value').textContent = payload.temperature.toFixed(1)
    $('#humidity-value').textContent = payload.humidity.toFixed(1)
    $('#gas-value').textContent = payload.gas.toFixed(2)
    updateSparkline('temperature', payload.temperature)
    updateSparkline('humidity', payload.humidity)
    updateSparkline('gas', payload.gas)
    const gasRatio = Math.max(0, Math.min(1, payload.gas))
    $('#gas-meter-fill').setAttribute('style', `--gas-level: ${gasRatio * 100}%`)
    const gasMeter = $('.gas-meter')
    gasMeter.setAttribute('aria-valuenow', payload.gas.toFixed(2))
    $('#motion-readout').setAttribute('data-motion', payload.motion ? 'active' : 'clear')
    $('#motion-value').textContent = payload.motion ? 'MOUVEMENT' : 'AUCUN'
    $('#motion-track-fill').setAttribute('style', `--motion-width: ${payload.motion ? '100%' : '0%'}`)
    $('#dht-state').textContent = 'EN DIRECT'
    $('#gas-state').textContent = 'EN DIRECT'
    $('#pir-state').textContent = 'EN DIRECT'
    setSensorTime('dht', payload.timestamp)
    setSensorTime('gas', payload.timestamp)
    setSensorTime('pir', payload.timestamp)
    setThreshold('#threshold-gas', payload.gas >= 0.5)
    setThreshold('#threshold-heat', payload.temperature >= 35)
    setThreshold('#threshold-humidity-low', payload.humidity < 40)
    setThreshold('#threshold-humidity-high', payload.humidity > 60)
    setThreshold('#threshold-motion', payload.motion)
  }

  const setThreshold = (selector: string, active: boolean) => {
    const row = $(selector)
    row.dataset.active = String(active)
    row.querySelector('.rule-state')!.textContent = active ? 'ALERTE' : 'NORMAL'
  }

  const updateAlerts = (payload: AlertPayload) => {
    const alerts = Array.isArray(payload.alerts) ? payload.alerts : []
    const active = payload.active === true && alerts.length > 0
    $('#alert-current').setAttribute('data-active', String(active))
    const details = Array.isArray(payload.details) ? payload.details : []
    const messages = details.map((detail) => detail.message)
    const highestSeverity = details.some((detail) => detail.severity === 'critical') ? 'critical' : 'warning'
    $('#alert-current-text').textContent = active
      ? messages.join(' ')
      : payload.event === 'resolved' ? 'Incident résolu : toutes les mesures sont revenues dans les limites.' : 'Aucune anomalie détectée.'
    $('#incident-banner').setAttribute('data-active', String(active))
    $('#incident-banner').setAttribute('data-severity', highestSeverity)
    $('#incident-kicker').textContent = active
      ? `${highestSeverity === 'critical' ? 'ALERTE CRITIQUE' : 'ATTENTION REQUISE'} · ${payload.event === 'updated' ? 'ÉTAT MIS À JOUR' : 'ANOMALIE DÉTECTÉE'}`
      : payload.event === 'resolved' ? 'INCIDENT RÉSOLU · MESURES NORMALES' : 'SURVEILLANCE ACTIVE · ÉTAT STABLE'
    $('#incident-count').textContent = String(alerts.length)
    $('#incident-title').textContent = active
      ? alerts.map((alert) => alertLabel(alert)).join(' · ')
      : payload.event === 'resolved' ? 'Retour à la normale' : 'Aucune anomalie en cours'
    $('#incident-detail').textContent = active
      ? messages.join(' ')
      : payload.event === 'resolved' ? 'Les capteurs sont revenus dans leurs plages de fonctionnement.' : 'Seuils surveillés : gaz < 0.50 · température < 35 °C · humidité 40–60 % · aucun mouvement.'
  }

  const alertLabel = (code: string) => ({
    gas: 'Gaz élevé détecté',
    overheat: 'Température trop élevée',
    humidity_low: 'Humidité trop basse',
    humidity_high: 'Humidité trop élevée',
    intrusion: 'Mouvement détecté',
  }[code] ?? code)

  const updateStatus = (payload: StatusPayload) => {
    const online = payload.status === 'online'
    $('#device-status').textContent = `Appareil · ${online ? 'EN LIGNE' : 'HORS LIGNE'}`
  }

  const closeClient = () => {
    if (!client) return
    client.end(true)
    client = null
  }

  connectForm.addEventListener('submit', (event) => {
    event.preventDefault()
    const host = hostInput.value.trim()
    const port = Number(portInput.value)
    currentDeviceId = deviceInput.value.trim()
    if (!host || !currentDeviceId || !Number.isInteger(port) || port < 1 || port > 65535 || /[+#/]/.test(currentDeviceId)) {
      feedback.textContent = 'Vérifie l’hôte, le port (1–65535) et l’identifiant appareil.'
      feedback.setAttribute('data-state', 'error')
      return
    }

    closeClient()
    setConnectionState('connecting', 'CONNEXION…')
    feedback.textContent = `Connexion au broker ${host}:${port}…`
    feedback.removeAttribute('data-state')
    connectButton.disabled = true
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    client = mqtt.connect(`${scheme}://${host}:${port}`, {
      clientId: `sentinel-dashboard-${Math.random().toString(16).slice(2, 10)}`,
      clean: true,
      connectTimeout: 8000,
      reconnectPeriod: 2000,
      keepalive: 30,
    })

    client.on('connect', () => {
      setConnectionState('online', 'BROKER CONNECTÉ')
      feedback.textContent = `Abonné aux topics de ${currentDeviceId}.`
      feedback.removeAttribute('data-state')
      connectButton.disabled = false
      client?.subscribe(`sentinel/edge/${currentDeviceId}/#`, { qos: 1 }, (error) => {
        if (error) feedback.textContent = `Abonnement impossible : ${error.message}`
      })
    })
    client.on('reconnect', () => {
      setConnectionState('connecting', 'RECONNEXION…')
      feedback.textContent = 'Broker indisponible. Nouvelle tentative automatique…'
    })
    client.on('close', () => {
      if (client) {
        setConnectionState('offline', 'BROKER DÉCONNECTÉ')
        connectButton.disabled = false
      }
    })
    client.on('error', (error) => {
      setConnectionState('offline', 'ERREUR MQTT')
      feedback.textContent = `Connexion impossible · ${error.message}`
      feedback.setAttribute('data-state', 'error')
      connectButton.disabled = false
    })
    client.on('message', (topic, message) => {
      let payload: IncomingPayload
      try {
        payload = JSON.parse(message.toString()) as IncomingPayload
      } catch {
        payload = { raw: message.toString() }
      }

      const topicParts = topic.split('/')
      const type = topicParts.at(-1) ?? 'unknown'
      const messageKind = type === 'alerts' ? 'alert' : type === 'commands' ? 'command' : type
      if (type !== 'alerts' || (payload as AlertPayload).event) appendMessage(topic, payload, messageKind)
      if (type === 'sensors') updateSensor(payload as SensorPayload)
      if (type === 'alerts') updateAlerts(payload as AlertPayload)
      if (type === 'status') updateStatus(payload as StatusPayload)
    })
  })

  root.querySelectorAll<HTMLButtonElement>('[data-command]').forEach((button) => {
    button.addEventListener('click', () => {
      if (!client?.connected) {
        commandFeedback.textContent = 'Action impossible · connecte-toi au broker MQTT.'
        commandFeedback.setAttribute('data-state', 'error')
        return
      }
      const command = button.dataset.command!
      const payload: Record<string, string | number> = { command }
      if (button.dataset.duration) payload.duration = Number(button.dataset.duration)
      const topic = `sentinel/edge/${currentDeviceId}/commands`
      const serialized = JSON.stringify(payload)
      client.publish(topic, serialized, { qos: 1 }, (error) => {
        if (error) {
          commandFeedback.textContent = `Échec d’envoi · ${error.message}`
          commandFeedback.setAttribute('data-state', 'error')
          return
        }
        commandFeedback.textContent = `Commande envoyée · ${command}`
        commandFeedback.removeAttribute('data-state')
        if (command === 'BUZZER_ON') $('#buzzer-state').textContent = 'ACTIF · 5 S'
        if (command === 'BUZZER_OFF' || command === 'RESET_ALERT') $('#buzzer-state').textContent = 'ARRÊTÉ'
        if (command === 'LED_RED') $('#led-state').textContent = 'ROUGE'
        if (command === 'LED_GREEN') $('#led-state').textContent = 'VERTE'
        if (command === 'LED_OFF') $('#led-state').textContent = 'ÉTEINTE'
        window.clearTimeout(commandTimeout)
        if (command === 'BUZZER_ON') commandTimeout = window.setTimeout(() => { $('#buzzer-state').textContent = 'ARRÊTÉ' }, 5000)
      })
    })
  })

  $('#clear-message-log').addEventListener('click', () => {
    messageLog.querySelectorAll('.message-entry').forEach((entry) => entry.remove())
    messageTotal = 0
    $('#message-count').textContent = '0'
    logEmpty.hidden = false
  })
}