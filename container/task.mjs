/**
 * Cloud Run Jobs task: render one slice of a Remotion composition, or its whole audio track, from a
 * bundle that scripts/cloud_render.sh uploaded to the bucket.
 *
 * Task layout of one execution (CLOUD_RUN_TASK_INDEX = i):
 *   i <  VIDEO_TASKS        → muted h264 slice i of the frames  → parts/v_<i>.mp4
 *   i == VIDEO_TASKS, AUDIO → the full audio track as PCM wav    → parts/audio.wav
 * Slices are equal-length except the last, so the local side can join them with `ffmpeg concat -c copy`
 * (the same shape as a local `remotion render --frames=a-b --muted` loop).
 *
 * Env set per execution: RENDER_ID, COMPOSITION, VIDEO_TASKS, AUDIO (1|0)
 * Optional env: CONCURRENCY (default TASK_CPU), JPEG_QUALITY (90), CRF (Remotion default), SCALE (1),
 *               GL (swangle: no GPU here), TIMEOUT_MS (120000 per delayRender), X264_PRESET
 * Bucket is mounted at MOUNT (default /mnt/render) via the job's Cloud Storage volume:
 *   in : renders/<RENDER_ID>/bundle.tgz, renders/<RENDER_ID>/props.json (optional)
 *   out: renders/<RENDER_ID>/parts/*, renders/<RENDER_ID>/stats/task_<i>.json
 * Remotion settings are passed explicitly: the Node API does not read remotion.config.ts.
 */
import { spawnSync } from 'node:child_process';
import { createReadStream, createWriteStream, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { pipeline } from 'node:stream/promises';
import { openBrowser, renderMedia, selectComposition } from '@remotion/renderer';

const env = process.env;
const MOUNT = env.MOUNT || '/mnt/render';
const RID = required('RENDER_ID');
const COMPOSITION = required('COMPOSITION');
const VIDEO_TASKS = Number(required('VIDEO_TASKS'));
const AUDIO = env.AUDIO === '1';
const INDEX = Number(env.CLOUD_RUN_TASK_INDEX || 0);
const ATTEMPT = Number(env.CLOUD_RUN_TASK_ATTEMPT || 0);
const CONCURRENCY = Number(env.CONCURRENCY || env.TASK_CPU || 4);
const GL = env.GL || 'swangle';
const TIMEOUT_MS = Number(env.TIMEOUT_MS || 120000);
const REMOTE = `${MOUNT}/renders/${RID}`;

function required(name) {
  if (!env[name]) throw new Error(`missing env ${name}`);
  return env[name];
}

const log = (msg) => console.log(`[task ${INDEX} try ${ATTEMPT}] ${msg}`);
const now = () => performance.now() / 1000;

/** Which job this task index owns: a frame slice, the audio, or nothing (spare index). */
function taskKind() {
  if (INDEX < VIDEO_TASKS) return 'video';
  if (INDEX === VIDEO_TASKS && AUDIO) return 'audio';
  return 'none';
}

/** Frame range of slice INDEX: equal slices, the last one shorter. Null when the slice is empty. */
function sliceRange(total) {
  const per = Math.ceil(total / VIDEO_TASKS);
  const first = INDEX * per;
  const last = Math.min(total, first + per) - 1;
  return first > last ? null : [first, last];
}

/** Copies a local file into the mounted bucket (stream copy: FUSE has no copy_file_range). */
async function upload(local, remote) {
  mkdirSync(remote.slice(0, remote.lastIndexOf('/')), { recursive: true });
  await pipeline(createReadStream(local), createWriteStream(remote));
}

async function main() {
  const kind = taskKind();
  const stats = { task: INDEX, attempt: ATTEMPT, kind, concurrency: CONCURRENCY, startedAt: new Date().toISOString() };
  if (kind === 'none') return log('spare task index, nothing to do');

  let t = now();
  mkdirSync('/tmp/bundle', { recursive: true });
  const tar = spawnSync('tar', ['-xzf', `${REMOTE}/bundle.tgz`, '-C', '/tmp/bundle'], { stdio: 'inherit' });
  if (tar.status !== 0) throw new Error(`bundle extract failed (${tar.status})`);
  const propsFile = `${REMOTE}/props.json`;
  const inputProps = existsSync(propsFile) ? JSON.parse(readFileSync(propsFile, 'utf8')) : {};
  stats.extractSec = now() - t;

  t = now();
  const chromiumOptions = { gl: GL };
  const browser = await openBrowser('chrome', { chromiumOptions, logLevel: 'warn' });
  const composition = await selectComposition({
    serveUrl: '/tmp/bundle', id: COMPOSITION, inputProps, puppeteerInstance: browser,
    timeoutInMilliseconds: TIMEOUT_MS, logLevel: 'warn',
  });
  stats.selectSec = now() - t;
  stats.durationInFrames = composition.durationInFrames;

  const common = {
    composition, serveUrl: '/tmp/bundle', inputProps, puppeteerInstance: browser, chromiumOptions,
    concurrency: CONCURRENCY, timeoutInMilliseconds: TIMEOUT_MS, logLevel: 'warn',
  };
  let local; let remote;
  t = now();
  if (kind === 'video') {
    const range = sliceRange(composition.durationInFrames);
    if (!range) {
      await browser.close({ silent: true });
      return log('empty slice, nothing to do');
    }
    stats.frames = range;
    local = `/tmp/v_${String(INDEX).padStart(4, '0')}.mp4`;
    remote = `${REMOTE}/parts/v_${String(INDEX).padStart(4, '0')}.mp4`;
    let shown = -1;
    await renderMedia({
      ...common, codec: 'h264', muted: true, frameRange: range, outputLocation: local,
      imageFormat: 'jpeg', jpegQuality: Number(env.JPEG_QUALITY || 90), scale: Number(env.SCALE || 1),
      ...(env.CRF ? { crf: Number(env.CRF) } : {}),
      ...(env.X264_PRESET ? { x264Preset: env.X264_PRESET } : {}),
      onProgress: ({ progress, renderedFrames }) => {
        const step = Math.floor(progress * 10);
        if (step > shown) { shown = step; log(`frames ${range[0]}-${range[1]}: ${Math.round(progress * 100)}% (${renderedFrames} rendered)`); }
      },
    });
  } else {
    local = '/tmp/audio.wav';
    remote = `${REMOTE}/parts/audio.wav`;
    await renderMedia({ ...common, codec: 'wav', outputLocation: local });
  }
  stats.renderSec = now() - t;
  await browser.close({ silent: true });

  t = now();
  await upload(local, remote);
  stats.uploadSec = now() - t;
  stats.endedAt = new Date().toISOString();
  writeFileSync('/tmp/stats.json', JSON.stringify(stats, null, 1));
  await upload('/tmp/stats.json', `${REMOTE}/stats/task_${String(INDEX).padStart(4, '0')}.json`);
  log(`done ${kind}: ${JSON.stringify(stats)}`);
}

main().then(() => process.exit(0)).catch((err) => {
  console.error(`[task ${INDEX} try ${ATTEMPT}] FAILED`, err?.stack || err);
  process.exit(1);
});
