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
vi.mock('../src/services/docker.js', async () => {
  const f = await import('node:fs')
  return {
    isContainerRunning: () => true,
    autoDetectDeploymentId: () => 'dep1',
    dockerExecToFile: (_c: string, _cmd: string, out: string) =>
      f.writeFileSync(out, 'CREATE TABLE t (id int);\nDROP TABLE IF EXISTS t;\n'),
    dockerExecFromFile: () => {},
  }
})

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
