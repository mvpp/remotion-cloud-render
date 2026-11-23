/**
 * Prints a composition's {id, durationInFrames, fps, width, height} as JSON, using the Remotion renderer
 * that the project itself installed (so the version always matches the bundle).
 * Usage: node probe.mjs <project dir> <bundle dir> <composition id> [props.json]
 */
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const [projectDir, bundleDir, id, propsFile] = process.argv.slice(2);
if (!id) {
  console.error('usage: node probe.mjs <project dir> <bundle dir> <composition id> [props.json]');
  process.exit(2);
}
const require = createRequire(path.join(path.resolve(projectDir), 'package.json'));
const { selectComposition } = require('@remotion/renderer');
const inputProps = propsFile ? JSON.parse(readFileSync(propsFile, 'utf8')) : {};
const c = await selectComposition({
  serveUrl: path.resolve(bundleDir), id, inputProps, chromiumOptions: { gl: 'swangle' }, logLevel: 'error',
});
console.log(JSON.stringify({ id: c.id, durationInFrames: c.durationInFrames, fps: c.fps, width: c.width, height: c.height }));
process.exit(0);
