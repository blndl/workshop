import * as ort from 'onnxruntime-web'

export type PersonDetection = {
  class: 'person'
  score: number
  bbox: [number, number, number, number]
}

const INPUT_SIZE = 640
const PERSON_CLASS_ID = 0
const NMS_IOU_THRESHOLD = 0.45

export class YoloV8Detector {
  private readonly session: ort.InferenceSession

  private constructor(session: ort.InferenceSession) {
    this.session = session
  }

  static async load(modelUrl: string): Promise<YoloV8Detector> {
    const session = await ort.InferenceSession.create(modelUrl, {
      executionProviders: ['wasm'],
      graphOptimizationLevel: 'all',
    })
    return new YoloV8Detector(session)
  }

  async detect(video: HTMLVideoElement, threshold: number): Promise<PersonDetection[]> {
    const sourceWidth = video.videoWidth
    const sourceHeight = video.videoHeight
    const scale = Math.min(INPUT_SIZE / sourceWidth, INPUT_SIZE / sourceHeight)
    const resizedWidth = Math.round(sourceWidth * scale)
    const resizedHeight = Math.round(sourceHeight * scale)
    const padX = (INPUT_SIZE - resizedWidth) / 2
    const padY = (INPUT_SIZE - resizedHeight) / 2

    const canvas = document.createElement('canvas')
    canvas.width = INPUT_SIZE
    canvas.height = INPUT_SIZE
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) throw new Error('Impossible de préparer l’image pour YOLOv8n.')
    context.fillStyle = 'rgb(114, 114, 114)'
    context.fillRect(0, 0, INPUT_SIZE, INPUT_SIZE)
    context.drawImage(video, padX, padY, resizedWidth, resizedHeight)

    const pixels = context.getImageData(0, 0, INPUT_SIZE, INPUT_SIZE).data
    const planeSize = INPUT_SIZE * INPUT_SIZE
    const input = new Float32Array(planeSize * 3)
    for (let pixel = 0; pixel < planeSize; pixel += 1) {
      const rgbaOffset = pixel * 4
      input[pixel] = pixels[rgbaOffset] / 255
      input[planeSize + pixel] = pixels[rgbaOffset + 1] / 255
      input[planeSize * 2 + pixel] = pixels[rgbaOffset + 2] / 255
    }

    const inputTensor = new ort.Tensor('float32', input, [1, 3, INPUT_SIZE, INPUT_SIZE])
    const results = await this.session.run({ [this.session.inputNames[0]]: inputTensor })
    const output = results[this.session.outputNames[0]]
    if (!output || output.dims.length !== 3) throw new Error('Format de sortie YOLOv8n non reconnu.')

    const firstAxis = output.dims[1]
    const secondAxis = output.dims[2]
    const channelsFirst = firstAxis <= 256 && secondAxis > firstAxis
    const attributes = channelsFirst ? firstAxis : secondAxis
    const candidates = channelsFirst ? secondAxis : firstAxis
    if (attributes <= PERSON_CLASS_ID + 4) throw new Error(`Sortie YOLOv8n inattendue : ${output.dims.join(' × ')}.`)

    const data = output.data as Float32Array
    const valueAt = (candidate: number, attribute: number) => channelsFirst
      ? data[attribute * candidates + candidate]
      : data[candidate * attributes + attribute]

    const detections: PersonDetection[] = []
    for (let candidate = 0; candidate < candidates; candidate += 1) {
      const score = valueAt(candidate, PERSON_CLASS_ID + 4)
      if (score < threshold) continue

      const centerX = valueAt(candidate, 0)
      const centerY = valueAt(candidate, 1)
      const width = valueAt(candidate, 2)
      const height = valueAt(candidate, 3)
      const left = Math.max(0, Math.min(sourceWidth, (centerX - width / 2 - padX) / scale))
      const top = Math.max(0, Math.min(sourceHeight, (centerY - height / 2 - padY) / scale))
      const right = Math.max(left, Math.min(sourceWidth, (centerX + width / 2 - padX) / scale))
      const bottom = Math.max(top, Math.min(sourceHeight, (centerY + height / 2 - padY) / scale))
      if (right - left < 1 || bottom - top < 1) continue
      detections.push({ class: 'person', score, bbox: [left, top, right - left, bottom - top] })
    }

    return nonMaximumSuppression(detections)
  }
}

function nonMaximumSuppression(detections: PersonDetection[]): PersonDetection[] {
  const sorted = [...detections].sort((first, second) => second.score - first.score)
  const kept: PersonDetection[] = []
  while (sorted.length) {
    const current = sorted.shift()!
    kept.push(current)
    for (let index = sorted.length - 1; index >= 0; index -= 1) {
      if (intersectionOverUnion(current.bbox, sorted[index].bbox) > NMS_IOU_THRESHOLD) sorted.splice(index, 1)
    }
  }
  return kept
}

function intersectionOverUnion(first: PersonDetection['bbox'], second: PersonDetection['bbox']): number {
  const left = Math.max(first[0], second[0])
  const top = Math.max(first[1], second[1])
  const right = Math.min(first[0] + first[2], second[0] + second[2])
  const bottom = Math.min(first[1] + first[3], second[1] + second[3])
  const intersection = Math.max(0, right - left) * Math.max(0, bottom - top)
  const union = first[2] * first[3] + second[2] * second[3] - intersection
  return union > 0 ? intersection / union : 0
}
