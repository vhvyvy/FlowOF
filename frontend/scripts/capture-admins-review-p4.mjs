/**
 * П.4 screenshots: universal case detail + KPI config.
 * SCREENSHOT_TOKEN = owner JWT (tenant=1)
 */
import { chromium } from 'playwright'
import { execSync } from 'child_process'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const dir = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(dir, '..', 'screenshots', 'admins-review-p4')
const TOKEN = process.env.SCREENSHOT_TOKEN
const BASE = process.env.SCREENSHOT_BASE || 'http://localhost:3000'
const BACKEND = path.join(dir, '..', '..', 'backend')

if (!TOKEN) {
  console.error('Set SCREENSHOT_TOKEN')
  process.exit(1)
}

fs.mkdirSync(OUT, { recursive: true })

function seedAwaitingCase() {
  const out = execSync('python scripts/seed_p4_awaiting_case.py', {
    cwd: BACKEND,
    encoding: 'utf8',
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      DATABASE_URL:
        process.env.DATABASE_URL ||
        'postgresql+asyncpg://neondb_owner:npg_yDrCmcTs50xv@ep-broad-forest-alh2ugau-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require',
      SECRET_KEY: 'test-secret-key-for-local',
    },
  }).trim()
  const id = Number(out.split('\n').pop())
  if (!id) throw new Error('seed failed: ' + out)
  return id
}

function cleanupAwaitingCase() {
  execSync('python scripts/seed_p4_awaiting_case.py cleanup', {
    cwd: BACKEND,
    encoding: 'utf8',
    env: {
      ...process.env,
      PYTHONIOENCODING: 'utf-8',
      DATABASE_URL:
        process.env.DATABASE_URL ||
        'postgresql+asyncpg://neondb_owner:npg_yDrCmcTs50xv@ep-broad-forest-alh2ugau-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require',
      SECRET_KEY: 'test-secret-key-for-local',
    },
  })
}

async function authContext(browser) {
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } })
  await context.route('http://127.0.0.1:8000/**', async (route) => {
    const url = route.request().url().replace('127.0.0.1:8000', '127.0.0.1:8001')
    await route.continue({ url })
  })
  await context.route('http://localhost:8000/**', async (route) => {
    const url = route.request().url().replace('localhost:8000', '127.0.0.1:8001')
    await route.continue({ url })
  })
  await context.addCookies([
    { name: 'user_role', value: 'owner', domain: 'localhost', path: '/' },
    { name: 'is_admin', value: '0', domain: 'localhost', path: '/' },
  ])
  await context.addInitScript((t) => {
    localStorage.setItem('token', t)
    localStorage.setItem('user_role', 'owner')
    localStorage.setItem('is_admin', '0')
  }, TOKEN)
  return context
}

async function main() {
  const awaitingId = seedAwaitingCase()
  console.log('seeded awaiting case:', awaitingId)

  const browser = await chromium.launch({ headless: true })

  // а) quantitative case 2 — full page
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review/cases/2`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })
    await page.waitForSelector('text=К обзору', { timeout: 20000 })
    await page.waitForSelector('text=Метрики', { timeout: 20000 })
    await page.waitForTimeout(2000)
    await page.screenshot({ path: path.join(OUT, '01-quant-case-full.png'), fullPage: true })
    console.log('01 quant case')
    await ctx.close()
  }

  // б) closed qualitative case 46
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review/cases/46`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })
    await page.waitForSelector('text=Сработало', { timeout: 20000 })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: path.join(OUT, '02-closed-qual.png'), fullPage: true })
    console.log('02 closed qual')
    await ctx.close()
  }

  // в) awaiting_review qualitative — evaluation buttons
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review/cases/${awaitingId}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })
    await page.waitForSelector('text=Сработало +5', { timeout: 20000 })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: path.join(OUT, '03-awaiting-qual-eval.png'), fullPage: true })
    console.log('03 awaiting qual eval')
    await ctx.close()
  }

  // г) config table
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review/config`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })
    await page.waitForSelector('text=Настройки KPI', { timeout: 20000 })
    await page.waitForSelector('text=Выручка', { timeout: 20000 })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: path.join(OUT, '04-config-table.png'), fullPage: true })
    console.log('04 config table')
    await ctx.close()
  }

  // д) config modal
  {
    const ctx = await authContext(browser)
    const page = await ctx.newPage()
    await page.goto(`${BASE}/dashboard/admins-review/config`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    })
    await page.waitForSelector('text=Изменить', { timeout: 20000 })
    const rows = page.getByRole('button', { name: 'Изменить' })
    await rows.last().click()
    await page.waitForSelector('[data-testid="kpi-config-modal"]', { timeout: 10000 })
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUT, '05-config-modal.png'), fullPage: false })
    console.log('05 config modal')
    await ctx.close()
  }

  await browser.close()
  cleanupAwaitingCase()
  console.log('cleanup done')
  console.log('Done:', OUT)
}

main().catch((e) => {
  console.error(e)
  try {
    cleanupAwaitingCase()
  } catch {
    /* ignore */
  }
  process.exit(1)
})
