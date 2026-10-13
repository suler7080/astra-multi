import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const i18nFilePath = path.resolve(__dirname, '../src/i18nContext.ts');

function extractKeys(content, dictName) {
  const dictStartRegex = new RegExp(`${dictName}:\\s*\\{`);
  const match = content.match(dictStartRegex);
  if (!match || match.index === undefined) {
    throw new Error(`Could not find ${dictName} dictionary in ${i18nFilePath}`);
  }

  const startIdx = match.index + match[0].length;
  let depth = 1;
  let endIdx = startIdx;

  for (let i = startIdx; i < content.length; i++) {
    if (content[i] === '{') depth++;
    else if (content[i] === '}') {
      depth--;
      if (depth === 0) {
        endIdx = i;
        break;
      }
    }
  }

  const dictBody = content.slice(startIdx, endIdx);
  const keys = new Set();
  const lineRegex = /^\s*([a-zA-Z0-9_]+)\s*:/gm;
  let lineMatch;
  while ((lineMatch = lineRegex.exec(dictBody)) !== null) {
    keys.add(lineMatch[1]);
  }
  return keys;
}

try {
  const content = fs.readFileSync(i18nFilePath, 'utf-8');
  const enKeys = extractKeys(content, 'EN');
  const vnKeys = extractKeys(content, 'VN');

  const missingInVN = [...enKeys].filter((k) => !vnKeys.has(k));
  const missingInEN = [...vnKeys].filter((k) => !enKeys.has(k));

  let hasError = false;

  if (missingInVN.length > 0) {
    console.error(`❌ Keys present in EN but missing in VN (${missingInVN.length}):`);
    for (const key of missingInVN) {
      console.error(`   - ${key}`);
    }
    hasError = true;
  }

  if (missingInEN.length > 0) {
    console.error(`❌ Keys present in VN but missing in EN (${missingInEN.length}):`);
    for (const key of missingInEN) {
      console.error(`   - ${key}`);
    }
    hasError = true;
  }

  if (hasError) {
    console.error('\n❌ i18n parity check failed.');
    process.exit(1);
  } else {
    console.log(`✓ i18n parity check passed! All ${enKeys.size} keys are 100% synchronized between EN and VN.`);
    process.exit(0);
  }
} catch (err) {
  console.error('Error verifying i18n parity:', err);
  process.exit(1);
}
