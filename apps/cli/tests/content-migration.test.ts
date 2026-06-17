import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// content-volume-migration shells out via execFileSync (docker inspect / cp /
// run / rm). Stub it so the "container exists → migrate" path runs in-process
// without a daemon (the copy is a no-op, so copiedBytes is 0).
vi.mock('node:child_process', () => ({ execFileSync: vi.fn(() => Buffer.from('')) }))

import { migrateContentVolume } from '../src/services/content-volume-migration.js'

describe('migrateContentVolume — migrated path (container present)', () => {
  let dir: string
  beforeEach(() => { dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lh-cvm2-')) })
  afterEach(() => { fs.rmSync(dir, { recursive: true, force: true }); vi.restoreAllMocks() })

  it('copies container content into the volume and patches the compose file', () => {
    fs.writeFileSync(path.join(dir, 'docker-compose.yml'), [
      'name: learnhouse-dep12345',
      'services:',
      '  learnhouse-app:',
      '    image: ghcr.io/learnhouse/app:latest',
      '    container_name: learnhouse-app-dep12345',
      '    networks:',
      '      - learnhouse-network-dep12345',
      'networks:',
      '  learnhouse-network-dep12345:',
      '',
    ].join('\n'))

    // execFileSync mocked (no throw) → dockerContainerExists() is true → migrate.
    const res = migrateContentVolume(dir, 'dep12345')
    expect(res.status).toBe('migrated')
    expect(res.copiedBytes).toBe(0) // the stubbed copy moves no bytes

    const patched = fs.readFileSync(path.join(dir, 'docker-compose.yml'), 'utf-8')
    expect(patched).toContain('learnhouse_content_dep12345:/app/api/content')
  })
})
