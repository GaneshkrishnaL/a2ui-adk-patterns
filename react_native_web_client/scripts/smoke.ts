/**
 * Headless smoke test: renders the real App inside jsdom (react-native-web on a fake DOM),
 * runs all scenarios, taps "Follow", and asserts the A2UI round-trip updated the UI.
 *
 *   corepack npm run smoke
 */
import {JSDOM} from 'jsdom';

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost:8087/?auto=1',
  pretendToBeVisual: true,
});
const w = dom.window as any;
// Expose every browser global jsdom provides (Lit + react-native-web touch many of them).
for (const k of Object.getOwnPropertyNames(w)) {
  if (k in globalThis) continue;
  try {
    Object.defineProperty(globalThis, k, {value: w[k], configurable: true, writable: true});
  } catch {}
}
for (const k of ['window', 'document', 'navigator', 'location', 'history', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame']) {
  try {
    Object.defineProperty(globalThis, k, {value: w[k], configurable: true, writable: true});
  } catch {}
}
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = false;

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
const text = () => w.document.body.textContent ?? '';
let failures = 0;
const expect = (label: string, cond: boolean) => {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}`);
  if (!cond) failures++;
};

(async () => {
  const React = (await import('react')).default;
  const {createRoot} = await import('react-dom/client');
  const {default: App} = await import('../src/App');

  createRoot(w.document.getElementById('root')).render(React.createElement(App));
  await sleep(600);

  // --- Scenario 1: Composer JSON on the Basic Catalog
  expect('S1 renders name "Sarah Chen"', text().includes('Sarah Chen'));
  expect('S1 renders handle "@sarahchen"', text().includes('@sarahchen'));
  expect('S1 formatNumber(12400) -> "12,400"', text().includes('12,400'));
  expect('S1 renders button label "Follow"', text().includes('Follow'));

  // --- Scenario 2: custom catalog
  expect('S2 custom StatTile compact value "98.2K"', text().includes('98.2K'));
  expect('S2 custom initials() inside formatString -> "Recent posts by SC"', text().includes('Recent posts by SC'));
  expect('S2 collection template rendered post titles', text().includes('Designing for trust') && text().includes('Figma → A2UI'));
  expect('S2 relative path in template "♥ 1,204"', text().includes('♥ 1,204'));

  // --- Scenario 3: form
  expect('S3 live formatString preview present', text().includes('Live preview'));
  expect('No unsupported components', !text().includes('Unsupported component'));
  expect('No MessageProcessor rejections', !text().includes('Rejected by MessageProcessor'));

  // --- Interaction: tap Follow -> action -> mock agent -> updateDataModel -> re-render
  const buttons = [...w.document.querySelectorAll('[role="button"], [tabindex="0"]')] as HTMLElement[];
  const follow = buttons.find(b => b.textContent?.trim() === 'Follow');
  expect('Found "Follow" button', Boolean(follow));
  follow?.click();
  await sleep(900);
  expect('Action logged as "→ agent"', text().includes('action "follow"'));
  expect('Agent reply applied: label became "Following ✓"', text().includes('Following ✓'));
  expect('Follower count re-formatted reactively "12,401"', text().includes('12,401'));

  console.log(failures === 0 ? '\nALL CHECKS PASSED' : `\n${failures} CHECK(S) FAILED`);
  process.exit(failures === 0 ? 0 : 1);
})().catch(e => {
  console.error('SMOKE TEST CRASHED', e);
  process.exit(1);
});
