const initial = window.__SHOWROOM_INITIAL__
const catalog = window.__SHOWROOM_CATALOG__ ?? []
const root = document.getElementById('showroom')
const SPEEDS = [0.5, 1, 2]
const SCALES = [1, 2, 3, 4]
const XTERM_VERSION = '6.0.0'

const role = {
  assistant: { copy: '#fff8dc', glyph: '┊', tone: '#cd7f32' },
  system: { copy: '#cc9b1f', glyph: '·', tone: '#cc9b1f' },
  tool: { copy: '#cc9b1f', glyph: '⚡', tone: '#cd7f32' },
  user: { copy: '#daa520', glyph: '❯', tone: '#ffd700' }
}

const escapeHtml = value =>
  String(value ?? '').replace(
    /[&<>"']/g,
    char => ({ '&': '&amp;', '"': '&quot;', "'": '&#39;', '<': '&lt;', '>': '&gt;' })[char]
  )

const state = {
  body: null,
  composer: null,
  frameMode: false,
  frameTargets: new Map(),
  overlays: null,
  progressFill: null,
  progressLabel: null,
  raf: null,
  scale: 2,
  shell: null,
  speed: 1,
  startedAt: 0,
  statusLeft: null,
  statusRight: null,
  term: null,
  termContainer: null,
  timers: [],
  total: 0,
  viewport: null,
  workflow: initial?.workflow ?? { timeline: [] }
}

const clearTimers = () => {
  while (state.timers.length) {
    clearTimeout(state.timers.pop())
  }

  if (state.raf) {
    cancelAnimationFrame(state.raf)
    state.raf = null
  }
}

const resolveTarget = id => {
  if (!id) {
    return null
  }

  return state.frameTargets.get(id) ?? document.querySelector(`[data-target="${CSS.escape(id)}"]`)
}

const setText = (node, text = '', duration = 0) => {
  if (!duration || state.speed <= 0) {
    node.textContent = text

    return
  }

  const chars = [...text]
  const adjusted = duration / state.speed
  const started = performance.now()

  const frame = now => {
    const n = Math.min(chars.length, Math.ceil(((now - started) / adjusted) * chars.length))
    node.textContent = chars.slice(0, n).join('')

    if (n < chars.length) {
      requestAnimationFrame(frame)
    }
  }

  requestAnimationFrame(frame)
}

const removeAfter = (node, duration = 1400) => {
  const wait = duration / state.speed

  state.timers.push(
    setTimeout(() => {
      node.classList.remove('is-visible')
      state.timers.push(setTimeout(() => node.remove(), 420 / state.speed))
    }, wait)
  )
}

const rectFor = (id, pad = 8) => {
  const el = resolveTarget(id)

  if (!el || !state.overlays) {
    return null
  }

  const stage = state.overlays.getBoundingClientRect()
  const rect = el.getBoundingClientRect()

  return {
    height: rect.height + pad * 2,
    left: rect.left - stage.left - pad,
    top: rect.top - stage.top - pad,
    width: rect.width + pad * 2
  }
}

const placeNear = (node, id, position = 'right') => {
  const rect = rectFor(id, 0)

  if (!rect) {
    node.style.left = '24px'
    node.style.top = '24px'

    return
  }

  const gap = 18
  const left = position === 'left' ? rect.left - node.offsetWidth - gap : rect.left + rect.width + gap
  const top = position === 'top' ? rect.top - node.offsetHeight - gap : rect.top

  node.style.left = `${Math.max(12, left)}px`
  node.style.top = `${Math.max(12, top)}px`
}

const message = action => {
  if (state.frameMode) {
    return
  }

  const spec = role[action.role] ?? role.assistant
  const line = document.createElement('div')
  const glyph = document.createElement('span')
  const copy = document.createElement('div')

  line.className = `showroom-line showroom-line-${action.role ?? 'assistant'}`
  line.dataset.target = action.id ?? ''
  line.style.setProperty('--role', spec.tone)
  line.style.setProperty('--copy', spec.copy)

  glyph.className = 'showroom-glyph'
  glyph.textContent = spec.glyph

  copy.className = 'showroom-copy'

  line.append(glyph, copy)
  state.body.append(line)
  setText(copy, action.text, action.duration)
}

const tool = action => {
  if (state.frameMode) {
    return
  }

  const box = document.createElement('div')
  const title = document.createElement('div')
  const items = document.createElement('div')

  box.className = 'showroom-tool'
  box.dataset.target = action.id ?? ''

  title.className = 'showroom-tool-title'
  title.textContent = action.title ?? 'tool activity'

  items.className = 'showroom-tool-items'

  for (const item of action.items ?? []) {
    const row = document.createElement('div')

    row.textContent = item
    items.append(row)
  }

  box.append(title, items)
  state.body.append(box)
}

const frame = action => {
  if (!state.term || !action.ansi) {
    return
  }

  state.term.write(action.ansi)

  if (action.id) {
    state.frameTargets.set(action.id, state.termContainer)
  }
}

const fade = action => {
  const el = resolveTarget(action.target)

  if (!el) {
    return
  }

  el.style.transition = `opacity ${(action.duration ?? 420) / state.speed}ms var(--ease-in-out)`
  el.style.opacity = String(action.to ?? 0)
}

const highlight = action => {
  const el = resolveTarget(action.target)

  if (!el) {
    return
  }

  el.classList.add('is-highlighted')
  state.timers.push(setTimeout(() => el.classList.remove('is-highlighted'), (action.duration ?? 1200) / state.speed))
}

const caption = action => {
  const node = document.createElement('div')

  node.className = 'showroom-caption'
  node.dataset.target = action.id ?? ''
  node.textContent = action.text ?? ''
  state.overlays.append(node)
  placeNear(node, action.target, action.position)
  requestAnimationFrame(() => node.classList.add('is-visible'))
  removeAfter(node, action.duration ?? 1600)
}

const spotlight = action => {
  const rect = rectFor(action.target, action.pad ?? 6)

  if (!rect) {
    return
  }

  const node = document.createElement('div')

  node.className = 'showroom-spotlight'
  node.style.left = `${rect.left}px`
  node.style.top = `${rect.top}px`
  node.style.width = `${rect.width}px`
  node.style.height = `${rect.height}px`
  state.overlays.append(node)
  requestAnimationFrame(() => node.classList.add('is-visible'))
  removeAfter(node, action.duration ?? 1500)
}

const status = action => {
  state.statusLeft.textContent = action.text ?? ''
  state.statusRight.textContent = action.detail ?? ''
}

const compose = action => setText(state.composer, action.text ?? '', action.duration ?? 0)

const clearTranscript = () => {
  state.overlays.textContent = ''
  state.frameTargets.clear()

  if (state.frameMode && state.term) {
    state.term.reset()
    state.term.write('\x1b[?25l')

    return
  }

  state.body.textContent = ''
}

const ACTIONS = { caption, clear: clearTranscript, compose, fade, frame, highlight, message, spotlight, status, tool }

const fmtTime = ms => {
  if (!Number.isFinite(ms)) {
    return '0.0s'
  }

  return `${(Math.max(0, ms) / 1000).toFixed(1)}s`
}

const tickProgress = () => {
  if (!state.startedAt) {
    return
  }

  const elapsed = Math.min(state.total, (performance.now() - state.startedAt) * state.speed)
  const ratio = state.total ? elapsed / state.total : 0

  state.progressFill.style.width = `${(ratio * 100).toFixed(2)}%`
  state.progressLabel.textContent = `${fmtTime(elapsed)} / ${fmtTime(state.total)}`

  if (elapsed < state.total) {
    state.raf = requestAnimationFrame(tickProgress)
  }
}

const ensureXtermStylesheet = () => {
  const id = 'xterm-css'

  if (document.getElementById(id)) {
    return
  }

  const link = document.createElement('link')
  link.id = id
  link.rel = 'stylesheet'
  link.href = `https://cdn.jsdelivr.net/npm/@xterm/xterm@${XTERM_VERSION}/css/xterm.css`
  document.head.append(link)
}

const initXterm = async () => {
  ensureXtermStylesheet()
  const mod = await import(`https://cdn.jsdelivr.net/npm/@xterm/xterm@${XTERM_VERSION}/+esm`)
  const { Terminal } = mod

  state.term = new Terminal({
    cols: state.viewport.cols,
    rows: state.viewport.rows,
    fontFamily: 'JetBrains Mono, "SF Mono", Consolas, monospace',
    fontSize: 13,
    cursorBlink: false,
    scrollback: 0,
    convertEol: true,
    allowProposedApi: true,
    theme: {
      background: '#0a0a0a',
      foreground: '#fff8dc',
      cursor: '#ffd700',
      selectionBackground: '#3a3a55',
      black: '#0a0a0a',
      red: '#ef5350',
      green: '#8fbc8f',
      yellow: '#ffd700',
      blue: '#5a82ff',
      magenta: '#cd7f32',
      cyan: '#daa520',
      white: '#fff8dc',
      brightBlack: '#cc9b1f',
      brightRed: '#ef5350',
      brightGreen: '#8fbc8f',
      brightYellow: '#ffbf00',
      brightBlue: '#5a82ff',
      brightMagenta: '#cd7f32',
      brightCyan: '#daa520',
      brightWhite: '#fff8dc'
    }
  })

  state.term.open(state.termContainer)
  state.term.write('\x1b[?25l')
}

const play = () => {
  clearTimers()
  clearTranscript()
  state.statusLeft.textContent = ''
  state.statusRight.textContent = ''
  state.composer.textContent = state.workflow.composer ?? ''

  const timeline = [...(state.workflow.timeline ?? [])].sort((a, b) => a.at - b.at)

  state.total = timeline.reduce((max, action) => Math.max(max, action.at + (action.duration ?? 0)), 0)
  state.startedAt = performance.now()
  state.progressFill.style.width = '0%'
  state.progressLabel.textContent = `0.0s / ${fmtTime(state.total)}`

  for (const action of timeline) {
    state.timers.push(setTimeout(() => ACTIONS[action.type]?.(action), action.at / state.speed))
  }

  state.raf = requestAnimationFrame(tickProgress)
}

const setSpeed = next => {
  state.speed = next

  for (const button of state.shell.querySelectorAll('[data-segment="speed"] button')) {
    button.classList.toggle('is-active', Number(button.dataset.value) === next)
  }
}

const setScale = next => {
  state.scale = next
  state.shell.style.setProperty('--scale', `${next}`)
  state.shell.style.setProperty(
    '--stage-w',
    `${state.viewport.cols * state.viewport.cellWidth * next}px`
  )
  state.shell.style.setProperty(
    '--stage-h',
    `${state.viewport.rows * state.viewport.lineHeight * next}px`
  )

  for (const button of state.shell.querySelectorAll('[data-segment="scale"] button')) {
    button.classList.toggle('is-active', Number(button.dataset.value) === next)
  }
}

const fitScale = () => {
  const margin = 96
  const baseW = state.viewport.cols * state.viewport.cellWidth
  const baseH = state.viewport.rows * state.viewport.lineHeight
  const maxW = Math.max(1, window.innerWidth - margin)
  const maxH = Math.max(1, window.innerHeight - 240)
  const fit = Math.max(1, Math.floor(Math.min(maxW / baseW, maxH / baseH)))

  return Math.max(1, Math.min(SCALES[SCALES.length - 1], fit))
}

const loadWorkflow = async name => {
  const url = new URL(window.location.href)
  url.searchParams.set('w', name)
  window.history.replaceState(null, '', url)

  try {
    const response = await fetch(`/api/workflow/${encodeURIComponent(name)}`)

    if (response.ok) {
      state.workflow = await response.json()
    }
  } catch {
    /* fall through */
  }

  await rebuild()
}

const buildOptions = () => {
  if (!catalog.length) {
    return ''
  }

  return catalog
    .map(({ name, title }) => {
      const selected = name === initial?.name ? ' selected' : ''

      return `<option value="${escapeHtml(name)}"${selected}>${escapeHtml(title)}</option>`
    })
    .join('')
}

const buildSegmented = (values, active) =>
  values
    .map(value => `<button type="button" data-value="${value}" class="${value === active ? 'is-active' : ''}">${value}x</button>`)
    .join('')

const computeViewport = () => {
  const fromWorkflow = state.workflow.viewport ?? {}
  const usesFrames = (state.workflow.timeline ?? []).some(a => a.type === 'frame')

  return {
    cellWidth: usesFrames ? 9 : 8,
    cols: 80,
    lineHeight: usesFrames ? 19 : 18,
    rows: 24,
    scale: 2,
    ...fromWorkflow
  }
}

const renderShell = () => {
  state.viewport = computeViewport()
  state.frameMode = (state.workflow.timeline ?? []).some(a => a.type === 'frame')
  state.frameTargets.clear()

  state.shell.style.setProperty('--cell-w', `${state.viewport.cellWidth}px`)
  state.shell.style.setProperty('--cols', `${state.viewport.cols}`)
  state.shell.style.setProperty('--line-h', `${state.viewport.lineHeight}px`)
  state.shell.style.setProperty('--rows', `${state.viewport.rows}`)
  state.shell.style.setProperty('--term-w', `${state.viewport.cols * state.viewport.cellWidth}px`)
  state.shell.style.setProperty('--term-h', `${state.viewport.rows * state.viewport.lineHeight}px`)

  state.shell.innerHTML = `
    <div class="showroom-stage">
      <div class="showroom-terminal">
        <div class="showroom-status" data-target="status">
          <span class="showroom-status-left"></span>
          <span class="showroom-status-right"></span>
        </div>
        <div class="showroom-body${state.frameMode ? ' is-frame-mode' : ''}"></div>
        <div class="showroom-composer" data-target="composer"></div>
      </div>
      <div class="showroom-overlays"></div>
    </div>
    <footer class="showroom-controls">
      <button type="button" data-action="restart" title="restart (R)">↻</button>
      <span class="showroom-segmented" data-segment="scale">${buildSegmented(SCALES, state.scale)}</span>
      <span class="showroom-segmented" data-segment="speed">${buildSegmented(SPEEDS, state.speed)}</span>
      ${catalog.length > 1 ? `<select class="showroom-picker" data-action="picker">${buildOptions()}</select>` : ''}
      <span class="showroom-progress">
        <span data-role="time">0.0s / 0.0s</span>
        <div class="showroom-progress-track"><div class="showroom-progress-fill"></div></div>
      </span>
    </footer>
  `

  state.body = state.shell.querySelector('.showroom-body')
  state.composer = state.shell.querySelector('.showroom-composer')
  state.overlays = state.shell.querySelector('.showroom-overlays')
  state.statusLeft = state.shell.querySelector('.showroom-status-left')
  state.statusRight = state.shell.querySelector('.showroom-status-right')
  state.progressFill = state.shell.querySelector('.showroom-progress-fill')
  state.progressLabel = state.shell.querySelector('[data-role="time"]')

  state.shell.querySelector('[data-action="restart"]').addEventListener('click', play)

  for (const button of state.shell.querySelectorAll('[data-segment="speed"] button')) {
    button.addEventListener('click', () => setSpeed(Number(button.dataset.value)))
  }

  for (const button of state.shell.querySelectorAll('[data-segment="scale"] button')) {
    button.addEventListener('click', () => setScale(Number(button.dataset.value)))
  }

  const picker = state.shell.querySelector('[data-action="picker"]')

  if (picker) {
    picker.addEventListener('change', event => {
      void loadWorkflow(event.target.value)
    })
  }

  if (state.frameMode) {
    state.body.innerHTML = '<div class="showroom-xterm" data-target="terminal"></div>'
    state.termContainer = state.body.querySelector('.showroom-xterm')
  } else {
    state.term = null
    state.termContainer = null
  }
}

const rebuild = async () => {
  renderShell()
  setScale(state.workflow.viewport?.scale ?? fitScale())

  if (state.frameMode) {
    await initXterm()
  }

  play()
}

const mount = () => {
  state.shell = document.createElement('section')
  state.shell.className = 'showroom-shell'
  root.replaceChildren(state.shell)

  void rebuild().then(() => {
    requestAnimationFrame(() => state.shell.classList.add('is-mounted'))
  })

  window.addEventListener('keydown', event => {
    const key = event.key.toLowerCase()

    if (key === 'r') {
      play()
    } else if (key === '1' || key === '2' || key === '3') {
      setSpeed(SPEEDS[Number(key) - 1])
    }
  })
}

mount()
