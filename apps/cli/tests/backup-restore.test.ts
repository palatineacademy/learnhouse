import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execSync } from 'node:child_process'

// Real tar runs (execSync is NOT mocked here — tar is a deterministic system
// tool, no daemon needed). Only the database exec calls are stubbed: the dump
// writer produces a real database.sql so the archive is genuine.
const promptStub = vi.hoisted(() => ({
  log: { error: () => {}, info: () => {}, success: () => {}, warn: () => {}, warning: () => {}, message: () => {}, step: () => {} },
  intro: () => {}, outro: () => {}, cancel: () => {}, note: () => {},
  spinner: () => ({ start: () => {}, stop: () => {}, message: () => {} }),
  select: async () => 'create',
  text: async () => '',
  confirm: async () => true,
  isCancel: () => false,
}))
vi.mock('@clack/prompts', () => promptStub)
vi.mock('../src/utils/prompt.js', () => promptStub)
const dockerMock = vi.hoisted(() => ({
  isContainerRunning: vi.fn(() => true),
  autoDetectDeploymentId: vi.fn(() => 'dep1'),
  dockerExecToFile: vi.fn(),
  dockerExecFromFile: vi.fn(),
}))
vi.mock('../src/services/docker.js', () => dockerMock)

import { backupCommand } from '../src/commands/backup.js'
import { restoreCommand } from '../src/commands/restore.js'

class ProcessExit extends Error {
  code: number
  constructor(code: number) { super(`process.exit(${code})`); this.code = code }
}

describe('backup / restore — real tar, stubbed database', () => {
  let home: string
  let installDir: string
  let origHome: string | undefined

  beforeEach(() => {
    home = fs.mkdtempSync(path.join(os.tmpdir(), 'lh-br-'))
    installDir = path.join(home, '.learnhouse', 'test')
    fs.mkdirSync(installDir, { recursive: true })
    fs.writeFileSync(path.join(installDir, 'learnhouse.config.json'), JSON.stringify({
      version: '1.4.8', deploymentId: 'dep1', createdAt: '2026-01-01T00:00:00Z',
      installDir, domain: 'localhost', httpPort: 8080,
      useHttps: false, autoSsl: false, useExternalDb: false, orgSlug: 'default',
    }))
    fs.writeFileSync(path.join(installDir, '.env'), 'LEARNHOUSE_DOMAIN=localhost\n')
    origHome = process.env.HOME
    process.env.HOME = home
    dockerMock.isContainerRunning.mockReturnValue(true)
    dockerMock.autoDetectDeploymentId.mockReturnValue('dep1')
    dockerMock.dockerExecFromFile.mockReset().mockImplementation(() => {})
    dockerMock.dockerExecToFile.mockReset().mockImplementation((_c: string, _cmd: string, out: string) =>
      fs.writeFileSync(out, 'CREATE TABLE t (id int);\nDROP TABLE IF EXISTS t;\n'))
    vi.spyOn(process, 'exit').mockImplementation(((code?: number) => {
      throw new ProcessExit(code ?? 0)
    }) as never)
  })

  afterEach(() => {
    if (origHome === undefined) delete process.env.HOME; else process.env.HOME = origHome
    fs.rmSync(home, { recursive: true, force: true })
    vi.restoreAllMocks()
  })

  it('backup creates a real .tar.gz containing the dump and .env', async () => {
    await backupCommand() // non-TTY → createBackup

    const backupsDir = path.join(installDir, 'backups')
    const archives = fs.readdirSync(backupsDir).filter((f) => f.endsWith('.tar.gz'))
    expect(archives).toHaveLength(1)

    // The temp working dir must have been cleaned up — only the archive remains.
    expect(fs.readdirSync(backupsDir).filter((e) => !e.endsWith('.tar.gz'))).toHaveLength(0)

    // Extract for real and verify contents.
    const out = fs.mkdtempSync(path.join(os.tmpdir(), 'lh-br-x-'))
    execSync(`tar -xzf "${path.join(backupsDir, archives[0])}" -C "${out}"`, { stdio: 'pipe' })
    const sub = fs.readdirSync(out)[0]
    expect(fs.readFileSync(path.join(out, sub, 'database.sql'), 'utf-8')).toContain('DROP TABLE IF EXISTS')
    expect(fs.existsSync(path.join(out, sub, '.env'))).toBe(true)
    fs.rmSync(out, { recursive: true, force: true })
  })

  it('restore extracts a real archive, runs psql, and cleans up', async () => {
    await backupCommand()
    const backupsDir = path.join(installDir, 'backups')
    const archive = path.join(backupsDir, fs.readdirSync(backupsDir).find((f) => f.endsWith('.tar.gz'))!)

    await expect(restoreCommand(archive)).resolves.toBeUndefined()
    // The .restore-tmp working dir must be cleaned up afterwards.
    expect(fs.existsSync(path.join(installDir, '.restore-tmp'))).toBe(false)
  })

  it('backupCommand --restore extracts and restores from an archive', async () => {
    await backupCommand()
    const backupsDir = path.join(installDir, 'backups')
    const archive = path.join(backupsDir, fs.readdirSync(backupsDir).find((f) => f.endsWith('.tar.gz'))!)
    await expect(backupCommand(archive, { restore: true })).resolves.toBeUndefined()
  })

  it('backup exits and cleans up when the pg_dump fails', async () => {
    dockerMock.dockerExecToFile.mockImplementation(() => { throw new Error('pg_dump failed') })
    await expect(backupCommand()).rejects.toBeInstanceOf(ProcessExit)
    // The temp working dir must be removed even on failure.
    const backupsDir = path.join(installDir, 'backups')
    if (fs.existsSync(backupsDir)) {
      expect(fs.readdirSync(backupsDir).filter((e) => !e.endsWith('.tar.gz'))).toHaveLength(0)
    }
  })

  it('backup exits when the database container is not running', async () => {
    dockerMock.isContainerRunning.mockReturnValue(false)
    await expect(backupCommand()).rejects.toBeInstanceOf(ProcessExit)
  })

  it('backup and restore refuse an external database', async () => {
    fs.writeFileSync(path.join(installDir, 'learnhouse.config.json'), JSON.stringify({
      version: '1.4.8', deploymentId: 'dep1', createdAt: '2026-01-01T00:00:00Z',
      installDir, domain: 'localhost', httpPort: 8080,
      useHttps: false, autoSsl: false, useExternalDb: true, orgSlug: 'default',
    }))
    await expect(backupCommand()).rejects.toBeInstanceOf(ProcessExit)
    const dummy = path.join(installDir, 'dummy.tar.gz')
    fs.writeFileSync(dummy, 'x') // exists → restore reaches the external-db guard
    await expect(restoreCommand(dummy)).rejects.toBeInstanceOf(ProcessExit)
  })

  it('restore also restores the .env when the user confirms', async () => {
    await backupCommand()
    const backupsDir = path.join(installDir, 'backups')
    const archive = path.join(backupsDir, fs.readdirSync(backupsDir).find((f) => f.endsWith('.tar.gz'))!)
    // Change the live .env, then restore — the archived .env should come back.
    fs.writeFileSync(path.join(installDir, '.env'), 'LEARNHOUSE_DOMAIN=changed\n')
    await backupCommand(archive, { restore: true })
    expect(fs.readFileSync(path.join(installDir, '.env'), 'utf-8')).toContain('LEARNHOUSE_DOMAIN=localhost')
  })

  it('restore rejects an archive with no database.sql inside', async () => {
    // Build a tar.gz that contains a folder but no database.sql.
    const stage = fs.mkdtempSync(path.join(os.tmpdir(), 'lh-br-bad-'))
    fs.mkdirSync(path.join(stage, 'empty'))
    fs.writeFileSync(path.join(stage, 'empty', 'readme.txt'), 'no dump here')
    const bad = path.join(home, 'bad.tar.gz')
    execSync(`tar -czf "${bad}" -C "${stage}" empty`, { stdio: 'pipe' })
    fs.rmSync(stage, { recursive: true, force: true })

    await expect(restoreCommand(bad)).rejects.toBeInstanceOf(ProcessExit)
    expect(fs.existsSync(path.join(installDir, '.restore-tmp'))).toBe(false)
  })
})
