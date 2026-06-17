import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// Docker helpers shell out via execSync — stub it so guard-path tests never
// touch a real daemon. spawn/spawnSync stay real (importActual).
vi.mock('node:child_process', async () => {
  const actual = await vi.importActual<typeof import('node:child_process')>('node:child_process')
  return { ...actual, execSync: vi.fn(() => Buffer.from('')) }
})

// Replace both prompt modules with non-blocking stubs: logs/intro/spinner are
// no-ops and every interactive prompt resolves to a "cancel" sentinel, so a
// command that reaches a prompt (e.g. the menu-first `deployments`) cancels and
// exits cleanly instead of blocking on stdin.
const promptStub = vi.hoisted(() => {
  const cancel = Symbol('cancel')
  const noop = () => {}
  return {
    log: { error: noop, info: noop, success: noop, warn: noop, warning: noop, message: noop, step: noop },
    intro: noop, outro: noop, cancel: noop, note: noop, group: noop,
    spinner: () => ({ start: noop, stop: noop, message: noop }),
    select: async () => cancel,
    multiselect: async () => cancel,
    text: async () => cancel,
    password: async () => cancel,
    confirm: async () => false,
    isCancel: (v: unknown) => v === cancel,
  }
})
vi.mock('@clack/prompts', () => promptStub)
vi.mock('../src/utils/prompt.js', () => promptStub)

import { configCommand } from '../src/commands/config.js'
import { statusCommand } from '../src/commands/status.js'
import { startCommand } from '../src/commands/start.js'
import { stopCommand } from '../src/commands/stop.js'
import { healthCommand } from '../src/commands/health.js'
import { shellCommand } from '../src/commands/shell.js'
import { logsCommand } from '../src/commands/logs.js'
import { scaleCommand, parseMemLimit, setMemLimit } from '../src/commands/scale.js'
import { envCommand } from '../src/commands/env.js'
import { deploymentsCommand } from '../src/commands/deployments.js'
import { backupCommand } from '../src/commands/backup.js'
import { restoreCommand } from '../src/commands/restore.js'
import { updateCommand } from '../src/commands/update.js'
import { checkDevEnv } from '../src/services/env-check.js'

// ─── Command guards — every entry point must bail cleanly with no install ──
//
// Each command resolves an install, then `process.exit(1)`s when none exists.
// Real process.exit would terminate; the code after it assumes a non-null
// config, so a test mock MUST throw to model termination. We point HOME at an
// empty dir so findInstallDir (via os.homedir) sees no installations.

class ProcessExit extends Error {
  code: number
  constructor(code: number) { super(`process.exit(${code})`); this.code = code }
}

describe('command guards — no installation / bad arguments', () => {
  let emptyHome: string
  let origHome: string | undefined

  beforeEach(() => {
    emptyHome = fs.mkdtempSync(path.join(os.tmpdir(), 'lh-cmdguard-'))
    origHome = process.env.HOME
    process.env.HOME = emptyHome
    vi.spyOn(process, 'exit').mockImplementation(((code?: number) => {
      throw new ProcessExit(code ?? 0)
    }) as never)
  })

  afterEach(() => {
    if (origHome === undefined) delete process.env.HOME; else process.env.HOME = origHome
    fs.rmSync(emptyHome, { recursive: true, force: true })
    vi.restoreAllMocks()
  })

  it.each([
    ['config', () => configCommand()],
    ['status', () => statusCommand()],
    ['start', () => startCommand()],
    ['stop', () => stopCommand()],
    ['health', () => healthCommand()],
    ['shell', () => shellCommand()],
    ['logs', () => logsCommand()],
    ['scale', () => scaleCommand()],
    ['env', () => envCommand()],
    ['backup', () => backupCommand()],
    ['update', () => updateCommand({})],
  ])('%s exits when no installation exists', async (_name, run) => {
    await expect(run()).rejects.toBeInstanceOf(ProcessExit)
  })

  it('restore exits when called with no archive argument', async () => {
    await expect(restoreCommand('')).rejects.toBeInstanceOf(ProcessExit)
  })

  it('restore exits when the archive path does not exist', async () => {
    await expect(restoreCommand(path.join(emptyHome, 'nope.tar.gz'))).rejects.toBeInstanceOf(ProcessExit)
  })

  it('deployments (menu-first) exits cleanly when the menu is dismissed', async () => {
    // deployments has no install guard — it opens a select menu; a cancelled
    // selection must exit(0), not crash or hang.
    await expect(deploymentsCommand()).rejects.toBeInstanceOf(ProcessExit)
  })
})

// ─── scale — compose mem_limit parse / set (pure) ───────────
//
// `scale` reads and rewrites mem_limit lines in docker-compose.yml. These
// are the exact text transforms, exercised without Docker.

describe('scale — mem_limit parse/set', () => {
  const compose = [
    'services:',
    '  learnhouse-app:',
    '    image: ghcr.io/learnhouse/app:latest',
    '    container_name: learnhouse-app-dep1',
    '    mem_limit: 2g',
    '  db:',
    '    image: pgvector/pgvector:pg16',
    '    container_name: learnhouse-db-dep1',
    '  redis:',
    '    image: redis:7-alpine',
    '    container_name: learnhouse-redis-dep1',
    '',
  ].join('\n')

  let dir: string
  beforeEach(() => { dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lh-scale-')) })
  afterEach(() => { fs.rmSync(dir, { recursive: true, force: true }) })

  it('parseMemLimit reads existing limits and omits services without one', () => {
    const p = path.join(dir, 'docker-compose.yml')
    fs.writeFileSync(p, compose)
    const limits = parseMemLimit(p)
    expect(limits.get('learnhouse-app')).toBe('2g')
    expect(limits.has('db')).toBe(false)
    expect(limits.has('redis')).toBe(false)
  })

  it('setMemLimit replaces an existing mem_limit in place', () => {
    const updated = setMemLimit(compose, 'learnhouse-app', '512m')
    fs.writeFileSync(path.join(dir, 'docker-compose.yml'), updated)
    expect(parseMemLimit(path.join(dir, 'docker-compose.yml')).get('learnhouse-app')).toBe('512m')
  })

  it('setMemLimit inserts a new mem_limit after container_name', () => {
    const updated = setMemLimit(compose, 'db', '1g')
    expect(updated).toMatch(/container_name: learnhouse-db-dep1\n {4}mem_limit: 1g/)
    fs.writeFileSync(path.join(dir, 'docker-compose.yml'), updated)
    expect(parseMemLimit(path.join(dir, 'docker-compose.yml')).get('db')).toBe('1g')
  })

  it('setMemLimit round-trips for every standard service', () => {
    let c = compose
    c = setMemLimit(c, 'learnhouse-app', '4g')
    c = setMemLimit(c, 'db', '1g')
    c = setMemLimit(c, 'redis', '256m')
    fs.writeFileSync(path.join(dir, 'docker-compose.yml'), c)
    const limits = parseMemLimit(path.join(dir, 'docker-compose.yml'))
    expect(limits.get('learnhouse-app')).toBe('4g')
    expect(limits.get('db')).toBe('1g')
    expect(limits.get('redis')).toBe('256m')
  })
})

// ─── dev pre-flight — checkDevEnv (the dev command's env gate) ───
//
// `dev` spawns the real API/Web servers (not unit-testable), but its
// pre-flight env check is pure fs: it scans apps/*/.env for required vars
// and only prompts when something is missing. Both outcomes are covered;
// the missing-vars prompt is auto-cancelled by the stubbed select above.

describe('checkDevEnv', () => {
  let root: string
  beforeEach(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), 'lh-dev-')) })
  afterEach(() => { fs.rmSync(root, { recursive: true, force: true }) })

  function writeEnv(rel: string, body: string) {
    const full = path.join(root, rel)
    fs.mkdirSync(path.dirname(full), { recursive: true })
    fs.writeFileSync(full, body)
  }

  it('returns true when every required dev var is present', async () => {
    writeEnv('apps/api/.env',
      'LEARNHOUSE_AUTH_JWT_SECRET_KEY=jwt\nCOLLAB_INTERNAL_KEY=collab\n')
    writeEnv('apps/web/.env.local',
      'NEXT_PUBLIC_LEARNHOUSE_BACKEND_URL=http://localhost:9000\n')
    writeEnv('apps/collab/.env',
      'COLLAB_PORT=4000\nLEARNHOUSE_API_URL=http://localhost:9000\n' +
      'LEARNHOUSE_AUTH_JWT_SECRET_KEY=jwt\nCOLLAB_INTERNAL_KEY=collab\n')

    expect(await checkDevEnv(root)).toBe(true)
  })

  it('returns false when required vars are missing and the fix prompt is cancelled', async () => {
    // No env files at all → everything missing → prompt → (stub cancels) → false
    expect(await checkDevEnv(root)).toBe(false)
  })
})
