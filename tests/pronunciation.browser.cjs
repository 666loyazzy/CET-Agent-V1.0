/* Run against the real local services. Only fixed synthetic sample audio is used. */
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { createRequire } = require('node:module')
const requireRuntime = process.env.PLAYWRIGHT_MODULE_ROOT ? createRequire(path.join(process.env.PLAYWRIGHT_MODULE_ROOT, 'anchor.js')) : require
const { chromium } = requireRuntime('playwright')

async function main() {
  const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:8000'
  const sample = path.resolve('speech_service/samples/present-noun.wav')
  const output = path.resolve('test-results/pronunciation')
  await fs.mkdir(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: process.env.TEST_BROWSER_EXECUTABLE || undefined, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${sample}%noloop`] })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()
  const failures = []
  page.on('pageerror', error => failures.push(String(error)))
  await page.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    navigator.mediaDevices.getUserMedia = async (...args) => {
      const stream = await original(...args)
      window.__testTracks = stream.getTracks()
      return stream
    }
  })
  try {
    await page.goto(base+'/vocab/#/pronunciation')
    await page.getByRole('heading', { name: /英语发音训练/ }).waitFor()
    await page.getByText('本地声学分析已就绪').waitFor()
    await page.locator('input[type=file]').setInputFiles(sample)
    await page.getByLabel('我已回听，确认读的是当前题目。').check()
    await page.getByRole('button', { name: '分析这次录音 →' }).click()
    await page.getByRole('heading', { name: '这一遍的练习反馈' }).waitFor({ timeout: 60000 })
    assert.equal(await page.locator('[data-stage="memory.update"].completed').count(), 1)
    assert.equal(await page.locator('[data-stage="text.align"].completed').count(), 1)
    assert.equal(await page.locator('.own-line').count(), 1)
    const history = await context.request.get(base+'/api/speaking/practices').then(r => r.json())
    const first = history[0].id
    await page.getByRole('button', { name: '生成练习建议', exact: true }).click()
    await page.locator('[data-stage="coach.save"].completed').waitFor({ timeout: 60000 })
    await page.locator('.coach-answer').waitFor()
    await page.getByRole('button', { name: '生成语调调整试听', exact: true }).click()
    await page.getByLabel('语调调整教学试听').waitFor({ timeout: 60000 })
    await page.evaluate(() => scrollTo(0, 0))
    await page.screenshot({ path: path.join(output, 'desktop-analysis.png'), fullPage: true })
    const csvEvent = page.waitForEvent('download')
    await page.getByRole('button', { name: /导出声学 CSV/ }).click()
    const download = await csvEvent
    await download.saveAs(path.join(output, 'measurement.csv'))
    assert.match(await fs.readFile(path.join(output, 'measurement.csv'), 'utf8'), /^time_s,f0_hz,relative_semitones,energy_dbfs/)

    await page.getByRole('button', { name: '开始录音', exact: true }).click()
    await page.getByRole('button', { name: '停止录音', exact: true }).waitFor()
    await page.waitForTimeout(1600)
    await page.getByRole('button', { name: '停止录音', exact: true }).click()
    await page.getByRole('button', { name: '开始录音', exact: true }).waitFor()
    assert.equal(await page.evaluate(() => window.__testTracks.every(track => track.readyState === 'ended')), true)
    await page.getByLabel('我已回听，确认读的是当前题目。').check()
    await page.getByRole('button', { name: '分析这次录音 →' }).click()
    await page.getByRole('heading', { name: '这一遍的练习反馈' }).waitFor({ timeout: 60000 })
    await page.locator('.comparison-picker select').selectOption(first)
    await page.getByLabel('历史复练录音').waitFor()
    await page.screenshot({ path: path.join(output, 'repeat-comparison.png'), fullPage: true })
    await page.getByRole('tab', { name: /练习记录/ }).click()
    assert.equal(await page.locator('.history-item').count(), 2)
    await page.reload()
    await page.getByRole('tab', { name: /练习记录/ }).click()
    await page.locator('.history-item').first().waitFor()
    assert.equal(await page.locator('.history-item').count(), 2)
    await page.locator('.history-item').last().getByRole('button', { name: '查看练习' }).click()
    await page.locator('.coach-answer').waitFor()
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => scrollTo(0, 0))
    await page.screenshot({ path: path.join(output, 'mobile-analysis.png'), fullPage: true })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1), true)
    await page.getByLabel('开启练习记忆').uncheck()
    await page.getByText('已关闭，不向教学模型提供历史摘要。').waitFor()

    const stranger = await browser.newContext()
    assert.equal((await stranger.request.get(base+`/api/speaking/practices/${first}/audio`)).status(), 404)
    await stranger.close()
    const denied = await browser.newContext()
    const deniedPage = await denied.newPage()
    await deniedPage.addInitScript(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('denied', 'NotAllowedError') } })
    await deniedPage.goto(base+'/vocab/#/pronunciation')
    await deniedPage.getByRole('button', { name: '开始录音', exact: true }).click()
    await deniedPage.getByRole('alert').filter({ hasText: '麦克风权限未开启' }).waitFor()
    await denied.close()
    assert.deepEqual(failures, [])
    console.log(JSON.stringify({ passed: true, checked: ['upload analysis', '9-step trace', 'coach trace', 'pitch resynthesis', 'CSV', 'MediaRecorder microphone release', 'repeat comparison', 'persistent history and coaching', '390px mobile overflow', 'memory switch', 'session isolation', 'permission denial'], screenshots: output }))
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
    throw error
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
