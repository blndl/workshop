$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$previousScenario = $env:SCENARIO
$env:SCENARIO = 'combined_attack'
Push-Location $root
try {
  if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
  docker compose up -d --build
  if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

  $runningServices = docker compose ps --services --status running
  foreach ($service in @('mosquitto', 'edge-simulator', 'sensor-dht22', 'sensor-mq2', 'sensor-pir')) {
    if ($runningServices -notcontains $service) { throw "Required Docker service is not running: $service" }
  }
  Write-Host 'Docker sensor isolation test passed: three sensor containers and edge coordinator are running.'

  Write-Host 'Waiting for a real sensor publication from the simulator...'
  $payload = docker compose exec -T mosquitto mosquitto_sub -h localhost `
    -t 'sentinel/edge/ESP8266-001/sensors' -C 1 -W 15
  if ($LASTEXITCODE -ne 0) { throw 'No sensor payload received from Mosquitto' }
  $sensor = $payload | ConvertFrom-Json
  $fieldNames = $sensor.PSObject.Properties.Name
  foreach ($field in @('device_id', 'timestamp', 'temperature', 'humidity', 'gas', 'motion')) {
    if ($fieldNames -notcontains $field) { throw "Missing sensor field: $field" }
  }
  Write-Host "MQTT sensor receive test passed: $($sensor | ConvertTo-Json -Compress)"

  docker compose exec -T mosquitto mosquitto_pub -h localhost -t 'sentinel/edge/ESP8266-001/alerts' -r -n
  if ($LASTEXITCODE -ne 0) { throw 'Could not clear the previous retained alert before the scenario test' }
  $alertPayload = docker compose exec -T mosquitto mosquitto_sub -h localhost `
    -t 'sentinel/edge/ESP8266-001/alerts' -C 1 -W 5
  if ($LASTEXITCODE -ne 0) { throw 'No alert state received from Mosquitto' }
  $alert = $alertPayload | ConvertFrom-Json
  if ($alert.event -notin @('triggered', 'updated')) { throw "Expected an active alert event, got: $($alert.event)" }
  if (-not $alert.active -or $alert.alerts.Count -eq 0) { throw 'Alert event is not active or has no alert codes' }
  if ($alert.PSObject.Properties.Name -notcontains 'details' -or $alert.details.Count -eq 0) { throw 'Alert payload has no human-readable details' }
  foreach ($detail in $alert.details) {
    foreach ($field in @('code', 'sensor', 'severity', 'message', 'value', 'condition', 'threshold')) {
      if ($detail.PSObject.Properties.Name -notcontains $field) { throw "Alert detail is missing: $field" }
    }
    if ([string]::IsNullOrWhiteSpace($detail.message)) { throw 'Alert detail message must not be empty' }
  }
  Write-Host "MQTT alert receive test passed: $($alert | ConvertTo-Json -Compress)"

  $command = '{"command":"LED_RED"}'
  $command | docker compose exec -T mosquitto mosquitto_pub -h localhost `
    -t 'sentinel/edge/ESP8266-001/commands' -l
  if ($LASTEXITCODE -ne 0) { throw 'Could not publish MQTT command' }
  $commandReceived = $false
  for ($attempt = 0; $attempt -lt 10 -and -not $commandReceived; $attempt++) {
    Start-Sleep -Milliseconds 250
    $logs = docker compose logs --no-color edge-simulator
    $commandReceived = [bool]($logs -match '\[Command\] LED_RED')
  }
  if (-not $commandReceived) { throw "Simulator did not apply LED_RED command. Logs: $($logs -join "`n")" }
  Write-Host 'MQTT command receive test passed.'

  docker compose restart mosquitto
  if ($LASTEXITCODE -ne 0) { throw 'Could not restart Mosquitto for reconnect test' }
  $reconnectedPayload = $null
  for ($attempt = 0; $attempt -lt 15 -and -not $reconnectedPayload; $attempt++) {
    $reconnectedPayload = docker compose exec -T mosquitto mosquitto_sub -h localhost `
      -t 'sentinel/edge/ESP8266-001/sensors' -C 1 -W 2 2>$null
    if ($LASTEXITCODE -ne 0) {
      $reconnectedPayload = $null
      Start-Sleep -Seconds 1
    }
  }
  if (-not $reconnectedPayload) { throw 'Simulator did not resume sensor publication after broker restart' }
  $logs = docker compose logs --no-color edge-simulator
  if (($logs | Select-String 'MQTT connected').Count -lt 2) { throw 'Simulator did not reconnect to Mosquitto' }
  Write-Host 'MQTT reconnect test passed.'
}
finally {
  Pop-Location
  if ($null -eq $previousScenario) { Remove-Item Env:SCENARIO -ErrorAction SilentlyContinue }
  else { $env:SCENARIO = $previousScenario }
  docker compose -f (Join-Path $root 'docker-compose.yml') up -d --build
  if ($LASTEXITCODE -ne 0) { throw 'Could not restore the Docker stack to its previous scenario configuration' }
}